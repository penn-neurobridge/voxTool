"""Rough layout sketch for the Figure 1 operating-room illustration (a brief, not final art).

    conda run -n voxfig python paper/figures/fig1/scripts/sketch_or_panel.py

Writes sketches/or_panel_sketch.svg and .png. The left side is the panel at its
real shape (1 : 1.8); the right side holds notes for whoever draws it.
"""
import math
from pathlib import Path

import cairosvg

FIG = Path(__file__).resolve().parents[1]
OUT = FIG / "sketches"
FONT = "Helvetica, Arial, sans-serif"
INK = "#1b2233"
MUTED = "#5b6475"
SKIN = "#e9cdb8"
BONE = "#efe8dc"
CORTEX = "#e8b4ad"
WARM = "#e4572e"
NOTE = "#0ea5e9"


def t(x, y, s, size=16, weight="normal", fill=INK, anchor="start"):
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def gyri(cx, cy, rx, ry):
    """Wavy lines suggesting folds of cortex inside the opening."""
    out = []
    for k in range(-3, 4):
        y0 = cy + k * ry / 3.6
        pts = []
        for i in range(0, 41):
            x = cx - rx + i * (2 * rx / 40)
            if ((x - cx) / rx) ** 2 + ((y0 - cy) / ry) ** 2 > 0.92:
                continue
            pts.append(f"{x:.1f},{y0 + 7 * math.sin(i * 0.9 + k):.1f}")
        if len(pts) > 2:
            out.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#c98d86" '
                       f'stroke-width="2.5" stroke-linecap="round"/>')
    return "".join(out)


def grid(x, y, cols, rows, step):
    out = [f'<rect x="{x - 10}" y="{y - 10}" width="{(cols - 1) * step + 20}" '
           f'height="{(rows - 1) * step + 20}" rx="6" fill="white" fill-opacity="0.85" '
           f'stroke="#9aa3b2" stroke-width="2"/>']
    for i in range(cols):
        for j in range(rows):
            out.append(f'<circle cx="{x + i * step}" cy="{y + j * step}" r="4.5" fill="{WARM}"/>')
    # Tail cable leaving the grid toward the edge of the opening.
    out.append(f'<path d="M {x - 10} {y + step} C {x - 3 * step} {y}, {x - 3 * step} '
               f'{y - 4 * step}, {x - 2 * step} {y - 7 * step}" '
               f'stroke="#9aa3b2" stroke-width="6" fill="none" stroke-linecap="round"/>')
    return "".join(out)


def depth_lead(x0, y0, x1, y1, n=6):
    """A burr hole at (x0, y0) and a lead running inward; the inside part is dashed."""
    out = [f'<circle cx="{x0}" cy="{y0}" r="11" fill="#5b4a3f" stroke="{BONE}" stroke-width="3"/>',
           f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="#6b7280" stroke-width="4" '
           f'stroke-dasharray="10 7" stroke-linecap="round"/>']
    for k in range(n):
        f = 0.35 + 0.65 * k / (n - 1)
        out.append(f'<circle cx="{x0 + (x1 - x0) * f:.1f}" cy="{y0 + (y1 - y0) * f:.1f}" r="5" '
                   f'fill="{WARM}"/>')
    return "".join(out)


def marker(x, y, n):
    return (f'<circle cx="{x}" cy="{y}" r="13" fill="{NOTE}" stroke="white" stroke-width="3"/>'
            + t(x, y + 5, str(n), size=14, weight="bold", fill="white", anchor="middle"))


def callout(x, y, tx, ty, label, n):
    """A numbered marker on the drawing and the same number beside its note."""
    return marker(x, y, n) + marker(tx + 4, ty - 6, n) + t(tx + 26, ty, label, size=16,
                                                           weight="bold", fill=NOTE)


def build():
    W, H = 900, 760
    px, py, pw, ph = 40, 80, 360, 648          # the panel, 1 : 1.8
    cx, cy = px + pw / 2, py + ph * 0.5       # head centre
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="white"/>',
        t(40, 40, "Figure 1 · panel 1 · rough sketch for the illustration", size=20, weight="bold"),
        t(40, 64, "Layout only. Final art in BioRender; check accuracy with Dan.", size=15, fill=MUTED),
        f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="14" fill="#f4f6f9" '
        f'stroke="#9aa3b2" stroke-width="2" stroke-dasharray="8 6"/>',
        # Surgical drape around the head, then the scalp seen from above.
        f'<rect x="{px + 14}" y="{py + 14}" width="{pw - 28}" height="{ph - 28}" rx="10" fill="#9cc3c7" '
        f'fill-opacity="0.55"/>',
        f'<ellipse cx="{cx}" cy="{cy}" rx="140" ry="190" fill="{SKIN}" stroke="#c9a68d" stroke-width="3"/>',
        # Skin and bone edge of the craniotomy, then exposed cortex.
        f'<ellipse cx="{cx - 8}" cy="{cy - 10}" rx="98" ry="122" fill="{BONE}" stroke="#d8ccb8" '
        f'stroke-width="3"/>',
        f'<ellipse cx="{cx - 8}" cy="{cy - 10}" rx="84" ry="108" fill="{CORTEX}"/>',
        gyri(cx - 8, cy - 10, 84, 108),
        grid(cx - 60, cy - 70, 6, 5, 18),
        depth_lead(cx + 108, cy - 120, cx + 52, cy - 64, n=4),
        depth_lead(cx + 120, cy + 60, cx + 30, cy + 20),
        depth_lead(cx - 100, cy + 140, cx - 30, cy + 70),
        t(cx, py + 50, "front of head", size=13, fill=MUTED, anchor="middle"),
        f'<path d="M {cx} {py + 58} l -7 12 h 14 z" fill="{MUTED}"/>',
    ]

    nx = 450
    parts += [
        callout(cx - 33, cy - 52, nx, 150, "ECoG grid on the cortex", 1),
        t(nx + 26, 172, "flat sheet, 4×4 to 8×8 contacts; cable", size=14, fill=MUTED),
        t(nx + 26, 190, "leaves through the opening", size=14, fill=MUTED),
        callout(cx + 128, cy - 136, nx, 240, "sEEG depth leads (2–3)", 2),
        t(nx + 26, 262, "enter through small burr holes outside", size=14, fill=MUTED),
        t(nx + 26, 280, "the opening; contacts along each lead", size=14, fill=MUTED),
        callout(cx + 60, cy + 100, nx, 330, "Craniotomy opening", 3),
        t(nx + 26, 352, "skin and bone edge, cortex with folds", size=14, fill=MUTED),
        callout(px + 46, py + 46, nx, 400, "Sterile drape", 4),
        t(nx + 26, 422, "suggests the operating room", size=14, fill=MUTED),
        t(nx, 480, "Style", size=17, weight="bold"),
        t(nx, 504, "• clean, flat, no blood", size=15),
        t(nx, 526, "• contacts in warm orange-red (#e4572e),", size=15),
        t(nx, 548, "  same as electrodes elsewhere in the figure", size=15),
        t(nx, 570, "• view from above, slightly tilted is fine", size=15),
        t(nx, 610, "Avoid", size=17, weight="bold"),
        t(nx, 634, "• faces or real patient photos", size=15),
        t(nx, 656, "• text inside the art (labels go in the layout)", size=15),
        t(nx, 700, "Panel size: 1 wide × 1.8 tall (e.g. 1000 × 1800 px)", size=15, weight="bold"),
        '</svg>',
    ]
    OUT.mkdir(exist_ok=True)
    svg = OUT / "or_panel_sketch.svg"
    svg.write_text("\n".join(parts))
    cairosvg.svg2png(url=str(svg), write_to=str(OUT / "or_panel_sketch.png"), output_width=W * 2)
    print("wrote", svg, OUT / "or_panel_sketch.png")


if __name__ == "__main__":
    build()
