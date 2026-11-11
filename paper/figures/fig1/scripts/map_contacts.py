"""Put the sample subject's published contact positions onto its CT, as VoxTool voxels.

MNE ships the sample_seeg contacts in head coordinates and the CT in scanner
space. Following MNE's sEEG tutorial, register the CT to the T1, then carry
each contact head -> MRI -> T1 scanner RAS -> CT voxel. Writes a legacy
voxel_coordinates.json that VoxTool's "Load coordinates" opens.

    conda run -n voxfig python paper/figures/fig1/scripts/map_contacts.py
"""
import json
import re
from pathlib import Path

import mne
import nibabel as nib
import numpy as np

MISC = Path.home() / "mne_data" / "dl" / "mne-misc-data-0.30" / "seeg"
FIG = Path(__file__).resolve().parents[1]
OUT = FIG / "assets" / "sample_seeg_voxel_coordinates.json"
REG = FIG / "assets" / "raw" / "ct_to_t1_reg_affine.npy"


def main():
    t1 = nib.load(MISC / "sample_seeg" / "mri" / "T1.mgz")
    ct = nib.load(MISC / "sample_seeg_CT.mgz")

    if REG.exists():
        reg_affine = np.load(REG)
    else:
        # Same call as MNE's tutorial; the rigid pipeline takes a few minutes.
        reg_affine, _ = mne.transforms.compute_volume_registration(
            ct, t1, pipeline="rigids", verbose=True)
        np.save(REG, reg_affine)

    raw = mne.io.read_raw_fif(MISC / "sample_seeg_ieeg.fif", verbose="error")
    trans = mne.coreg.estimate_head_mri_t("sample_seeg", MISC)
    montage = raw.get_montage()
    montage.apply_trans(trans)  # head -> MRI surface RAS, metres

    tkr_to_scanner = t1.affine @ np.linalg.inv(t1.header.get_vox2ras_tkr())
    # reg_affine maps static (T1) world coordinates to moving (CT) world coordinates.
    scanner_to_ct_vox = np.linalg.inv(ct.affine) @ reg_affine
    data = np.asarray(ct.dataobj)

    leads, hu = {}, []
    for name, xyz in montage.get_positions()["ch_pos"].items():
        if xyz is None or np.isnan(xyz).any():
            continue
        p = tkr_to_scanner @ np.r_[np.asarray(xyz) * 1000.0, 1.0]
        v = (scanner_to_ct_vox @ p)[:3]
        ijk = [int(round(x)) for x in v]
        i, j, k = ijk
        hu.append(data[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2, max(k - 1, 0):k + 2].max())
        lead = re.match(r"[A-Za-z']+", name).group(0)
        leads.setdefault(lead, []).append({
            "name": name.replace(" ", ""),  # VoxTool names contacts like LENT1
            "lead_group": 0,
            "coordinate_spaces": {"ct_voxel": {"raw": ijk}},
        })

    doc = {"leads": {k: {"type": "D", "dimensions": [1, len(v)], "contacts": v}
                     for k, v in leads.items()}}
    OUT.write_text(json.dumps(doc, indent=1))
    hu = np.array(hu)
    # Check: every contact should sit on metal, far brighter than bone (~1000-2000 HU).
    print(f"{sum(len(v) for v in leads.values())} contacts, {len(leads)} leads -> {OUT.name}")
    print(f"max HU near each contact: median {np.median(hu):.0f}, min {hu.min():.0f}, "
          f"share > 2500: {(hu > 2500).mean():.0%}")


if __name__ == "__main__":
    main()
