"""Render a whole brain with every sEEG contact, from MNE's public sample_seeg subject.

    conda run -n voxfig python paper/figures/fig1/scripts/render_brain.py

Writes assets/renders/brain_electrodes_{view}.png (transparent background).
"""
import re
from pathlib import Path

import mne
import nibabel as nib
import numpy as np
import pyvista as pv

MISC = Path.home() / "mne_data" / "dl" / "mne-misc-data-0.30" / "seeg"
SUBJECTS_DIR = MISC
OUT = Path(__file__).resolve().parents[1] / "assets" / "renders"

# One colour per lead; picked to stay distinct on a light-grey cortex.
LEAD_COLOURS = ["#e4572e", "#29a19c", "#f3a712", "#6c4ab6", "#2e86de", "#c0392b",
                "#16a085", "#d35400", "#8e44ad", "#27ae60", "#e84393", "#0984e3"]


def contacts_mri_mm():
    raw = mne.io.read_raw_fif(MISC / "sample_seeg_ieeg.fif", verbose="error")
    trans = mne.coreg.estimate_head_mri_t("sample_seeg", SUBJECTS_DIR)
    montage = raw.get_montage()
    montage.apply_trans(trans)  # head -> MRI surface RAS (metres)
    pos = montage.get_positions()["ch_pos"]
    leads = {}
    for name, xyz in pos.items():
        if xyz is None or np.isnan(xyz).any():
            continue
        lead = re.match(r"[A-Za-z']+", name).group(0)
        leads.setdefault(lead, []).append(np.asarray(xyz) * 1000.0)
    return {k: np.array(v) for k, v in leads.items()}


def pial(hemi):
    v, f = nib.freesurfer.read_geometry(SUBJECTS_DIR / "sample_seeg" / "surf" / f"{hemi}.pial")
    faces = np.hstack([np.full((len(f), 1), 3), f]).astype(np.int64)
    return pv.PolyData(v, faces)


def render(view, leads):
    pl = pv.Plotter(off_screen=True, window_size=(2400, 2000))
    pl.set_background("white")
    for hemi in ("lh", "rh"):
        pl.add_mesh(pial(hemi), color="#d9d4ce", opacity=0.28, smooth_shading=True,
                    specular=0.3, ambient=0.25)
    for i, (lead, xyz) in enumerate(sorted(leads.items())):
        colour = LEAD_COLOURS[i % len(LEAD_COLOURS)]
        pl.add_mesh(pv.Spline(xyz, 50).tube(radius=0.5), color="#555555")
        for p in xyz:
            pl.add_mesh(pv.Sphere(radius=1.6, center=p), color=colour, smooth_shading=True,
                        specular=0.5)
    cams = {"lateral_left": "yz", "top": "xy", "oblique": None}
    if view == "oblique":
        pl.camera_position = "yz"
        pl.camera.azimuth = 215
        pl.camera.elevation = 25
    else:
        pl.camera_position = cams[view]
        if view == "lateral_left":
            pl.camera.azimuth = 180
    pl.camera.zoom(1.35)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"brain_electrodes_{view}.png"
    pl.screenshot(path, transparent_background=True)
    pl.close()
    return path


if __name__ == "__main__":
    leads = contacts_mri_mm()
    print({k: len(v) for k, v in leads.items()})
    for view in ("oblique", "lateral_left", "top"):
        print("wrote", render(view, leads))
