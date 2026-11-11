"""Render Figure 2's voxel panel from the CT itself: one axial slice and a zoom
onto the voxel grid around a single labeled contact.

Uses the contacts VoxTool loaded for Figure 1 (fig1/assets/sample_seeg_voxel_coordinates.json).

    conda run -n voxfig python paper/figures/fig2/scripts/render_voxels.py
"""
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from matplotlib.patches import Rectangle

matplotlib.use("Agg")

FIGS = Path(__file__).resolve().parents[2]
CT = FIGS / "fig1" / "assets" / "raw" / "mne_sample_seeg_CT.nii.gz"
COORDS = FIGS / "fig1" / "assets" / "sample_seeg_voxel_coordinates.json"
OUT = FIGS / "fig2" / "assets" / "renders"
LEAD, CONTACT = "LENT", "LENT3"
HALF = 8            # zoom shows (2*HALF+1) voxels per side
WINDOW = (300, 2500)  # HU: bone grey, metal white
WARM = "#e4572e"


def main():
    img = nib.load(CT)
    data = np.asarray(img.dataobj)
    lead = json.loads(COORDS.read_text())["leads"][LEAD]["contacts"]
    i, j, k = next(c for c in lead if c["name"] == CONTACT)["coordinate_spaces"]["ct_voxel"]["raw"]
    mm = img.affine @ np.array([i, j, k, 1.0])
    sl = data[:, :, k].T  # rows = j, cols = i; origin lower so j grows upward

    OUT.mkdir(parents=True, exist_ok=True)

    # Full axial slice with a box where the zoom comes from.
    fig = plt.figure(figsize=(6, 6), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(sl, cmap="gray", vmin=WINDOW[0], vmax=WINDOW[1], origin="lower",
              interpolation="nearest")
    ax.add_patch(Rectangle((i - HALF - 0.5, j - HALF - 0.5), 2 * HALF + 1, 2 * HALF + 1,
                           fill=False, ec=WARM, lw=2.5))
    ax.set_axis_off()
    fig.savefig(OUT / "axial_slice.png", facecolor="black")
    plt.close(fig)

    # Zoom: every voxel visible as a square, grid lines between them.
    z = sl[j - HALF:j + HALF + 1, i - HALF:i + HALF + 1]
    fig = plt.figure(figsize=(6, 6), dpi=200)
    ax = fig.add_axes([0.13, 0.11, 0.85, 0.85])
    ax.imshow(z, cmap="gray", vmin=WINDOW[0], vmax=WINDOW[1], origin="lower",
              interpolation="nearest",
              extent=(i - HALF - 0.5, i + HALF + 0.5, j - HALF - 0.5, j + HALF + 0.5))
    for v in np.arange(-HALF - 0.5, HALF + 1.5):
        ax.axvline(i + v, color="#3b4252", lw=0.6)
        ax.axhline(j + v, color="#3b4252", lw=0.6)
    ax.add_patch(Rectangle((i - 0.5, j - 0.5), 1, 1, fill=False, ec=WARM, lw=3))
    ticks_i = [i - HALF + 2, i, i + HALF - 2]
    ticks_j = [j - HALF + 2, j, j + HALF - 2]
    ax.set_xticks(ticks_i)
    ax.set_yticks(ticks_j)
    ax.tick_params(labelsize=13, colors="#1b2233")
    ax.set_xlabel("i (voxel column)", fontsize=14, color="#1b2233")
    ax.set_ylabel("j (voxel row)", fontsize=14, color="#1b2233")
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(OUT / "voxel_zoom.png", facecolor="white")
    plt.close(fig)

    info = {"contact": CONTACT, "voxel": [i, j, k], "mm": [round(float(x), 1) for x in mm[:3]],
            "voxel_size_mm": [round(float(x), 3) for x in img.header.get_zooms()]}
    (OUT / "voxel_example.json").write_text(json.dumps(info))
    print(info)


if __name__ == "__main__":
    main()
