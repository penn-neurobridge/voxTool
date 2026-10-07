"""Connect VoxTool to Pennsieve without the terminal.

`pennsieve profile create` takes an API key and secret in a terminal. This does
the same from VoxTool: check the key with Pennsieve, write it into the CLI's own
config as a new profile, restart the agent so it sees the profile (it reads its
config only at start), and switch to it. Switching between saved profiles is
the same minus the first two steps.

This is the one place VoxTool handles a real API key, which, unlike the agent's
session token, never expires. So the key and secret are:

- checked with Pennsieve before anything is written;
- written only to ~/.pennsieve/config.ini, where the terminal command puts
  them, and that file is then made readable by this user alone;
- never logged, returned, or put in an error. Every failure in this module is
  reported in its own words, with `from None`, never in an exception's text.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request

import pennsieve_api
import pennsieve_sync
from pennsieve_sync import PennsieveError

API_HOST = "https://api.pennsieve.io"
_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Config sections that are not profiles, and a name the CLI refuses.
_NOT_PROFILES = {"agent", "global", "migration", "pennsieve"}


class PennsieveBusy(PennsieveError):
    """The agent may be uploading; restarting it now could cut that off."""


def config_path() -> str:
    return os.path.expanduser("~/.pennsieve/config.ini")


def _read_config() -> dict[str, dict[str, str]]:
    """Section -> key -> value, with keys above the first header as "default".

    That is where the CLI writes its default profile, and configparser rejects
    the layout while quoting the offending line, a secret, in its error. So it
    is scanned by hand.
    """
    sections: dict[str, dict[str, str]] = {}
    current = "default"
    try:
        with open(config_path(), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(("#", ";")):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1].strip()
                    sections.setdefault(current, {})
                elif "=" in line:
                    key, value = (part.strip() for part in line.split("=", 1))
                    sections.setdefault(current, {})[key.lower()] = value
    except (OSError, UnicodeDecodeError):
        return {}
    return sections


def profiles() -> list[str]:
    """Names of the profiles saved in the CLI's config. Names only."""
    return sorted(
        name for name, keys in _read_config().items()
        if name.lower() not in _NOT_PROFILES and "api_token" in keys
    )


def _http_json(url: str, body: dict | None = None, headers: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _jwt_claims(token: str) -> dict:
    """A JWT's payload, unverified: it came straight from Cognito over TLS and is
    only read to learn the workspace, never trusted for access."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def verify(api_key: str, api_secret: str) -> dict:
    """Sign in with the key as the Pennsieve clients do, and say whose it is.

    Cognito's USER_PASSWORD_AUTH with the key as username and the secret as
    password (as pennsieve-go's Authenticate does), then the workspace from the
    ID token's claims. Nothing is written.
    """
    if not (_ID.match(api_key) and _ID.match(api_secret)):
        raise PennsieveError(
            "That doesn't look like a Pennsieve API key and secret: both are long "
            "IDs like 1a2b3c4d-5e6f-…. Copy each one in full."
        )
    try:
        pool = _http_json(f"{API_HOST}/authentication/cognito-config")["tokenPool"]
        auth = _http_json(
            f"https://cognito-idp.{pool['region']}.amazonaws.com/",
            {
                "AuthFlow": "USER_PASSWORD_AUTH",
                "ClientId": pool["appClientId"],
                "AuthParameters": {"USERNAME": api_key, "PASSWORD": api_secret},
            },
            {
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            },
        )["AuthenticationResult"]
    except urllib.error.HTTPError as e:
        if e.code == 400:
            raise PennsieveError(
                "Pennsieve did not accept that key and secret. Check both were "
                "copied in full, and that the key has not been deleted."
            ) from None
        raise PennsieveError(f"Pennsieve's sign-in answered {e.code}. Try again shortly.") from None
    except (urllib.error.URLError, OSError, KeyError, ValueError, TypeError):
        raise PennsieveError("Could not reach Pennsieve to check the key.") from None

    workspace_id = _jwt_claims(auth.get("IdToken", "")).get("custom:organization_node_id", "")
    headers = {
        "Authorization": f"Bearer {auth.get('AccessToken', '')}",
        "X-ORGANIZATION-ID": workspace_id,
    }
    try:
        workspace = _http_json(f"{API_HOST}/organizations/{workspace_id}", headers=headers)
        user = _http_json(f"{API_HOST}/user/", headers=headers)
        name = workspace["organization"]["name"]
    except (urllib.error.URLError, OSError, KeyError, ValueError, TypeError):
        raise PennsieveError(
            "The key works, but Pennsieve would not say which workspace it is for."
        ) from None
    return {
        "workspace": name,
        "workspace_id": workspace_id,
        "user": f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
    }


def _profile_name(workspace: str, taken: list[str]) -> str:
    """`Penn CNT` -> `penn-cnt`, made unique among the saved profiles."""
    base = re.sub(r"[^a-z0-9]+", "-", workspace.lower()).strip("-") or "workspace"
    if base in _NOT_PROFILES:
        base = f"{base}-workspace"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


_FRESH_CONFIG = """[agent]
port=9000
upload_chunk_size=32
upload_workers=10
useconfigfile=true
db_path={db_path}

[global]
default_profile={profile}
"""


def _save_profile(name: str, api_key: str, api_secret: str) -> None:
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fresh = not os.path.isfile(path)
    # Created private, and made private if it was not: it holds every key.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        if fresh:
            # Mirrors what the CLI's own setup writes; untested on a machine
            # that has never run it.
            f.write(_FRESH_CONFIG.format(
                db_path=os.path.join(os.path.dirname(path), "pennsieve_agent.db"),
                profile=name,
            ))
        f.write(f"\n[{name}]\napi_token={api_key}\napi_secret={api_secret}\n")
    os.chmod(path, 0o600)


def _uploads_waiting() -> int:
    """Uploads that were still running when the dialog stopped waiting.

    Those keep their staged files in the outbox until the agent has sent them,
    and restarting the agent would cut them off.
    """
    try:
        return len(os.listdir(pennsieve_sync.outbox_dir()))
    except OSError:
        return 0


def _restart_agent() -> None:
    pennsieve_sync._run(["agent", "stop"])
    if not pennsieve_sync.start_agent(wait=20):
        raise PennsieveError("The Pennsieve agent did not come back after restarting.")


def _whoami() -> dict:
    _, out = pennsieve_sync._run(["whoami"])
    info = {}
    for cells in pennsieve_sync._table_rows(out):
        if len(cells) == 2:
            info[cells[0].upper()] = cells[1]
    return {
        "user": info.get("NAME", ""),
        "workspace": info.get("ORGANIZATION", ""),
        "workspace_id": info.get("ORGANIZATION ID", ""),
    }


def _active_profile() -> str:
    _, out = pennsieve_sync._run(["profile", "show"], timeout=15)
    m = re.search(r"Current profile:\s*(\S+)", out)
    return m.group(1) if m else ""


def switch(profile: str, expected_workspace_id: str = "", force: bool = False) -> dict:
    """Make `profile` the agent's active and default profile, and prove it."""
    if profile not in profiles():
        raise PennsieveError(f"There is no saved Pennsieve profile called {profile}.")
    if _active_profile() != profile:
        try:
            _, out = pennsieve_sync._run(["profile", "switch", profile], timeout=20)
            # Saved after the agent started, so it has not read it yet.
            needs_restart = "not found" in out.lower()
        except pennsieve_sync.PennsieveTimeout:
            # Agent 1.8.10 bug: each upload leaves a goroutine that, after its
            # 15-minute verify window, blocks forever on a channel nobody reads,
            # and SwitchProfile then blocks forever trying to cancel it. Only a
            # restart clears it.
            needs_restart = True
        if needs_restart:
            if not force and _uploads_waiting():
                raise PennsieveBusy(
                    "Switching needs the Pennsieve agent restarted, and an upload may "
                    "still be running in it. Wait for it to finish, or switch anyway."
                )
            _restart_agent()
            pennsieve_sync._run(["profile", "switch", profile], timeout=20)
    pennsieve_sync._run(["profile", "set-default", profile])

    # The token VoxTool holds belongs to the previous profile.
    pennsieve_api._session = None
    who = _whoami()
    if not who["workspace_id"] or (
        expected_workspace_id and who["workspace_id"] != expected_workspace_id
    ):
        raise PennsieveError(
            f"Pennsieve did not switch to {profile}. It still reports "
            f"{who['workspace'] or 'no workspace'}."
        )
    return {"profile": profile, **who}


def connect(api_key: str, api_secret: str, force: bool = False) -> dict:
    """Check a key, save it as a profile named after its workspace, switch to it."""
    api_key, api_secret = api_key.strip(), api_secret.strip()
    account = verify(api_key, api_secret)

    config = _read_config()
    existing = next(
        (name for name in profiles() if config[name].get("api_token") == api_key), None
    )
    if existing:
        # Saved already; just make it the active one.
        return {**switch(existing, account["workspace_id"], force), "new": False}

    if not force and _uploads_waiting():
        raise PennsieveBusy(
            "Connecting restarts the Pennsieve agent, and an upload may still be "
            "running in it. Wait for it to finish, or connect anyway."
        )
    name = _profile_name(account["workspace"], profiles())
    _save_profile(name, api_key, api_secret)
    _restart_agent()
    return {**switch(name, account["workspace_id"], force=True), "new": True}
