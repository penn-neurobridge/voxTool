"""Figure 4 v1: labeling a patient step by step, plus how a click snaps.

Run make_plan.py, capture_fig4.py and render_snap.py first. Then:

    conda run -n voxfig python paper/figures/fig4/scripts/compose_fig4.py
"""
import json
import sys
from pathlib import Path

import cairosvg
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fig1" / "scripts"))
from compose_fig1 import ACCENT, INK, MUTED, PANEL, WARM, arrow, heading, image, text  # noqa: E402

FIG = Path(__file__).resolve().parents[1]
A = FIG / "assets"
MONO = "Menlo, Courier New, monospace"


def crop(src, box, name):
    (A / "crops").mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    if box:
        im = im.crop(box)
    im.save(A / "crops" / name)
    return f"assets/crops/{name}", im.size


def build():
    s = A / "screens"
    lead_box = tuple(json.loads((A / "lead_crop_box.json").read_text()))
    lead_box = (lead_box[0] + 22, lead_box[1] + 5, lead_box[2] - 16, lead_box[3] - 85)
    c = {
        "plan": crop(s / "step1_plan_read.png", (0, 0, 1800, 1120), "plan_read.png"),
        "ends": crop(s / "step2_ends.png", lead_box, "ends.png"),
        "filled": crop(s / "step3_interpolated.png", lead_box, "filled.png"),
        "status": crop(s / "step3_status.png", None, "interp_status.png"),
        "snap": crop(A / "renders" / "snap_inset.png", None, "snap_inset.png"),
    }
    snap = json.loads((A / "renders" / "snap_example.json").read_text())
    export = (A / "exported_voxel_coordinates.txt").read_text().splitlines()

    W, H = 2000, 1190
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker></defs>',
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]

    # 1 · Read the plan.
    pw = 600
    ph = pw * c["plan"][1][1] / c["plan"][1][0]
    p += [
        heading(40, 60, 1, "Read the implant plan"),
        image(c["plan"][0], 40, 90, pw, ph, rx=12, clip_id="clip-plan"),
        text(40, 90 + ph + 32, "The local model fills in each lead's name, contacts and target.",
             size=16, fill=MUTED),
        text(40, 90 + ph + 56, "Gaps in the channel map are flagged to check (yellow).", size=16,
             fill=MUTED),
    ]

    # 2 and 3 · Mark the two ends, then interpolate.
    x2, sw = 720, 620
    sh = sw * c["ends"][1][1] / c["ends"][1][0]
    p += [
        arrow(650, 280, 700, 280),
        heading(x2, 60, 2, "Mark the two end contacts"),
        image(c["ends"][0], x2, 90, sw, sh, rx=12, clip_id="clip-ends"),
        text(x2, 90 + sh + 28, "RAHP1 and RAHP8 placed (blue); the 6 between are still unlabeled.",
             size=16, fill=MUTED),
    ]
    y3 = 90 + sh + 90
    stw = 380
    sth = stw * c["status"][1][1] / c["status"][1][0]
    p += [
        heading(x2, y3, 3, "Interpolate"),
        image(c["filled"][0], x2, y3 + 30, sw, sh, rx=12, clip_id="clip-filled"),
        image(c["status"][0], x2, y3 + 30 + sh + 16, stw, sth, preserve="xMidYMid meet"),
        text(x2 + stw + 20, y3 + 30 + sh + 40, "Steps along the lead from", size=16, fill=MUTED),
        text(x2 + stw + 20, y3 + 30 + sh + 62, "both ends; each contact", size=16, fill=MUTED),
        text(x2 + stw + 20, y3 + 30 + sh + 84, "snaps to its own metal.", size=16, fill=MUTED),
    ]

    # 4 · Save.
    x4 = 1490
    lines = [ln.replace("\t", "  ") for ln in export]
    p += [
        arrow(1360, 280, 1470, 280),
        heading(x4, 60, 4, "Save"),
        f'<rect x="{x4}" y="90" width="470" height="{60 + 30 * len(lines)}" rx="12" fill="{PANEL}"/>',
        text(x4 + 20, 125, "voxel_coordinates.txt", size=17, weight="bold"),
    ]
    for n, ln in enumerate(lines):
        p.append(f'<text x="{x4 + 20}" y="{160 + 30 * n}" font-family="{MONO}" font-size="17" '
                 f'fill="{INK}" xml:space="preserve">{ln}</text>')
    yb = 90 + 60 + 30 * len(lines) + 30
    p += [
        text(x4, yb, "name · i · j · k · type · dimensions", size=15, fill=MUTED),
        text(x4, yb + 22, "Voxel coordinates, also as JSON.", size=15, fill=MUTED),
    ]

    # Inset · how a click snaps.
    top = 700
    path = snap["path"]
    p += [
        f'<rect x="40" y="{top}" width="1920" height="{H - top - 60}" rx="18" fill="{PANEL}"/>',
        text(70, top + 50, "How a click snaps to a contact", size=24, weight="bold"),
        image(c["snap"][0], 70, top + 75, 340, 340, rx=8, clip_id="clip-snap"),
        f'<text x="460" y="{top + 130}" font-family="{MONO}" font-size="26" fill="{INK}">'
        f'c<tspan baseline-shift="sub" font-size="18">t+1</tspan> = mean {{ x : I(x) ≥ T, '
        f'|x − c<tspan baseline-shift="sub" font-size="18">t</tspan>| ≤ r }}</text>',
        text(460, top + 180, "Start at the click c₀ (×). Average every bright voxel within r of it; "
             "move there; repeat.", size=18),
        text(460, top + 210, "It is a local mean on the bright voxels, not k-means: "
             "each click converges to the contact under it.", size=18),
        text(460, top + 270, "Defaults", size=18, weight="bold"),
        text(460, top + 298, f"T = {snap['threshold_pct']}th percentile of the CT "
             f"({snap['threshold_hu']:,.0f} HU here)", size=17),
        text(460, top + 324, f"r = {snap['radius_mm']:g} mm  ·  {len(path) - 1} iterations for a "
             f"click", size=17),
        text(460, top + 380, "This example", size=18, weight="bold", fill=ACCENT),
        text(460, top + 408, f"click at {tuple(round(v) for v in path[0])}  ·  averages "
             f"{snap['voxels_used'][0]}, then {snap['voxels_used'][1]} bright voxels  ·  lands on "
             f"{tuple(round(v) for v in path[-1])}, contact {snap['contact']}", size=17),
        f'<rect x="1420" y="{top + 100}" width="500" height="150" rx="12" fill="white"/>',
        f'<line x1="1450" y1="{top + 140}" x2="1490" y2="{top + 140}" stroke="{ACCENT}" '
        f'stroke-width="3" stroke-dasharray="7 5"/>',
        text(1505, top + 146, "search radius r around the click", size=16),
        f'<rect x="1452" y="{top + 172}" width="34" height="18" fill="{WARM}" opacity="0.55"/>',
        text(1505, top + 186, "voxels at or above T (this slice)", size=16),
        f'<circle cx="1470" cy="{top + 220}" r="8" fill="{ACCENT}" stroke="white" stroke-width="2"/>',
        text(1505, top + 226, "where the click lands", size=16),
        text(40, H - 22, "Data: MNE-Python sample sEEG CT (public, BSD-3); example plan made from "
             "its lead list. Screenshots: VoxTool 1.1.2. Inset: VoxTool's snap replayed on the CT.",
             size=14, fill=MUTED, italic=True),
        '</svg>',
    ]
    svg = FIG / "fig4_v1.svg"
    svg.write_text("\n".join(p))
    cairosvg.svg2png(url=str(svg), write_to=str(FIG / "fig4_v1.png"), output_width=W * 2,
                     unsafe=True)  # unsafe: allow linked local images
    print("wrote", svg, FIG / "fig4_v1.png")


if __name__ == "__main__":
    build()
