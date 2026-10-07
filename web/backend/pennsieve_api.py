"""Browse Pennsieve datasets and download scans, through the REST API.

The CLI cannot do either: it has no command to list a dataset's folders, and
`download package` writes into the agent's working directory in the background
without saying where. So these go to the REST API directly.

The session token comes from the running agent's `ReAuthenticate` call — the
same route Pennsieve's own Python client takes — so VoxTool still never reads
the API key, and the token always belongs to the profile the agent is signed in
to, the same one uploads go through. It lives in memory only and expires within
the hour.

Reads honour VOXTOOL_PENNSIEVE_DATASETS just as uploads do: while the list is
set, nothing outside it can be browsed or downloaded either.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import local_mode
from pennsieve_sync import PennsieveError, allowed_datasets

_NIFTI = (".nii", ".nii.gz")


@dataclass
class Session:
    token: str
    expires: float
    organization_id: str
    api_host: str


_session: Session | None = None


def _agent_address() -> str:
    """The agent's gRPC port, from the same config file the CLI reads.

    Not through configparser: the CLI writes the default profile's API key and
    secret above the first section header, configparser rejects that, and its
    error quotes the offending line — which put a secret in the server log. So
    the file is scanned for the one value needed, and nothing read from it is
    ever repeated in an error.
    """
    port, section = "9000", ""
    try:
        with open(os.path.expanduser("~/.pennsieve/config.ini"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip().lower()
                elif section == "agent" and "=" in line:
                    key, value = (part.strip() for part in line.split("=", 1))
                    if key.lower() == "port" and value.isdigit():
                        port = value
    except (OSError, UnicodeDecodeError):
        pass
    return f"127.0.0.1:{port}"


def session() -> Session:
    """A token for the agent's signed-in profile, refreshed when near expiry."""
    global _session
    if _session is None or _session.expires - time.time() < 120:
        _session = _new_session()
    return _session


def _new_session() -> Session:
    try:
        import grpc
        from pennsieve_agent import agent_pb2
    except ImportError as e:
        raise PennsieveError(
            "Pennsieve browsing needs grpcio and protobuf "
            "(pip install -r requirements-desktop.txt)."
        ) from e

    channel = grpc.insecure_channel(_agent_address())
    try:
        reauthenticate = channel.unary_unary(
            "/v1.Agent/ReAuthenticate",
            request_serializer=agent_pb2.ReAuthenticateRequest.SerializeToString,
            response_deserializer=agent_pb2.UserResponse.FromString,
        )
        user = reauthenticate(agent_pb2.ReAuthenticateRequest(), timeout=30)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNAVAILABLE:
            raise PennsieveError("The Pennsieve agent is not running.") from e
        raise PennsieveError(f"The Pennsieve agent could not sign in: {e.details()}") from e
    finally:
        channel.close()

    if not user.session_token:
        raise PennsieveError("The Pennsieve agent is not signed in to any profile.")
    return Session(
        token=user.session_token,
        expires=float(user.token_expire),
        organization_id=user.organization_id,
        api_host=(user.api_host or "https://api.pennsieve.io").rstrip("/"),
    )


def _get(path: str, params: dict | None = None, retry: bool = True) -> dict:
    global _session
    s = session()
    url = s.api_host + path + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {s.token}",
        "X-ORGANIZATION-ID": s.organization_id,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry:
            # Signed out or switched profile since the token was issued.
            _session = None
            return _get(path, params, retry=False)
        if e.code == 404:
            raise PennsieveError("Pennsieve has nothing with that ID, or this account cannot see it.") from e
        if e.code == 403:
            raise PennsieveError("This Pennsieve account does not have access to that.") from e
        raise PennsieveError(f"Pennsieve answered {e.code} for {path}.") from e
    except urllib.error.URLError as e:
        raise PennsieveError(f"Could not reach Pennsieve: {e.reason}") from e


def _quote(node_id: str) -> str:
    """Escape an ID for a URL path, keeping the colons in `N:package:…` as the
    API's own clients send them."""
    return urllib.parse.quote(node_id, safe=":")


def _check_allowed(dataset_id: str) -> None:
    allowed = allowed_datasets()
    if allowed and dataset_id not in allowed:
        raise PennsieveError(
            "That is outside the datasets this machine is set up for "
            f"({', '.join(sorted(allowed))}, VOXTOOL_PENNSIEVE_DATASETS)."
        )


def _item(child: dict) -> dict:
    content = child.get("content", {})
    return {
        "id": content.get("nodeId", ""),
        "name": content.get("name", ""),
        "folder": content.get("packageType") == "Collection",
        "bytes": child.get("storage"),
        "scan": content.get("name", "").lower().endswith(_NIFTI),
    }


def browse(dataset_id: str, folder_id: str = "") -> dict:
    """One level of a dataset: the folder's path from the root and its contents.

    Pennsieve pages long folders; the first page (up to 100 items) is plenty for
    the lab's per-subject layout, and the ID box covers anything beyond it.
    """
    _check_allowed(dataset_id)
    if folder_id:
        package = _get(f"/packages/{_quote(folder_id)}", {"includeAncestors": "true"})
        content = package.get("content", {})
        if content.get("datasetNodeId") != dataset_id:
            raise PennsieveError("That folder is not in the chosen dataset.")
        if content.get("packageType") != "Collection":
            raise PennsieveError("That ID is a file, not a folder.")
        path = [
            {"id": a["content"]["nodeId"], "name": a["content"]["name"]}
            for a in package.get("ancestors", [])
        ] + [{"id": folder_id, "name": content.get("name", "")}]
        children = package.get("children", [])
    else:
        path = []
        children = _get(f"/datasets/{_quote(dataset_id)}").get("children", [])

    items = sorted((_item(c) for c in children), key=lambda i: (not i["folder"], i["name"].lower()))
    return {"dataset": dataset_id, "path": path, "items": items}


def folder_path(dataset_id: str, folder_id: str) -> str:
    """`N:collection:…` -> `derivatives/voxtool_ct`, checked to be in the dataset.

    Uploads still go by path, because the CLI's --target_path takes nothing
    else; Pennsieve matches each part to an existing folder by name.
    """
    return "/".join(p["name"] for p in browse(dataset_id, folder_id)["path"])


def downloads_dir() -> str:
    path = os.path.join(local_mode.app_data_dir(), "pennsieve-downloads")
    os.makedirs(path, exist_ok=True)
    return path


def download_scan(package_id: str) -> dict:
    """Fetch a NIfTI scan by its Pennsieve ID into the app data folder.

    A file already downloaded at the same size is reused rather than fetched
    again. Returns where it landed and where it came from.
    """
    package = _get(f"/packages/{_quote(package_id)}", {"includeAncestors": "true"})
    content = package.get("content", {})
    dataset_id = content.get("datasetNodeId", "")
    _check_allowed(dataset_id)
    if content.get("packageType") == "Collection":
        raise PennsieveError("That ID is a folder. Open the folder and pick the scan inside it.")

    sources = _get(f"/packages/{_quote(package_id)}/sources-paged").get("results", [])
    if len(sources) != 1:
        raise PennsieveError(f"Expected one file in that package, found {len(sources)}.")
    source = sources[0].get("content", {})
    filename = os.path.basename(source.get("filename") or content.get("name") or "")
    if not filename.lower().endswith(_NIFTI):
        raise PennsieveError(f"{filename or 'That file'} is not a NIfTI scan (.nii or .nii.gz).")
    size = source.get("size")

    # One folder per package, so two scans with the same filename never collide.
    target_dir = os.path.join(downloads_dir(), re.sub(r"[^A-Za-z0-9_-]", "_", package_id))
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, filename)
    origin = "/".join([a["content"]["name"] for a in package.get("ancestors", [])] + [filename])

    if not (os.path.isfile(path) and os.path.getsize(path) == size):
        url = _get(
            f"/packages/{_quote(package_id)}/files/{source.get('id')}",
            {"short": "false"},
        ).get("url")
        if not url:
            raise PennsieveError("Pennsieve did not provide a download link for that file.")
        partial = path + ".part"
        try:
            with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as out:
                while chunk := response.read(1 << 20):
                    out.write(chunk)
        except (urllib.error.URLError, OSError) as e:
            raise PennsieveError(f"The download did not finish: {e}") from e
        if size is not None and os.path.getsize(partial) != size:
            os.remove(partial)
            raise PennsieveError("The download was incomplete. Try again.")
        os.replace(partial, path)

    return {"path": path, "package_id": package_id, "dataset": dataset_id, "origin": origin}
