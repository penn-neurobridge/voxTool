"""Figure 5 v1: from VoxTool's coordinates to brain regions, with iEEG-recon as a
labeled black box.

The module descriptions follow iEEG-recon's own docs (github.com/penn-cnt/ieeg-recon,
docs/source/introduction.rst and module 2/3). The outputs shown are computed for
the public MNE sample with MNE-Python, standing in for Modules 2 and 3. Run
label_contacts.py, render_overlay.py, ../fig1 render_brain.py and ../fig4
capture_fig4.py first.

    conda run -n voxfig python paper/figures/fig5/scripts/compose_fig5.py
"""
import json
import sys
from pathlib import Path

import cairosvg
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fig1" / "scripts"))
from compose_fig1 import ACCENT, INK, MUTED, PANEL, WARM, arrow, heading, image, text  # noqa: E402

FIGS = Path(__file__).resolve().parents[2]
FIG = FIGS / "fig5"
A = FIG / "assets"
MONO = "Menlo, Courier New, monospace"
ROWS = ["LAMY 1", "LPHG 1", "RAHP 1", "RPHP 1", "LBRI 1", "LACN 1"]


def region(names):
    for n in names:
        if n == "Unknown" or "White-Matter" in n:
            continue
        n = n.replace("ctx-lh-", "L ").replace("ctx-rh-", "R ")
        return n.replace("Left-", "L ").replace("Right-", "R ")
    return "white matter"


def crop(src, box, name, trim=False):
    (A / "crops").mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    if box:
        im = im.crop(box)
    if trim:
        im = im.crop(im.getbbox())
    im.save(A / "crops" / name)
    return f"assets/crops/{name}", im.size


def build():
    c = {
        "mri": crop(A / "renders" / "ct_on_mri_coronal.png", (60, 100, 1140, 1080), "ct_on_mri.png"),
        "brain": crop(FIGS / "fig1" / "assets" / "renders" / "brain_electrodes_lateral_left.png",
                      None, "brain.png", trim=True),
    }
    labels = json.loads((A / "contact_labels.json").read_text())
    export = (FIGS / "fig4" / "assets" / "exported_voxel_coordinates.txt").read_text().splitlines()

    W, H = 2000, 980
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker></defs>',
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]

    # Input: VoxTool's file.
    lines = [ln.replace("\t", "  ") for ln in export[:5]] + ["…"]
    p += [
        heading(40, 60, 1, "VoxTool output"),
        f'<rect x="40" y="90" width="420" height="{70 + 30 * len(lines)}" rx="12" fill="{PANEL}"/>',
        text(60, 125, "voxel_coordinates.txt", size=17, weight="bold"),
    ]
    for n, ln in enumerate(lines):
        p.append(f'<text x="60" y="{160 + 30 * n}" font-family="{MONO}" font-size="17" '
                 f'fill="{INK}" xml:space="preserve">{ln}</text>')
    p += [
        text(40, 90 + 70 + 30 * len(lines) + 30, "CT voxel coordinates for every contact", size=16,
             fill=MUTED),
        f'<rect x="40" y="430" width="420" height="90" rx="12" fill="white" stroke="#c8ced8" '
        f'stroke-width="2"/>',
        text(60, 468, "+ pre-implant MRI", size=19, weight="bold"),
        text(60, 496, "(T1-weighted, same patient)", size=16, fill=MUTED),
        arrow(470, 300, 535, 300),
    ]

    # The black box.
    bx, by, bw, bh = 550, 90, 520, 430
    p += [
        heading(bx, 60, 2, "Downstream pipeline"),
        f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="18" fill="#1b2233"/>',
        text(bx + bw / 2, by + 60, "iEEG-recon", size=32, weight="bold", fill="white",
             anchor="middle"),
        text(bx + bw / 2, by + 92, "or MNE-Python, FieldTrip, …", size=17, fill="#aab4c8",
             anchor="middle"),
        f'<rect x="{bx + 30}" y="{by + 130}" width="{bw - 60}" height="120" rx="12" fill="#26314a"/>',
        text(bx + 50, by + 168, "Module 2 · register", size=20, weight="bold", fill="white"),
        text(bx + 50, by + 198, "align the CT to the MRI; move every", size=17, fill="#d5dceb"),
        text(bx + 50, by + 222, "contact from CT to MRI space", size=17, fill="#d5dceb"),
        f'<rect x="{bx + 30}" y="{by + 270}" width="{bw - 60}" height="130" rx="12" fill="#26314a"/>',
        text(bx + 50, by + 308, "Module 3 · label", size=20, weight="bold", fill="white"),
        text(bx + 50, by + 338, "assign each contact to an atlas", size=17, fill="#d5dceb"),
        text(bx + 50, by + 362, "region (DKT or any FreeSurfer atlas);", size=17, fill="#d5dceb"),
        text(bx + 50, by + 386, "optional MNI template space", size=17, fill="#d5dceb"),
        text(bx, by + bh + 34, "Module 1 of iEEG-recon is VoxTool itself.", size=16, fill=MUTED),
        arrow(1080, 300, 1145, 300),
    ]

    # Outputs.
    ox = 1160
    mw = 360
    mh = mw * c["mri"][1][1] / c["mri"][1][0]
    p += [
        heading(ox, 60, 3, "Outputs"),
        image(c["mri"][0], ox, 90, mw, mh, rx=12, clip_id="clip-mri"),
        text(ox + 14, 120, "R", size=20, weight="bold", fill="white"),
        text(ox + mw - 14, 120, "L", size=20, weight="bold", fill="white", anchor="end"),
        text(ox, 90 + mh + 28, "CT metal (orange) on the MRI", size=16, fill=MUTED),
    ]
    tx = ox + mw + 30
    p += [
        text(tx, 115, "Contact", size=16, weight="bold", fill=MUTED),
        text(tx + 120, 115, "Atlas region", size=16, weight="bold", fill=MUTED),
    ]
    for n, ch in enumerate(ROWS):
        lead = ch.split()[0]
        y = 150 + 36 * n
        p += [
            f'<line x1="{tx}" y1="{y - 26}" x2="{W - 40}" y2="{y - 26}" stroke="#e5e7eb"/>',
            text(tx, y, ch.replace(" ", ""), size=17, weight="bold"),
            text(tx + 120, y, region(labels[lead][ch]), size=17),
        ]
    bw2 = 520
    bh2 = bw2 * c["brain"][1][1] / c["brain"][1][0]
    p += [
        text(tx, 150 + 36 * len(ROWS), "deepest contact of each lead; FreeSurfer aparc+aseg",
             size=14, fill=MUTED),
        image(c["brain"][0], ox + 80, 90 + mh + 70, bw2, bh2, preserve="xMidYMid meet"),
        text(ox + 80 + bw2 / 2, 90 + mh + 70 + bh2 + 28, "every contact, inside a see-through brain",
             size=16, fill=MUTED, anchor="middle"),
        text(40, H - 22, "Data: MNE-Python sample sEEG subject (public, BSD-3). Outputs computed with "
             "MNE-Python (rigid CT-to-MRI registration; FreeSurfer aparc+aseg), standing in for "
             "iEEG-recon Modules 2 and 3.", size=14, fill=MUTED, italic=True),
        '</svg>',
    ]
    svg = FIG / "fig5_v1.svg"
    svg.write_text("\n".join(p))
    cairosvg.svg2png(url=str(svg), write_to=str(FIG / "fig5_v1.png"), output_width=W * 2,
                     unsafe=True)  # unsafe: allow linked local images
    print("wrote", svg, FIG / "fig5_v1.png")


if __name__ == "__main__":
    build()
