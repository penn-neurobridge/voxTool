"""Compose Figure 1 (overview) v1 as an editable SVG plus a PNG preview.

Run capture_screens.py and render_brain.py first. Then:

    conda run -n voxfig python paper/figures/fig1/scripts/compose_fig1.py

Writes fig1_v1.svg (images linked from assets/, so Affinity keeps them as
separate replaceable layers) and fig1_v1.png. Placeholders are hatched boxes.
"""
from pathlib import Path

import cairosvg
from PIL import Image

FIG = Path(__file__).resolve().parents[1]
A = FIG / "assets"
CROPS = A / "crops"

INK = "#1b2233"
MUTED = "#5b6475"
ACCENT = "#0ea5e9"   # VoxTool's own cyan, so the figure matches the app
WARM = "#e4572e"     # electrodes / contacts
PANEL = "#f3f5f8"
FONT = "Helvetica, Arial, sans-serif"


def crop(src, box, name, trim=False):
    CROPS.mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    if box:
        im = im.crop(box)
    if trim:
        im = im.crop(im.getbbox())
    out = CROPS / name
    im.save(out)
    return out.relative_to(FIG).as_posix(), im.size


def make_crops():
    s = A / "screens"
    return {
        "slices": crop(s / "mne_slices_nosidebar.png", (720, 405, 2480, 1945), "slices_4up.png"),
        "axial": crop(s / "mne_slices_nosidebar.png", (720, 1070, 1597, 1945), "axial.png"),
        "coronal": crop(s / "mne_slices_nosidebar.png", (720, 405, 1597, 1065), "coronal.png"),
        "cloud": crop(s / "mne_cloud_nosidebar.png", (1040, 480, 2320, 1760), "cloud.png"),
        "app": crop(s / "mne_app_cloud.png", None, "app_full.png"),
        "brain": crop(A / "renders" / "brain_electrodes_lateral_left.png", None, "brain.png", trim=True),
    }


def text(x, y, s, size=18, weight="normal", fill=INK, anchor="start", italic=False):
    style = "italic" if italic else "normal"
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" font-style="{style}" fill="{fill}" '
            f'text-anchor="{anchor}">{s}</text>')


def image(href, x, y, w, h, preserve="xMidYMid slice", rx=0, clip_id=None):
    clip = ""
    if rx:
        clip = (f'<clipPath id="{clip_id}"><rect x="{x}" y="{y}" width="{w}" height="{h}" '
                f'rx="{rx}"/></clipPath>')
    attr = f' clip-path="url(#{clip_id})"' if rx else ""
    return (f'{clip}<image href="{href}" xlink:href="{href}" x="{x}" y="{y}" width="{w}" height="{h}" '
            f'preserveAspectRatio="{preserve}"{attr}/>')


def placeholder(x, y, w, h, lines):
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="url(#hatch)" '
           f'stroke="#9aa3b2" stroke-width="2" stroke-dasharray="8 6"/>']
    cy = y + h / 2 - (len(lines) - 1) * 13
    for i, ln in enumerate(lines):
        out.append(text(x + w / 2, cy + i * 26, ln, size=17 if i else 19,
                        weight="bold" if i == 0 else "normal",
                        fill=INK if i == 0 else MUTED, anchor="middle"))
    return "\n".join(out)


def badge(x, y, n):
    return (f'<circle cx="{x}" cy="{y}" r="17" fill="{INK}"/>'
            + text(x, y + 6, str(n), size=18, weight="bold", fill="white", anchor="middle"))


def heading(x, y, n, title):
    return badge(x + 17, y - 6, n) + text(x + 44, y, title, size=24, weight="bold")


def arrow(x1, y1, x2, y2, label=None, colour=INK):
    out = (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" '
           f'stroke-width="4" marker-end="url(#arrow)"/>')
    if label:
        out += text((x1 + x2) / 2, min(y1, y2) - 12, label, size=16, weight="bold",
                    fill=colour, anchor="middle")
    return out


def chip(x, y, w, label, colour=ACCENT):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="38" rx="19" fill="white" '
            f'stroke="{colour}" stroke-width="2.5"/>'
            + text(x + w / 2, y + 25, label, size=16, weight="bold", fill=INK, anchor="middle"))


def implant_plan(x, y, w, h):
    """A schematic implant plan: lead names and contact counts from the public sample."""
    rows = [("LAMY", 7), ("LENT", 7), ("LOFC", 9), ("LSMA", 16), ("RAHP", 8), ("…", "")]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="white" '
           f'stroke="#c8ced8" stroke-width="2"/>',
           f'<path d="M{x + w - 34},{y} l34,34 h-34 z" fill="#e6e9ee"/>',
           text(x + 18, y + 34, "Implant plan", size=18, weight="bold"),
           text(x + 18, y + 58, "PDF · PowerPoint", size=14, fill=MUTED)]
    ty = y + 88
    out.append(text(x + 18, ty, "Lead", size=14, weight="bold", fill=MUTED))
    out.append(text(x + w - 18, ty, "Contacts", size=14, weight="bold", fill=MUTED, anchor="end"))
    for i, (lead, n) in enumerate(rows):
        yy = ty + 26 + i * 25
        out.append(f'<line x1="{x + 14}" y1="{yy - 18}" x2="{x + w - 14}" y2="{yy - 18}" '
                   f'stroke="#eef0f3" stroke-width="1.5"/>')
        out.append(text(x + 18, yy, lead, size=15))
        out.append(text(x + w - 18, yy, str(n), size=15, anchor="end"))
    return "\n".join(out)


def window(x, y, w, h, title):
    """A plain app-window frame so the screenshots read as one program."""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="#1e2a44" '
            f'filter="url(#shadow)"/>'
            f'<circle cx="{x + 24}" cy="{y + 20}" r="6" fill="#ff5f57"/>'
            f'<circle cx="{x + 44}" cy="{y + 20}" r="6" fill="#febc2e"/>'
            f'<circle cx="{x + 64}" cy="{y + 20}" r="6" fill="#28c840"/>'
            + text(x + w / 2, y + 26, title, size=15, fill="#c9d4e8", anchor="middle"))


def cloud_shape(cx, cy, s=1.0):
    blobs = [(-70, 10, 55), (0, -25, 70), (75, 5, 55), (-120, 40, 38), (125, 40, 38)]
    circles = "".join(f'<circle cx="{x}" cy="{y}" r="{r}"/>' for x, y, r in blobs)
    # Outline pass, then a white fill pass on top so the inner seams disappear.
    g = f'<g transform="translate({cx},{cy - 40}) scale({s})" fill="white"'
    return (f'{g} stroke="#9fb4cf" stroke-width="6">{circles}'
            '<rect x="-125" y="20" width="250" height="58" rx="29"/></g>'
            f'{g}>{circles}<rect x="-125" y="20" width="250" height="58" rx="29"/></g>')


def build():
    c = make_crops()
    W, H = 2000, 1180
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        '<defs>'
        '<pattern id="hatch" width="14" height="14" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><rect width="14" height="14" fill="#f7f8fa"/>'
        '<line x1="0" y1="0" x2="0" y2="14" stroke="#e3e6ec" stroke-width="5"/></pattern>'
        f'<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker>'
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">'
        '<feDropShadow dx="0" dy="6" stdDeviation="9" flood-opacity="0.22"/></filter>'
        '</defs>',
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]

    # 1 · The patient: why localization matters, and what a CT is.
    parts += [
        f'<g id="panel-1-patient">',
        heading(40, 60, 1, "The patient"),
        placeholder(40, 90, 420, 330, ["Operating-room photo", "open craniotomy with ECoG grid",
                                       "and sEEG depth leads", "source: CC-licensed / BioRender / Dan"]),
        text(40, 470, "What is a CT?", size=20, weight="bold"),
        placeholder(40, 490, 200, 240, ["Person", "in the scanner", "(BioRender)"]),
        arrow(248, 610, 262, 610),
        image(c["coronal"][0], 270, 490, 190, 240, rx=12, clip_id="clip-coronal"),
        text(365, 755, "one CT slice", size=14, fill=MUTED, anchor="middle"),
        text(40, 800, "Bright = dense: bone, and metal", size=16, fill=MUTED),
        text(40, 822, "electrodes brightest of all.", size=16, fill=MUTED),
        '</g>',
    ]

    # 2 · Inputs.
    parts += [
        f'<g id="panel-2-inputs">',
        heading(510, 60, 2, "Inputs"),
        implant_plan(510, 90, 250, 270),
        f'<rect x="530" y="420" width="230" height="230" rx="12" fill="#0b0d12"/>',
        f'<rect x="520" y="410" width="230" height="230" rx="12" fill="#11141b"/>',
        image(c["axial"][0], 510, 400, 230, 230, rx=12, clip_id="clip-ct"),
        text(510, 680, "Post-implant CT", size=18, weight="bold"),
        text(510, 704, "NIfTI (.nii / .nii.gz)", size=14, fill=MUTED),
        '</g>',
        arrow(470, 260, 500, 260),
        arrow(770, 400, 815, 400),
    ]

    # 3 · VoxTool: real screenshots of v1.1.1 on the public sample CT.
    vx, vy, vw, vh = 830, 90, 700, 560
    sw, sh = c["slices"][1]
    parts += [
        f'<g id="panel-3-voxtool">',
        heading(vx, 60, 3, "VoxTool"),
        window(vx, vy, vw, vh, "VoxTool 1.1 · Slices"),
        image(c["slices"][0], vx + 10, vy + 40, vw - 20, vh - 50, preserve="xMidYMid meet"),
        window(vx + vw - 340, vy + vh - 250, 320, 290, "Electrode View"),
        image(c["cloud"][0], vx + vw - 330, vy + vh - 212, 300, 242, preserve="xMidYMid slice", rx=8, clip_id="clip-cloud"),
        chip(vx, vy + 600, 250, "Plan pre-fills leads (LLM)"),
        chip(vx, vy + 648, 250, "Click snaps to contact"),
        chip(vx, vy + 696, 250, "Fill in between ends"),
        text(vx + 270, vy + 625, "macOS · Windows desktop app", size=15, fill=MUTED),
        text(vx + 270, vy + 649, "Linux from source · web app", size=15, fill=MUTED),
        '</g>',
        arrow(1540, 400, 1580, 400),
    ]

    # 4 · Outputs.
    bw, bh = c["brain"][1]
    bwid = 380
    bhei = bwid * bh / bw
    parts += [
        f'<g id="panel-4-outputs">',
        heading(1590, 60, 4, "Outputs"),
        f'<rect x="1590" y="90" width="380" height="200" rx="12" fill="{PANEL}"/>',
        text(1610, 125, "Contact coordinates", size=18, weight="bold"),
        text(1610, 150, "voxel (i, j, k) · JSON or TXT", size=14, fill=MUTED),
        f'<text x="1610" y="190" font-family="Menlo, Courier New, monospace" font-size="15" fill="{INK}">'
        '<tspan x="1610">lead   #   i    j    k</tspan>'
        '<tspan x="1610" dy="24">LAMY   1   ·    ·    ·</tspan>'
        '<tspan x="1610" dy="24">LAMY   2   ·    ·    ·</tspan>'
        '<tspan x="1610" dy="24">…</tspan></text>',
        image(c["brain"][0], 1590, 330, bwid, bhei, preserve="xMidYMid meet"),
        text(1780, 330 + bhei + 24, "every contact on the brain", size=14, fill=MUTED, anchor="middle"),
        text(1780, 330 + bhei + 44, "(via iEEG-recon or similar)", size=14, fill=MUTED, anchor="middle"),
        '</g>',
    ]

    # 5 · Cloud and APIs, along the bottom.
    by = 900
    parts += [
        f'<g id="panel-5-cloud">',
        f'<rect x="40" y="{by - 40}" width="1930" height="300" rx="18" fill="{PANEL}"/>',
        heading(60, by, 5, "Share through the cloud"),
        cloud_shape(560, by + 140, 1.1),
        text(560, by + 160, "Cloud data", size=20, weight="bold", anchor="middle"),
        # Logos from each project's own GitHub repo; check brand rules before publishing.
        f'<rect x="780" y="{by + 40}" width="230" height="110" rx="14" fill="white" '
        f'stroke="#d5dbe4" stroke-width="2"/>',
        image("assets/logos/pennsieve-logo-full.png", 800, by + 75, 190, 40,
              preserve="xMidYMid meet"),
        f'<rect x="1040" y="{by + 40}" width="230" height="110" rx="14" fill="white" '
        f'stroke="#d5dbe4" stroke-width="2"/>',
        image("assets/logos/openneuro-brand-mark.png", 1056, by + 67, 56, 56,
              preserve="xMidYMid meet"),
        text(1120, by + 104, "OpenNeuro", size=23, weight="bold"),
        text(1025, by + 190, "open scans · save coordinates", size=16, fill=MUTED, anchor="middle"),
        f'<path d="M 1180 {by - 40} C 1180 {by - 90}, 1180 {by - 120}, 1180 {by - 150}" '
        f'stroke="{ACCENT}" stroke-width="4" fill="none" marker-end="url(#arrow)"/>',
        f'<path d="M 720 {by + 95} L 770 {by + 95}" stroke="{ACCENT}" stroke-width="4" '
        f'marker-end="url(#arrow)"/>',
        text(1210, by - 85, "API", size=30, weight="bold", fill=ACCENT),
        arrow(1300, by + 95, 1400, by + 95),
        text(1420, by + 85, "Downstream", size=20, weight="bold"),
        text(1420, by + 112, "iEEG-recon · MNE · other pipelines", size=16, fill=MUTED),
        text(60, by + 230, "Example data: MNE-Python sample sEEG subject (public, BSD-3). "
             "Screenshots: VoxTool 1.1.1.", size=14, fill=MUTED, italic=True),
        '</g>',
        '</svg>',
    ]
    svg = "\n".join(parts)
    svg_path = FIG / "fig1_v1.svg"
    svg_path.write_text(svg)
    cairosvg.svg2png(url=str(svg_path), write_to=str(FIG / "fig1_v1.png"), output_width=W * 2, unsafe=True)  # unsafe: allow linked local images
    print("wrote", svg_path, FIG / "fig1_v1.png")


if __name__ == "__main__":
    build()
