"""Electrode View must never show a scan mirror-image.

The cloud is drawn in scaled voxel space, so a scan stored mirror-image to RAS
(negative-determinant affine, e.g. LAS) came out as a mirror image of the head:
an IISc user saw right-hemisphere electrodes "on the left" with R and L looking
swapped. The server now sends ``flip_x`` and the viewer negates x for both the
points and the R/A/S labels. These tests check that the scene the viewer builds
from the server's answers is right-handed for either kind of scan.
"""
from __future__ import annotations

import json
import os
import sys

import nibabel as nib
import numpy as np
import pytest
from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes.scans import _cloud_cache_path, _DATAOBJ_CACHE, scans_bp  # noqa: E402

RAS = np.diag([0.5, 0.5, 1.0, 1.0])
# How the lab's example CTs are stored: x runs right-to-left.
LAS = np.diag([-0.5, 0.5, 1.0, 1.0])
# Same, with a gantry-style tilt, so the labels are not axis-aligned.
_tilt = np.radians(12)
LAS_TILTED = np.array(
    [
        [-0.5, 0.0, 0.0, 0.0],
        [0.0, 0.5 * np.cos(_tilt), -np.sin(_tilt), 0.0],
        [0.0, 0.5 * np.sin(_tilt), np.cos(_tilt), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VOXTOOL_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.delenv("VOXTOOL_LOCAL", raising=False)
    _DATAOBJ_CACHE.clear()
    app = Flask(__name__)
    app.config["DATA_DIR"] = str(tmp_path)
    app.config["BUNDLED_CLOUD_DIR"] = ""
    app.register_blueprint(scans_bp, url_prefix="/api/scans")
    with app.test_client() as c:
        c.data_dir = tmp_path
        yield c
    _DATAOBJ_CACHE.clear()


def _write_scan(dirpath, name, affine):
    data = np.zeros((12, 12, 12), dtype=np.int16)
    # One bright "electrode" off to the left of the voxel grid's first axis.
    data[2:4, 6, 6] = 3000
    img = nib.Nifti1Image(data, affine)
    img.set_qform(affine, code=1)
    img.set_sform(affine, code=1)
    nib.save(img, str(dirpath / name))
    return name


def _scene(client, name):
    """The label directions and flip the viewer would use for this scan."""
    o = client.get(f"/api/scans/{name}/orientation").get_json()
    cloud = client.post(
        f"/api/scans/{name}/threshold_cloud",
        json={"threshold_pct": 99.0, "excluded_voxels": [[0, 0, 0]]},
    ).get_json()
    assert o["flip_x"] == cloud["flip_x"]
    sign = -1.0 if cloud["flip_x"] else 1.0
    flip = lambda d: np.array([sign * d[0], d[1], d[2]])  # noqa: E731
    return {k: flip(o[k]) for k in ("R", "L", "A", "P", "S", "I")}, cloud


def _handedness(dirs):
    return float(np.dot(np.cross(dirs["R"], dirs["A"]), dirs["S"]))


@pytest.mark.parametrize(
    "affine, expect_flip",
    [(RAS, False), (LAS, True), (LAS_TILTED, True)],
    ids=["RAS", "LAS", "LAS-tilted"],
)
def test_scene_is_right_handed(client, affine, expect_flip):
    name = _write_scan(client.data_dir, "ct.nii.gz", affine)
    dirs, cloud = _scene(client, name)
    assert cloud["flip_x"] is expect_flip
    assert _handedness(dirs) > 0.99


def test_old_scenes_were_mirrored_for_las(client):
    """Without the flip, an LAS scan's R × A points away from S."""
    name = _write_scan(client.data_dir, "ct.nii.gz", LAS)
    o = client.get(f"/api/scans/{name}/orientation").get_json()
    raw = {k: np.array(o[k]) for k in ("R", "A", "S")}
    assert _handedness(raw) < -0.99


def test_bright_voxels_sit_on_the_labelled_side(client):
    """Points drawn with the flip land on the side of the label they belong to."""
    name = _write_scan(client.data_dir, "ct.nii.gz", LAS)
    dirs, cloud = _scene(client, name)
    sign = -1.0 if cloud["flip_x"] else 1.0
    sx, sy, sz = cloud["voxel_spacing_mm"]
    centre = np.array([sign * 5.5 * sx, 5.5 * sy, 5.5 * sz])
    for i, j, k in cloud["points"]:
        ras_x = (LAS @ np.array([i, j, k, 1.0]))[0] - (LAS @ np.array([5.5, 5.5, 5.5, 1.0]))[0]
        scene = np.array([sign * i * sx, j * sy, k * sz]) - centre
        # Patient-right of centre (ras_x > 0) must point toward the R label.
        assert np.sign(np.dot(scene, dirs["R"])) == np.sign(ras_x)


def test_flip_is_added_to_clouds_cached_before_it_existed(client):
    name = _write_scan(client.data_dir, "ct.nii.gz", LAS)
    path = str(client.data_dir / name)
    old_cache = {
        "success": True,
        "points": [[2, 6, 6], [3, 6, 6]],
        "intensity_threshold": 3000.0,
        "threshold_pct": 99.0,
        "total_voxels": 2,
        "returned": 2,
        "shape": [12, 12, 12],
        "voxel_spacing_mm": [0.5, 0.5, 1.0],
    }
    with open(_cloud_cache_path(path, 99.0), "w", encoding="utf-8") as f:
        json.dump(old_cache, f)
    cloud = client.post(
        f"/api/scans/{name}/threshold_cloud", json={"threshold_pct": 99.0}
    ).get_json()
    assert cloud["points"] == old_cache["points"]
    assert cloud["flip_x"] is True
