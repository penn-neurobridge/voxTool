"""Pennsieve upload tests, against a fake `pennsieve` CLI. Nothing here talks to
Pennsieve: the fake keeps its state in a JSON file and logs every call.

The fake copies the real CLI's habits that matter: every command exits 0, a
refused `dataset use` just prints "Unknown Dataset", and a failed index still
returns a manifest id.

Run from web/backend:  python -m pytest tests/ -q
"""
from __future__ import annotations

import json
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_mode  # noqa: E402
import pennsieve_sync  # noqa: E402

SANDBOX = "N:dataset:test"
REAL = "N:dataset:real"

FAKE_CLI = r'''#!{python}
import json, os, sys, time

state_path = os.environ["STUB_STATE"]
scenario = os.environ.get("STUB_SCENARIO", "ok")
state = json.load(open(state_path))
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps({{"args": args, "active": state["active"]}}) + "\n")
known = {{"N:dataset:test": "VoxTool Test", "N:dataset:real": "PennEPI00049",
         "N:dataset:homework": "Homework Data"}}

def save():
    json.dump(state, open(state_path, "w"))

def table(rows):
    print("Initializing DB...")
    print("+------+")
    for row in rows:
        print("| " + " | ".join(str(c) for c in row) + " |")
    print("+------+")

if args == ["whoami"]:
    table([["NAME", "Test User"], ["ORGANIZATION", "Penn CNT"],
           ["ORGANIZATION ID", "N:organization:x"]])
elif args == ["dataset", "list"]:
    table([["Datasets"], ["NAME", "NODE ID", "INTEGER ID"],
           ["VoxTool Test", "N:dataset:test", 537],
           ["PennEPI00049", "N:dataset:real", 289]])
elif args == ["dataset"]:
    table([["Active dataset"], ["NAME", known[state["active"]]],
           ["NODE ID", state["active"]]])
elif args[:2] == ["dataset", "use"]:
    if args[2] in known and scenario != "use_refused":
        state["active"] = args[2]
        save()
        table([["NAME", known[args[2]]], ["NODE ID", args[2]]])
    else:
        print("Unknown Dataset: " + args[2])
elif args[:2] == ["manifest", "create"]:
    if scenario == "index_fail":
        print("Manifest ID: 9 Message: Creating manifest failed.")
    else:
        mid = str(7 + len(state["manifests"]))
        target = args[args.index("--target_path") + 1] if "--target_path" in args else ""
        state["manifests"][mid] = {{"dataset": state["active"], "target": target,
                                    "path": args[-1], "status": "REGISTERED"}}
        save()
        print("Manifest ID: " + mid + " Message: Successfully indexed 1 files.")
elif args[:2] == ["upload", "manifest"]:
    m = state["manifests"][args[2]]
    m["status"] = {{"stuck": "REGISTERED", "failed": "FAILED"}}.get(scenario, "UPLOADED")
    save()
    print("Upload initiated for manifest: " + args[2])
elif args[:2] == ["manifest", "list"]:
    m = state["manifests"][args[2]]
    table([["Files for upload manifest: " + args[2]], ["ID", "SOURCE PATH", "STATUS"],
           [1, m["path"], m["status"]]])
elif args[:2] == ["manifest", "sync"]:
    m = state["manifests"][args[2]]
    if m["status"] == "UPLOADED" and scenario != "slow_import":
        m["status"] = "VERIFIED"
    save()
    print("Synchronizing manifest.")
'''


class Fake:
    def __init__(self, tmp_path, monkeypatch):
        self.state_path = tmp_path / "state.json"
        self.log_path = tmp_path / "calls.log"
        # The agent starts out pointed at a dataset nobody chose for this.
        self.state_path.write_text(json.dumps({"active": "N:dataset:homework", "manifests": {}}))
        self.log_path.write_text("")
        cli = tmp_path / "pennsieve"
        cli.write_text(FAKE_CLI.format(python=sys.executable))
        cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setattr(pennsieve_sync, "CLI", str(cli))
        monkeypatch.setenv("STUB_STATE", str(self.state_path))
        monkeypatch.setenv("STUB_LOG", str(self.log_path))
        monkeypatch.setenv("VOXTOOL_DATA_DIR", str(tmp_path / "appdata"))
        monkeypatch.delenv("VOXTOOL_PENNSIEVE_DATASETS", raising=False)
        monkeypatch.setattr(local_mode, "_resolved_data_dir", None)
        self.monkeypatch = monkeypatch
        self.file = tmp_path / "sub-03_voxel_coordinates.json"
        self.file.write_text("{}")

    def scenario(self, name):
        self.monkeypatch.setenv("STUB_SCENARIO", name)

    def calls(self):
        return [json.loads(line)["args"] for line in self.log_path.read_text().splitlines()]

    def manifests(self):
        return json.loads(self.state_path.read_text())["manifests"]

    def upload(self, dataset=SANDBOX, **kw):
        return pennsieve_sync.upload(str(self.file), dataset_id=dataset,
                                     target_path="derivatives/voxtool_ct",
                                     dry_run=False, **kw)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    return Fake(tmp_path, monkeypatch)


def created_manifest(fake):
    return any(c[:2] == ["manifest", "create"] for c in fake.calls())


class TestUpload:
    def test_lands_in_the_chosen_dataset_and_folder(self, fake):
        result = fake.upload()
        assert result["state"] == "imported"
        (manifest,) = fake.manifests().values()
        assert manifest["dataset"] == SANDBOX
        assert manifest["target"] == "derivatives/voxtool_ct"

    def test_ignored_dataset_switch_sends_nothing(self, fake):
        # The real CLI exits 0 here and leaves the old dataset active, so a
        # manifest created next would go into that one.
        fake.scenario("use_refused")
        with pytest.raises(pennsieve_sync.PennsieveError, match="did not switch"):
            fake.upload()
        assert not created_manifest(fake)

    def test_unknown_dataset_sends_nothing(self, fake):
        with pytest.raises(pennsieve_sync.PennsieveError, match="Unknown Dataset"):
            fake.upload(dataset="N:dataset:not-in-this-workspace")
        assert not created_manifest(fake)

    def test_failed_index_is_an_error(self, fake):
        fake.scenario("index_fail")
        with pytest.raises(pennsieve_sync.PennsieveError, match="Creating manifest failed"):
            fake.upload()
        assert not any(c[:2] == ["upload", "manifest"] for c in fake.calls())

    def test_failed_transfer_is_an_error(self, fake):
        fake.scenario("failed")
        with pytest.raises(pennsieve_sync.PennsieveError, match="failed"):
            fake.upload()

    def test_transfer_still_running_is_pending_not_success(self, fake):
        fake.scenario("stuck")
        result = fake.upload(wait=1)
        assert result["state"] == "pending"
        assert result["uploaded"] is False

    def test_transferred_but_not_imported_says_so(self, fake):
        fake.scenario("slow_import")
        assert fake.upload(wait=1)["state"] == "sent"

    def test_dry_run_calls_nothing(self, fake):
        pennsieve_sync.upload(str(fake.file), dataset_id=SANDBOX)
        assert fake.calls() == []


class TestAllowList:
    def test_blocks_other_datasets_before_touching_the_cli(self, fake):
        fake.monkeypatch.setenv("VOXTOOL_PENNSIEVE_DATASETS", SANDBOX)
        for dry_run in (True, False):
            with pytest.raises(pennsieve_sync.PennsieveError, match="only to"):
                pennsieve_sync.upload(str(fake.file), dataset_id=REAL, dry_run=dry_run)
        assert fake.calls() == []

    def test_allows_the_sandbox(self, fake):
        fake.monkeypatch.setenv("VOXTOOL_PENNSIEVE_DATASETS", SANDBOX)
        assert fake.upload()["state"] == "imported"

    def test_status_lists_only_allowed_datasets(self, fake):
        fake.monkeypatch.setenv("VOXTOOL_PENNSIEVE_DATASETS", SANDBOX)
        st = pennsieve_sync.status()
        assert [d["id"] for d in st.datasets] == [SANDBOX]
        assert st.restricted

    def test_status_without_a_list_shows_everything(self, fake):
        st = pennsieve_sync.status()
        assert {d["id"] for d in st.datasets} == {SANDBOX, REAL}
        assert not st.restricted


class TestRoute:
    @pytest.fixture
    def client(self, fake):
        fake.monkeypatch.setenv("VOXTOOL_LOCAL", "1")
        from app import create_app

        return create_app().test_client()

    DOC = {"leads": {"LA": {"contacts": []}}}

    def outbox_files(self):
        return [f for _, _, files in os.walk(pennsieve_sync.outbox_dir()) for f in files]

    def test_defaults_to_a_dry_run(self, client, fake):
        r = client.post("/api/pennsieve/upload", json={
            "document": self.DOC, "dataset_id": SANDBOX, "scan_filename": "sub-03_ct.nii.gz"})
        assert r.status_code == 200
        assert r.get_json()["dry_run"] is True
        assert fake.calls() == []

    def test_finished_upload_cleans_up(self, client, fake):
        r = client.post("/api/pennsieve/upload", json={
            "document": self.DOC, "dataset_id": SANDBOX, "dry_run": False,
            "target_path": "derivatives/voxtool_ct", "scan_filename": "sub-03_ct.nii.gz"})
        body = r.get_json()
        assert body["state"] == "imported"
        assert body["filename"].startswith("sub-03_voxel_coordinates_")
        assert self.outbox_files() == []

    def test_pending_upload_keeps_its_file(self, client, fake):
        # The agent reads the file after the request returns.
        fake.scenario("stuck")
        fake.monkeypatch.setattr(pennsieve_sync, "UPLOAD_WAIT", 1)
        r = client.post("/api/pennsieve/upload", json={
            "document": self.DOC, "dataset_id": SANDBOX, "dry_run": False})
        assert r.get_json()["state"] == "pending"
        assert len(self.outbox_files()) == 1

    def test_refused_outside_the_desktop_app(self, client, fake):
        fake.monkeypatch.delenv("VOXTOOL_LOCAL")
        assert client.get("/api/pennsieve/status").status_code == 403
        assert client.post("/api/pennsieve/upload", json={}).status_code == 403
