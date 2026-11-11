"""Figure 3 v1: where VoxTool runs and where the data lives, plus the Pennsieve flow.

A diagram, drawn from what the code does today (routes/pennsieve.py refuses in
cloud mode; scan_store.py keeps web uploads on the server and in S3; there is
no OpenNeuro code yet). Logos come from fig1/assets/logos.

    conda run -n voxfig python paper/figures/fig3/scripts/compose_fig3.py
"""
import sys
from pathlib import Path

import cairosvg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fig1" / "scripts"))
from compose_fig1 import ACCENT, INK, MUTED, PANEL, arrow, heading, image, text  # noqa: E402

FIG = Path(__file__).resolve().parents[1]
LOGOS = "../fig1/assets/logos"
GREEN, AMBER, GREY = "#16a34a", "#d97706", "#9aa3b2"


def pill(x, y, label, colour, dashed=False):
    w = 14 + 9.2 * len(label)
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    fill = "white" if dashed else colour
    fg = colour if dashed else "white"
    return (f'<rect x="{x}" y="{y}" width="{w}" height="30" rx="15" fill="{fill}" '
            f'stroke="{colour}" stroke-width="2"{dash}/>'
            + text(x + w / 2, y + 21, label, size=15, weight="bold", fill=fg, anchor="middle"))


def cell(x, y, w, h, status, colour, lines, dashed=False):
    border = ' stroke-dasharray="10 7"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="white" '
           f'stroke="{colour}" stroke-width="2.5"{border}/>',
           pill(x + 20, y + 20, status, colour, dashed)]
    for n, ln in enumerate(lines):
        out.append(text(x + 20, y + 85 + 27 * n, ln, size=18, fill=INK if n == 0 else MUTED,
                        weight="bold" if n == 0 else "normal"))
    return "\n".join(out)


def box(x, y, w, h, title, sub, fill="white", stroke="#c8ced8", dashed=False):
    dash = ' stroke-dasharray="10 7"' if dashed else ""
    out = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" '
           f'stroke="{stroke}" stroke-width="2.5"{dash}/>'
           + text(x + w / 2, y + 42, title, size=20, weight="bold", anchor="middle"))
    for n, s in enumerate(sub):
        out += text(x + w / 2, y + 72 + 24 * n, s, size=15, fill=MUTED, anchor="middle")
    return out


def build():
    W, H = 2000, 1160
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
        f'fill="{INK}"/></marker></defs>',
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]

    # A · The 2 × 2.
    gx, gy, cw, ch = 330, 150, 790, 175
    p += [
        heading(40, 60, "A", "Where VoxTool runs × where the CT lives"),
        text(gx + cw / 2, gy - 20, "Desktop app  ·  macOS, Windows  (Linux: run from source)",
             size=19, weight="bold", anchor="middle"),
        text(gx + cw + 30 + cw / 2, gy - 20, "Web app  ·  any browser, nothing to install",
             size=19, weight="bold", anchor="middle"),
        text(300, gy + ch / 2 - 6, "CT on your", size=19, weight="bold", anchor="end"),
        text(300, gy + ch / 2 + 18, "computer", size=19, weight="bold", anchor="end"),
        text(300, gy + ch + 30 + ch / 2 - 6, "CT in the", size=19, weight="bold", anchor="end"),
        text(300, gy + ch + 30 + ch / 2 + 18, "cloud", size=19, weight="bold", anchor="end"),
        cell(gx, gy, cw, ch, "Available", GREEN,
             ["Open a CT in place, from any folder.",
              "Nothing leaves the machine. Implant plans are read",
              "by a model running locally."]),
        cell(gx + cw + 30, gy, cw, ch, "Available · de-identified data only", AMBER,
             ["Upload a CT from the browser.",
              "It is stored on the server (AWS), and the web app has",
              "no login yet, so use public or de-identified scans."]),
        cell(gx, gy + ch + 30, cw, ch, "Available · Pennsieve", GREEN,
             ["Open a CT from a Pennsieve dataset; upload",
              "coordinates back to it. Uses the Pennsieve agent",
              "on this machine. OpenNeuro: planned."]),
        cell(gx + cw + 30, gy + ch + 30, cw, ch, "Planned", GREY,
             ["Not yet.",
              "Pennsieve needs the agent on your own machine,",
              "so the web app cannot reach it."], dashed=True),
    ]

    # B · The Pennsieve flow.
    by = 650
    p += [
        heading(40, by, "B", "Opening and saving through the Pennsieve API (desktop app)"),
        box(40, by + 40, 330, 150, "VoxTool", ["local server on", "your computer"],
            fill=PANEL),
        box(520, by + 40, 330, 150, "Pennsieve agent", ["also on your computer;", "holds the sign-in"],
            fill=PANEL),
        f'<rect x="1000" y="{by + 40}" width="380" height="150" rx="14" fill="white" '
        f'stroke="#c8ced8" stroke-width="2.5"/>',
        image(f"{LOGOS}/pennsieve-logo-full.png", 1040, by + 70, 300, 60, preserve="xMidYMid meet"),
        text(1190, by + 162, "Pennsieve API (cloud)", size=16, fill=MUTED, anchor="middle"),
        box(1530, by + 40, 430, 150, "Your dataset",
            ["primary/sub-XX/ses-postimplant/ct", "derivatives/voxtool_ct (coordinates)"]),
        f'<line x1="378" y1="{by + 95}" x2="512" y2="{by + 95}" stroke="{INK}" stroke-width="3.5" '
        f'marker-start="url(#arrow)" marker-end="url(#arrow)"/>',
        text(445, by + 80, "session token", size=15, weight="bold", anchor="middle"),
        f'<line x1="858" y1="{by + 95}" x2="992" y2="{by + 95}" stroke="{INK}" stroke-width="3.5" '
        f'marker-start="url(#arrow)" marker-end="url(#arrow)"/>',
        text(925, by + 80, "upload", size=15, weight="bold", anchor="middle"),
        f'<line x1="1388" y1="{by + 95}" x2="1522" y2="{by + 95}" stroke="{INK}" stroke-width="3.5" '
        f'marker-start="url(#arrow)" marker-end="url(#arrow)"/>',
        # VoxTool reads directly from the REST API with the agent's token.
        f'<path d="M 205 {by + 198} C 205 {by + 290}, 1190 {by + 290}, 1190 {by + 198}" '
        f'stroke="{ACCENT}" stroke-width="3.5" fill="none" marker-end="url(#arrow)"/>',
        text(700, by + 300, "browse datasets and download a CT (REST API, with the agent's token)",
             size=16, weight="bold", fill=ACCENT, anchor="middle"),
    ]

    # Notes and OpenNeuro.
    ny = by + 350
    p += [
        text(40, ny, "The API key lives in the Pennsieve agent's own config; VoxTool never keeps it.",
             size=17, fill=MUTED),
        text(40, ny + 28, "Uploads go only to datasets this computer is allowed to write to "
             "(a per-computer setting).", size=17, fill=MUTED),
        f'<rect x="1300" y="{ny - 40}" width="660" height="110" rx="14" fill="white" '
        f'stroke="{GREY}" stroke-width="2.5" stroke-dasharray="10 7"/>',
        image(f"{LOGOS}/openneuro-brand-mark.png", 1325, ny - 22, 72, 72, preserve="xMidYMid meet"),
        text(1415, ny + 2, "OpenNeuro API", size=22, weight="bold"),
        text(1415, ny + 32, "planned: open public datasets by ID", size=17, fill=MUTED),
        '</svg>',
    ]
    svg = FIG / "fig3_v1.svg"
    svg.write_text("\n".join(p))
    cairosvg.svg2png(url=str(svg), write_to=str(FIG / "fig3_v1.png"), output_width=W * 2,
                     unsafe=True)  # unsafe: allow linked local images
    print("wrote", svg, FIG / "fig3_v1.png")


if __name__ == "__main__":
    build()
