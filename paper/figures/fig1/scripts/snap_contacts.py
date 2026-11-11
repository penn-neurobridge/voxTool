"""Snap each mapped contact with VoxTool's own /snap endpoint, as a click would.

Needs VoxTool running locally with the sample CT opened. Rewrites
assets/sample_seeg_voxel_coordinates.json in place and reports how many moved.

    conda run -n voxfig python paper/figures/fig1/scripts/snap_contacts.py
"""
import json
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:5001/api/scans/mne_sample_seeg_CT.nii.gz"
PATH = Path(__file__).resolve().parents[1] / "assets" / "sample_seeg_voxel_coordinates.json"


def post(route, body):
    req = urllib.request.Request(f"{API}/{route}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    doc = json.loads(PATH.read_text())
    moved, missed = 0, 0
    for lead in doc["leads"].values():
        for c in lead["contacts"]:
            vox = c["coordinate_spaces"]["ct_voxel"]["raw"]
            mm = post("voxel_to_mm", {"voxel": vox})
            mm = mm.get("point_mm") or mm.get("mm")
            snap = post("snap", {"point_mm": mm})
            if not snap.get("success"):
                missed += 1
                continue
            new = post("mm_to_voxel", {"point_mm": snap["center_mm"]})["voxel"]
            new = [int(round(x)) for x in new]
            moved += new != vox
            c["coordinate_spaces"]["ct_voxel"]["raw"] = new
    PATH.write_text(json.dumps(doc, indent=1))
    print(f"snapped; {moved} contacts moved, {missed} had no bright voxels nearby")


if __name__ == "__main__":
    main()
