"""Figure 2 v1: the two coordinate systems.

A: voxel coordinates on a CT slice (what VoxTool saves), with the affine that
turns them into millimetres. B: VoxTool's millimetre point cloud at rising
thresholds. Run capture_thresholds.py and render_voxels.py first.

    conda run -n voxfig python paper/figures/fig2/scripts/compose_fig2.py
"""
import json
import sys
from pathlib import Path

import cairosvg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fig1" / "scripts"))
from compose_fig1 import ACCENT, INK, MUTED, PANEL, WARM, arrow, crop, heading, image, text  # noqa: E402

FIG = Path(__file__).resolve().parents[1]
A = FIG / "assets"

# (percentile, HU threshold, voxels above, what is left) as VoxTool reported them.
STEPS = [("90", "596", "5,178,644", "whole skull"),
         ("98", "1,918", "942,956", "dense bone"),
         ("99.96", "3,071", "25,558", "electrodes and teeth")]


def rel(name):
    return f"assets/crops/{name}"


def make_crops():
    crops = A / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    out = {}
    for pct, *_ in STEPS:
        src = A / "screens" / f"cloud_p{pct}.png"
        out[pct] = _crop(src, (1140, 697, 2140, 1697), f"cloud_p{pct}.png")
    out["axial"] = _crop(A / "renders" / "axial_slice.png", None, "axial_slice.png")
    out["zoom"] = _crop(A / "renders" / "voxel_zoom.png", None, "voxel_zoom.png")
    return out


def _crop(src, box, name):
    from PIL import Image
    im = Image.open(src)
    if box:
        im = im.crop(box)
    im.save(A / "crops" / name)
    return rel(name), im.size


def build():
    c = make_crops()
    ex = json.loads((A / "renders" / "voxel_example.json").read_text())
    i, j, k = ex["voxel"]
    r, a, s = ex["mm"]
    vx, vy, vz = ex["voxel_size_mm"]
    W, H = 2000, 1330
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker></defs>',
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]

    # A · Voxel coordinates.
    parts += [
        '<g id="panel-a-voxel">',
        heading(40, 60, "A", "Voxel coordinates: what VoxTool saves"),
        image(c["axial"][0], 40, 95, 380, 380, rx=12, clip_id="clip-axial"),
        text(230, 505, f"axial slice k = {k}", size=16, fill=MUTED, anchor="middle"),
        arrow(430, 285, 470, 285),
        image(c["zoom"][0], 480, 85, 410, 410, preserve="xMidYMid meet"),
        text(1000, 140, "Contact LENT 3", size=22, weight="bold"),
        f'<text x="1000" y="190" font-family="Menlo, Courier New, monospace" font-size="30" '
        f'font-weight="bold" fill="{WARM}">(i, j, k) = ({i}, {j}, {k})</text>',
        text(1000, 228, "whole-number indices into the CT array", size=17, fill=MUTED),
        text(1000, 254, f"one voxel = {vx} × {vy} × {vz} mm", size=17, fill=MUTED),
        '</g>',
    ]

    # The bridge: the affine in the NIfTI header turns voxels into millimetres.
    bx, by = 1000, 300
    parts += [
        '<g id="affine">',
        f'<rect x="{bx}" y="{by}" width="940" height="190" rx="14" fill="{PANEL}"/>',
        text(bx + 24, by + 40, "From voxels to millimetres: the affine in the file header", size=19,
             weight="bold"),
        f'<text x="{bx + 24}" y="{by + 95}" font-family="Menlo, Courier New, monospace" '
        f'font-size="24" fill="{INK}">[R, A, S, 1] = affine · [i, j, k, 1]</text>',
        f'<text x="{bx + 24}" y="{by + 148}" font-family="Menlo, Courier New, monospace" '
        f'font-size="24" fill="{INK}">({i}, {j}, {k})  →  '
        f'<tspan fill="{ACCENT}" font-weight="bold">({r}, {a}, {s}) mm</tspan></text>',
        text(bx + 24, by + 176, "R = right, A = anterior, S = superior (scanner space)", size=15,
             fill=MUTED),
        '</g>',
    ]

    # B · Millimetre point cloud at rising thresholds.
    top = 600
    cw = 590
    ch = cw * c["90"][1][1] / c["90"][1][0]
    parts += [
        '<g id="panel-b-mm">',
        heading(40, top - 30, "B", "Millimetre coordinates: Electrode View at rising thresholds"),
    ]
    for n, (pct, hu, count, left) in enumerate(STEPS):
        x = 40 + n * (cw + 35)
        parts += [
            image(c[pct][0], x, top, cw, ch, rx=12, clip_id=f"clip-cloud-{n}"),
            text(x + cw / 2, top + ch + 36, f"≥ {pct}th percentile  ·  ≥ {hu} HU", size=19,
                 weight="bold", anchor="middle"),
            text(x + cw / 2, top + ch + 62, f"{left}  ·  {count} voxels", size=16, fill=MUTED,
                 anchor="middle"),
        ]
        if n < 2:
            parts.append(arrow(x + cw + 4, top + ch / 2, x + cw + 31, top + ch / 2))
    parts += [
        '</g>',
        text(40, H - 22, "Data: MNE-Python sample sEEG CT (public, BSD-3). Panel B: VoxTool 1.1.2 "
             "Electrode View; at most 120,000 points are drawn.", size=14, fill=MUTED, italic=True),
        '</svg>',
    ]
    svg = FIG / "fig2_v1.svg"
    svg.write_text("\n".join(parts))
    cairosvg.svg2png(url=str(svg), write_to=str(FIG / "fig2_v1.png"), output_width=W * 2,
                     unsafe=True)  # unsafe: allow linked local images
    print("wrote", svg, FIG / "fig2_v1.png")


if __name__ == "__main__":
    build()
