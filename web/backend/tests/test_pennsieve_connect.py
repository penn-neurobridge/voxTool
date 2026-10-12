"""Connecting to Pennsieve from VoxTool. Nothing here talks to Pennsieve, AWS or
the agent: HTTP and the CLI are faked, and HOME points at a temp folder so the
real ~/.pennsieve/config.ini is never read or written.

Most of these check one thing: the API key and secret, which never expire,
end up in the CLI's config and nowhere else.

Run from web/backend:  python -m pytest tests/ -q
"""
from __future__ import annotations

import base64
import json
import os
import stat
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_mode  # noqa: E402
import pennsieve_api  # noqa: E402
import pennsieve_connect  # noqa: E402
import pennsieve_sync  # noqa: E402
from pennsieve_sync import PennsieveError  # noqa: E402

KEY = "11111111-2222-3333-4444-555555555555"
SECRET = "99999999-8888-7777-6666-aaaaaaaaaaaa"
WORKSPACE = "N:organization:cnt"

EXISTING_CONFIG = """api_secret=old-secret
api_token=old-token

[agent]
port=9000

[global]
default_profile=default

[penn-cnt]
api_token=another-token
api_secret=another-secret
"""


def id_token(claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("VOXTOOL_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(local_mode, "_resolved_data_dir", None)
    monkeypatch.delenv("VOXTOOL_PENNSIEVE_DATASETS", raising=False)
    (tmp_path / ".pennsieve").mkdir()
    config = tmp_path / ".pennsieve" / "config.ini"
    config.write_text(EXISTING_CONFIG)
    return config


@pytest.fixture
def pennsieve(home, monkeypatch):
    """Fake Pennsieve sign-in plus a fake CLI that tracks the active profile."""
    state = {"accept": True, "active": "default", "known": None, "hang": False, "calls": []}

    def fake_http(url, body=None, headers=None):
        state["calls"].append(url)
        if url.endswith("/authentication/cognito-config"):
            return {"tokenPool": {"region": "us-east-1", "appClientId": "client"}}
        if "cognito-idp" in url:
            if not state["accept"]:
                raise urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
            return {"AuthenticationResult": {
                "AccessToken": "access",
                "IdToken": id_token({"custom:organization_node_id": WORKSPACE}),
            }}
        if "/organizations/" in url:
            return {"organization": {"name": "Penn CNT"}}
        if url.endswith("/user/"):
            return {"firstName": "Binoy", "lastName": "Patel"}
        raise AssertionError(url)

    def fake_run(args, timeout=60):
        state["calls"].append(args)
        known = state["known"] if state["known"] is not None else pennsieve_connect.profiles()
        if args == ["profile", "show"]:
            return 0, f"Current profile:  {state['active']}"
        if args[:2] == ["profile", "switch"]:
            if state["hang"]:
                raise pennsieve_sync.PennsieveTimeout("timed out")
            if args[2] not in known:
                return 0, f"Error: Profile not found: {args[2]}"
            state["active"] = args[2]
        if args == ["whoami"]:
            org = WORKSPACE if state["active"] != "default" else "N:organization:be5210"
            return 0, f"| NAME | Binoy Patel |\n| ORGANIZATION | x |\n| ORGANIZATION ID | {org} |"
        return 0, ""

    def fake_start_agent(wait=15):
        state["calls"].append(["agent", "start"])
        state["known"] = None  # a fresh agent reads the config again
        state["hang"] = False  # and has no stuck goroutines
        return True

    monkeypatch.setattr(pennsieve_connect, "_http_json", fake_http)
    monkeypatch.setattr(pennsieve_sync, "_run", fake_run)
    monkeypatch.setattr(pennsieve_sync, "start_agent", fake_start_agent)
    return state


def test_profiles_lists_names_only(home):
    assert pennsieve_connect.profiles() == ["default", "penn-cnt"]


class TestVerify:
    def test_reports_the_keys_workspace_and_owner(self, pennsieve):
        assert pennsieve_connect.verify(KEY, SECRET) == {
            "workspace": "Penn CNT", "workspace_id": WORKSPACE, "user": "Binoy Patel"}

    def test_malformed_input_never_leaves_the_machine(self, pennsieve):
        with pytest.raises(PennsieveError, match="doesn't look like"):
            pennsieve_connect.verify("not-a-key", SECRET)
        assert pennsieve["calls"] == []

    def test_rejected_key_says_so_without_repeating_it(self, pennsieve):
        pennsieve["accept"] = False
        with pytest.raises(PennsieveError) as caught:
            pennsieve_connect.verify(KEY, SECRET)
        assert "did not accept" in str(caught.value)
        assert KEY not in str(caught.value) and SECRET not in str(caught.value)
        assert caught.value.__cause__ is None and caught.value.__suppress_context__


class TestConnect:
    def test_new_key_becomes_a_private_profile_and_the_active_one(self, pennsieve, home):
        result = pennsieve_connect.connect(KEY, SECRET)
        # penn-cnt is taken by another key, so the new profile gets a suffix.
        assert result["profile"] == "penn-cnt-2" and result["new"] is True
        assert result["workspace_id"] == WORKSPACE
        text = home.read_text()
        assert text.startswith(EXISTING_CONFIG)
        assert f"[penn-cnt-2]\napi_token={KEY}\napi_secret={SECRET}\n" in text
        assert stat.S_IMODE(os.stat(home).st_mode) == 0o600
        assert ["agent", "stop"] in pennsieve["calls"]
        assert ["profile", "set-default", "penn-cnt-2"] in pennsieve["calls"]

    def test_a_key_saved_already_is_reused_not_written_twice(self, pennsieve, home):
        home.write_text(EXISTING_CONFIG.replace("another-token", KEY))
        result = pennsieve_connect.connect(KEY, SECRET)
        assert result["profile"] == "penn-cnt" and result["new"] is False
        assert home.read_text().count(KEY) == 1

    def test_rejected_key_writes_nothing(self, pennsieve, home):
        pennsieve["accept"] = False
        with pytest.raises(PennsieveError):
            pennsieve_connect.connect(KEY, SECRET)
        assert home.read_text() == EXISTING_CONFIG

    def test_waits_for_running_uploads_unless_told(self, pennsieve, home):
        os.makedirs(os.path.join(pennsieve_sync.outbox_dir(), "still-sending"))
        with pytest.raises(pennsieve_connect.PennsieveBusy):
            pennsieve_connect.connect(KEY, SECRET)
        assert home.read_text() == EXISTING_CONFIG
        assert pennsieve_connect.connect(KEY, SECRET, force=True)["new"] is True

    def test_drops_the_previous_profiles_token(self, pennsieve):
        pennsieve_api._session = object()
        pennsieve_connect.connect(KEY, SECRET)
        assert pennsieve_api._session is None


class TestSwitch:
    def test_switches_to_a_saved_profile(self, pennsieve):
        result = pennsieve_connect.switch("penn-cnt")
        assert result["workspace_id"] == WORKSPACE
        assert ["agent", "stop"] not in pennsieve["calls"]

    def test_profile_saved_outside_voxtool_restarts_the_agent(self, pennsieve):
        pennsieve["known"] = ["default"]  # the agent started before penn-cnt existed
        pennsieve_connect.switch("penn-cnt")
        assert ["agent", "stop"] in pennsieve["calls"]
        assert pennsieve["active"] == "penn-cnt"

    def test_already_active_profile_is_not_switched_again(self, pennsieve):
        pennsieve["active"] = "penn-cnt"
        pennsieve["hang"] = True  # a real switch would hang
        assert pennsieve_connect.switch("penn-cnt")["workspace_id"] == WORKSPACE
        assert not any(c[:2] == ["profile", "switch"] for c in pennsieve["calls"] if isinstance(c, list))

    def test_hung_switch_restarts_the_agent_and_retries(self, pennsieve):
        pennsieve["hang"] = True  # agent 1.8.10 after an upload older than 15 minutes
        assert pennsieve_connect.switch("penn-cnt")["workspace_id"] == WORKSPACE
        assert ["agent", "stop"] in pennsieve["calls"]

    def test_hung_switch_waits_for_running_uploads(self, pennsieve):
        pennsieve["hang"] = True
        os.makedirs(os.path.join(pennsieve_sync.outbox_dir(), "still-sending"))
        with pytest.raises(pennsieve_connect.PennsieveBusy):
            pennsieve_connect.switch("penn-cnt")
        assert ["agent", "stop"] not in pennsieve["calls"]

    def test_unknown_profile_is_refused(self, pennsieve):
        with pytest.raises(PennsieveError, match="no saved Pennsieve profile"):
            pennsieve_connect.switch("nope")


class TestRemoveProfile:
    def test_removes_one_section_and_nothing_else(self, pennsieve, home):
        pennsieve["active"] = "default"
        assert pennsieve_connect.remove_profile("penn-cnt") == ["default"]
        text = home.read_text()
        assert "penn-cnt" not in text and "another-secret" not in text
        assert "[agent]\nport=9000" in text and text.startswith("api_secret=old-secret")
        assert stat.S_IMODE(os.stat(home).st_mode) == 0o600

    def test_removing_default_drops_only_its_keys_and_repoints_the_default(self, pennsieve, home):
        pennsieve["active"] = "penn-cnt"
        assert pennsieve_connect.remove_profile("default") == ["penn-cnt"]
        text = home.read_text()
        assert "old-secret" not in text and "old-token" not in text
        assert "default_profile=penn-cnt" in text
        assert "[penn-cnt]\napi_token=another-token" in text

    def test_refuses_the_profile_in_use(self, pennsieve, home):
        pennsieve["active"] = "penn-cnt"
        with pytest.raises(PennsieveError, match="in use"):
            pennsieve_connect.remove_profile("penn-cnt")
        assert home.read_text() == EXISTING_CONFIG


class TestRoutes:
    @pytest.fixture
    def client(self, home, monkeypatch):
        monkeypatch.setenv("VOXTOOL_LOCAL", "1")
        from app import create_app

        return create_app().test_client()

    def test_no_response_ever_contains_the_key(self, client, monkeypatch, pennsieve):
        bodies = []
        post = lambda: client.post("/api/pennsieve/connect", json={"api_key": KEY, "api_secret": SECRET})
        bodies.append(post().get_data(as_text=True))  # success
        pennsieve["accept"] = False
        bodies.append(post().get_data(as_text=True))  # rejected

        def leaky(*a, **k):
            raise ValueError(f"something went wrong with {KEY} / {SECRET}")

        monkeypatch.setattr(pennsieve_connect, "connect", leaky)
        bodies.append(post().get_data(as_text=True))  # unexpected
        for body in bodies:
            assert KEY not in body and SECRET not in body

    def test_settings_round_trip(self, client):
        r = client.post("/api/pennsieve/settings", json={"allowed_datasets": ["N:dataset:test"]})
        assert r.get_json()["allowed_datasets"] == ["N:dataset:test"]
        assert pennsieve_sync.allowed_datasets() == {"N:dataset:test"}
        client.post("/api/pennsieve/settings", json={"allowed_datasets": []})
        assert pennsieve_sync.allowed_datasets() == set()

    def test_settings_rejects_anything_but_dataset_ids(self, client):
        r = client.post("/api/pennsieve/settings", json={"allowed_datasets": ["rm -rf"]})
        assert r.status_code == 400

    def test_refused_outside_the_desktop_app(self, client, monkeypatch):
        monkeypatch.delenv("VOXTOOL_LOCAL")
        for path in ("/api/pennsieve/connect", "/api/pennsieve/switch", "/api/pennsieve/settings",
                     "/api/pennsieve/remove-profile"):
            assert client.post(path, json={}).status_code == 403
