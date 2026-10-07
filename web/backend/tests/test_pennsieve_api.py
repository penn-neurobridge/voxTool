"""Pennsieve browsing and downloads, against canned REST responses shaped like
the real API's (recorded from the VoxTool Test sandbox). Nothing here talks to
Pennsieve or the agent.

Run from web/backend:  python -m pytest tests/ -q
"""
from __future__ import annotations

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_mode  # noqa: E402
import pennsieve_api  # noqa: E402
from pennsieve_sync import PennsieveError  # noqa: E402

DATASET = "N:dataset:test"
OTHER = "N:dataset:real"
CT = "N:package:ct"
CT_BYTES = b"\x1f\x8b fake nifti bytes"


def node(name, node_id, kind, dataset=DATASET, storage=None):
    return {"content": {"name": name, "nodeId": node_id, "packageType": kind,
                        "datasetNodeId": dataset}, "storage": storage}


API = {
    f"/datasets/{DATASET}": {"children": [
        node("primary", "N:collection:primary", "Collection"),
        node("README.txt", "N:package:readme", "Text", storage=12),
        node("derivatives", "N:collection:derivatives", "Collection"),
    ]},
    "/packages/N:collection:ct": {
        "content": node("ct", "N:collection:ct", "Collection")["content"],
        "ancestors": [node("primary", "N:collection:primary", "Collection"),
                      node("sub-03", "N:collection:sub03", "Collection")],
        "children": [node("sub-03_ses-postimplant_ct.nii.gz", CT, "MRI", storage=len(CT_BYTES)),
                     node("sub-03_ses-postimplant_ct.json", "N:package:sidecar", "Unknown")],
    },
    f"/packages/{CT}": {
        "content": node("sub-03_ses-postimplant_ct.nii.gz", CT, "MRI")["content"],
        "ancestors": [node("primary", "x", "Collection"), node("sub-03", "y", "Collection"),
                      node("ses-postimplant", "z", "Collection"), node("ct", "w", "Collection")],
    },
    f"/packages/{CT}/sources-paged": {"results": [{"content": {
        "id": 1381856, "filename": "sub-03_ses-postimplant_ct.nii.gz", "size": len(CT_BYTES)}}]},
    f"/packages/{CT}/files/1381856": {"url": "https://s3.example/presigned"},
    "/packages/N:package:sidecar": {"content": node("x.json", "N:package:sidecar", "Unknown")["content"]},
    "/packages/N:package:sidecar/sources-paged": {"results": [{"content": {
        "id": 7, "filename": "sub-03_ses-postimplant_ct.json", "size": 3}}]},
    "/packages/N:package:elsewhere": {"content": node("ct.nii.gz", "N:package:elsewhere", "MRI", dataset=OTHER)["content"]},
}


@pytest.fixture
def api(tmp_path, monkeypatch):
    calls = []

    def fake_get(path, params=None, retry=True):
        calls.append(path)
        if path not in API:
            raise PennsieveError("Pennsieve has nothing with that ID, or this account cannot see it.")
        return API[path]

    downloads = []

    def fake_urlopen(url, timeout=None, context=None):
        # Every HTTPS call must carry the bundled CA certificates.
        assert context is pennsieve_api.https_context()
        downloads.append(url)
        return io.BytesIO(fake_urlopen.body)

    fake_urlopen.body = CT_BYTES
    monkeypatch.setattr(pennsieve_api, "_get", fake_get)
    monkeypatch.setattr(pennsieve_api.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("VOXTOOL_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(local_mode, "_resolved_data_dir", None)
    monkeypatch.delenv("VOXTOOL_PENNSIEVE_DATASETS", raising=False)
    return type("Api", (), {"calls": calls, "downloads": downloads, "urlopen": fake_urlopen,
                            "monkeypatch": monkeypatch})


class TestBrowse:
    def test_root_lists_folders_first(self, api):
        listing = pennsieve_api.browse(DATASET)
        assert [i["name"] for i in listing["items"]] == ["derivatives", "primary", "README.txt"]
        assert listing["path"] == []

    def test_folder_gives_its_path_and_marks_scans(self, api):
        listing = pennsieve_api.browse(DATASET, "N:collection:ct")
        assert [p["name"] for p in listing["path"]] == ["primary", "sub-03", "ct"]
        scans = {i["name"]: i["scan"] for i in listing["items"]}
        assert scans == {"sub-03_ses-postimplant_ct.nii.gz": True,
                         "sub-03_ses-postimplant_ct.json": False}

    def test_folder_from_another_dataset_is_refused(self, api):
        with pytest.raises(PennsieveError, match="not in the chosen dataset"):
            pennsieve_api.browse(OTHER, "N:collection:ct")

    def test_folder_id_resolves_to_its_path(self, api):
        assert pennsieve_api.folder_path(DATASET, "N:collection:ct") == "primary/sub-03/ct"

    def test_allow_list_blocks_other_datasets(self, api):
        api.monkeypatch.setenv("VOXTOOL_PENNSIEVE_DATASETS", DATASET)
        with pytest.raises(PennsieveError, match="outside the datasets"):
            pennsieve_api.browse(OTHER)
        assert api.calls == []


class TestDownload:
    def test_downloads_into_app_data_and_reports_origin(self, api):
        result = pennsieve_api.download_scan(CT)
        with open(result["path"], "rb") as f:
            assert f.read() == CT_BYTES
        assert result["path"].startswith(pennsieve_api.downloads_dir())
        assert result["origin"] == "primary/sub-03/ses-postimplant/ct/sub-03_ses-postimplant_ct.nii.gz"

    def test_second_open_reuses_the_file(self, api):
        pennsieve_api.download_scan(CT)
        pennsieve_api.download_scan(CT)
        assert len(api.downloads) == 1

    def test_short_download_leaves_nothing_behind(self, api):
        api.urlopen.body = CT_BYTES[:5]
        with pytest.raises(PennsieveError, match="incomplete"):
            pennsieve_api.download_scan(CT)
        target = os.path.join(pennsieve_api.downloads_dir(), "N_package_ct")
        assert os.listdir(target) == []

    def test_non_nifti_is_refused_before_downloading(self, api):
        with pytest.raises(PennsieveError, match="not a NIfTI"):
            pennsieve_api.download_scan("N:package:sidecar")
        assert api.downloads == []

    def test_folder_id_is_refused(self, api):
        API["/packages/N:collection:ct"]["content"]["datasetNodeId"] = DATASET
        with pytest.raises(PennsieveError, match="is a folder"):
            pennsieve_api.download_scan("N:collection:ct")

    def test_allow_list_applies_to_downloads(self, api):
        api.monkeypatch.setenv("VOXTOOL_PENNSIEVE_DATASETS", DATASET)
        with pytest.raises(PennsieveError, match="outside the datasets"):
            pennsieve_api.download_scan("N:package:elsewhere")
        assert api.downloads == []


def test_config_with_keys_above_the_first_section_is_read_safely(tmp_path, monkeypatch):
    # The CLI writes the default profile like this; configparser rejects it and
    # quotes the secret line in its error.
    (tmp_path / ".pennsieve").mkdir()
    (tmp_path / ".pennsieve" / "config.ini").write_text(
        "api_secret=SECRET-VALUE\napi_token=TOKEN-VALUE\n\n[agent]\nport=9123\n\n[global]\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert pennsieve_api._agent_address() == "127.0.0.1:9123"


def test_unexpected_errors_never_repeat_their_message(api, monkeypatch):
    monkeypatch.setenv("VOXTOOL_LOCAL", "1")

    def leak(*a, **k):
        raise ValueError("api_secret=SECRET-VALUE")

    monkeypatch.setattr(pennsieve_api, "browse", leak)
    from app import create_app

    r = create_app().test_client().get(f"/api/pennsieve/browse?dataset={DATASET}")
    assert r.status_code == 500
    assert "SECRET" not in r.get_data(as_text=True)


def test_agent_not_running_is_said_plainly(monkeypatch):
    # Port 1 refuses connections, so this is a real gRPC call failing fast.
    monkeypatch.setattr(pennsieve_api, "_agent_address", lambda: "127.0.0.1:1")
    monkeypatch.setattr(pennsieve_api, "_session", None)
    with pytest.raises(PennsieveError, match="not running"):
        pennsieve_api.session()


class TestRoutes:
    @pytest.fixture
    def client(self, api):
        api.monkeypatch.setenv("VOXTOOL_LOCAL", "1")
        from app import create_app

        return create_app().test_client()

    def test_open_wants_a_package_id(self, client):
        r = client.post("/api/pennsieve/open", json={"package_id": "N:collection:ct"})
        assert r.status_code == 400

    def test_open_returns_the_local_path(self, client):
        r = client.post("/api/pennsieve/open", json={"package_id": CT})
        assert r.status_code == 200
        assert os.path.isfile(r.get_json()["path"])

    def test_browse_and_open_refused_outside_the_desktop_app(self, client, api):
        api.monkeypatch.delenv("VOXTOOL_LOCAL")
        assert client.get(f"/api/pennsieve/browse?dataset={DATASET}").status_code == 403
        assert client.post("/api/pennsieve/open", json={"package_id": CT}).status_code == 403


def test_https_uses_certificates_packaged_with_the_app():
    import certifi

    context = pennsieve_api.https_context()
    assert context.cert_store_stats()["x509_ca"] > 0
    assert os.path.isfile(certifi.where())
