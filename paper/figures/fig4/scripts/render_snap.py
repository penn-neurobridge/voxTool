"""Figure 4 inset: how a click snaps to a contact.

Replays VoxTool's snap (routes/scans.py, snap()) on the sample CT: start at an
off-centre click, then twice move to the mean of the above-threshold voxels
within r. Draws one axial slice of the voxel grid with the radius and the path.

    conda run -n voxfig python paper/figures/fig4/scripts/render_snap.py
"""
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from matplotlib.patches import Circle

matplotlib.use("Agg")

FIGS = Path(__file__).resolve().parents[2]
CT = FIGS / "fig1" / "assets" / "raw" / "mne_sample_seeg_CT.nii.gz"
COORDS = FIGS / "fig1" / "assets" / "sample_seeg_voxel_coordinates.json"
OUT = FIGS / "fig4" / "assets" / "renders"
LEAD, CONTACT = "RAHP", "RAHP4"
CLICK_OFFSET = np.array([-3.0, 3.0, 0.0])  # voxels: a click a little up-left of the contact
RADIUS_MM, ITERATIONS, PCT = 3.0, 2, 99.96  # VoxTool's defaults for a click
HALF = 11
WARM, ACCENT, INK = "#e4572e", "#0ea5e9", "#1b2233"


def main():
    img = nib.load(CT)
    data = np.asarray(img.dataobj)
    contact = next(c for c in json.loads(COORDS.read_text())["leads"][LEAD]["contacts"]
                   if c["name"] == CONTACT)
    i, j, k = contact["coordinate_spaces"]["ct_voxel"]["raw"]

    # The same arithmetic as VoxTool's snap().
    thr = np.percentile(data, PCT)
    points = np.argwhere(data >= thr).astype(np.float32)
    radius_vox = RADIUS_MM / float(np.mean(np.abs(np.diag(img.affine[:3, :3]))))
    path = [np.array([i, j, k], dtype=np.float32) + CLICK_OFFSET]
    counts = []
    for _ in range(ITERATIONS):
        near = points[np.sum((points - path[-1]) ** 2, axis=1) <= radius_vox ** 2]
        if not len(near):
            break
        path.append(near.mean(axis=0))
        counts.append(len(near))

    sl = data[:, :, k].T
    ext = (i - HALF - 0.5, i + HALF + 0.5, j - HALF - 0.5, j + HALF + 0.5)
    z = sl[j - HALF:j + HALF + 1, i - HALF:i + HALF + 1]
    OUT.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(6, 6), dpi=200)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.imshow(z, cmap="gray", vmin=300, vmax=2500, origin="lower", interpolation="nearest",
              extent=ext)
    bright = np.ma.masked_where(z < thr, np.ones_like(z, dtype=float))
    ax.imshow(bright, cmap=matplotlib.colors.ListedColormap([WARM]), alpha=0.55,
              origin="lower", interpolation="nearest", extent=ext)
    for v in np.arange(-HALF - 0.5, HALF + 1.5):
        ax.axvline(i + v, color="#3b4252", lw=0.5)
        ax.axhline(j + v, color="#3b4252", lw=0.5)
    c0 = path[0]
    ax.add_patch(Circle((c0[0], c0[1]), radius_vox, fill=False, ec=ACCENT, lw=2.5, ls="--"))
    xs, ys = [p[0] for p in path], [p[1] for p in path]
    ax.plot(xs, ys, color=ACCENT, lw=2.5)
    ax.plot(c0[0], c0[1], marker="x", color=ACCENT, ms=16, mew=4)
    ax.plot(xs[1:-1], ys[1:-1], "o", color="white", ms=8, mec=ACCENT, mew=2.5)
    ax.plot(xs[-1], ys[-1], "o", color=ACCENT, ms=12, mec="white", mew=2.5)
    ax.set_xlim(ext[:2])
    ax.set_ylim(ext[2:])
    ax.set_axis_off()
    fig.savefig(OUT / "snap_inset.png", facecolor="white")
    plt.close(fig)

    info = {"contact": CONTACT, "contact_voxel": [i, j, k],
            "click_voxel": [round(float(v), 1) for v in path[0]],
            "path": [[round(float(v), 2) for v in p] for p in path],
            "voxels_used": counts, "radius_mm": RADIUS_MM, "radius_vox": round(radius_vox, 2),
            "threshold_hu": float(thr), "threshold_pct": PCT}
    (OUT / "snap_example.json").write_text(json.dumps(info, indent=1))
    print(info)


if __name__ == "__main__":
    main()
