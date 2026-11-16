"""Figure 1 v2: four panels, less text, VoxTool and the brain as the two big images.

Run capture_labeled.py (and render_brain.py) first. Then:

    conda run -n voxfig python paper/figures/fig1/scripts/compose_fig1_v2.py
"""
import cairosvg

from compose_fig1 import (ACCENT, FIG, FONT, INK, MUTED, A, arrow, chip, crop, heading,
                          image, implant_plan, placeholder, text, window)


def make_crops():
    s = A / "screens"
    return {
        "app": crop(s / "labeled_app_slices.png", None, "v2_app_slices.png"),
        "cloud": crop(s / "labeled_cloud_nosidebar.png", (960, 610, 2240, 1700), "v2_cloud.png"),
        "axial": crop(s / "mne_slices_nosidebar.png", (720, 1070, 1597, 1945), "axial.png"),
        "brain": crop(A / "renders" / "brain_electrodes_lateral_left.png", None, "brain.png",
                      trim=True),
    }


def logo_card(x, y, w, h, inner):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="white" '
            f'stroke="#d5dbe4" stroke-width="2"/>' + inner)


ILLUSTRATION = FIG / "private" / "muki_implant_draft.png"  # BioRender free tier: no licence yet, so git-ignored


def implant_art():
    """Muki's draft illustration when it is on this machine, otherwise the placeholder."""
    if not ILLUSTRATION.exists():
        return [placeholder(40, 90, 330, 600, ["Illustration", "open craniotomy:",
                                               "ECoG grid on cortex,", "sEEG depth leads",
                                               "(BioRender / CC-licensed)"]),
                text(40, 725, "Leads are implanted, then", size=17, fill=MUTED),
                text(40, 748, "the patient gets a CT.", size=17, fill=MUTED)]
    w, h = 350, 350 * 504 / 720
    y = 390 - h / 2
    return [image("private/muki_implant_draft.png", 30, y, w, h, preserve="xMidYMid meet"),
            text(40, y + h + 40, "Leads are implanted, then", size=17, fill=MUTED),
            text(40, y + h + 63, "the patient gets a CT.", size=17, fill=MUTED),
            text(40, y + h + 95, "Draft art: Muki Gill (BioRender)", size=13, fill=MUTED, italic=True)]


def build():
    c = make_crops()
    W, H = 2000, 960
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        '<defs>'
        '<pattern id="hatch" width="14" height="14" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><rect width="14" height="14" fill="#f7f8fa"/>'
        '<line x1="0" y1="0" x2="0" y2="14" stroke="#e3e6ec" stroke-width="5"/></pattern>'
        f'<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker>'
        f'<marker id="arrow-acc" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{ACCENT}"/></marker>'
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">'
        '<feDropShadow dx="0" dy="6" stdDeviation="9" flood-opacity="0.22"/></filter>'
        '</defs>',
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]

    # 1 · Implant: the clinical scene, as one illustration.
    parts += [
        '<g id="panel-1-implant">',
        heading(40, 60, 1, "Implant"),
        *implant_art(),
        '</g>',
        arrow(380, 390, 415, 390),
    ]

    # 2 · Inputs: the plan and the CT.
    parts += [
        '<g id="panel-2-inputs">',
        heading(430, 60, 2, "Inputs"),
        implant_plan(430, 90, 230, 270),
        f'<rect x="446" y="406" width="214" height="214" rx="12" fill="#0b0d12"/>',
        image(c["axial"][0], 430, 390, 214, 214, rx=12, clip_id="clip-ct"),
        text(430, 652, "Post-implant CT", size=18, weight="bold"),
        text(430, 676, "Bone and metal show bright;", size=15, fill=MUTED),
        text(430, 697, "contacts brightest of all.", size=15, fill=MUTED),
        '</g>',
        arrow(670, 390, 705, 390),
    ]

    # 3 · VoxTool: the real app with all 119 sample contacts loaded.
    vx, vy, vw = 720, 90, 780
    aw, ah = c["app"][1]
    vh = vw * ah / aw + 40
    parts += [
        '<g id="panel-3-voxtool">',
        heading(vx, 60, 3, "Label in VoxTool"),
        window(vx, vy, vw, vh, "VoxTool 1.1"),
        image(c["app"][0], vx + 8, vy + 34, vw - 16, vh - 42, preserve="xMidYMid meet"),
        window(vx + vw - 300, vy + vh - 150, 290, 260, "Electrode View"),
        image(c["cloud"][0], vx + vw - 292, vy + vh - 114, 274, 216, rx=8, clip_id="clip-cloud"),
        chip(vx, vy + vh + 30, 230, "Plan pre-fills leads"),
        chip(vx + 245, vy + vh + 30, 210, "Clicks snap to metal"),
        '</g>',
    ]

    # Cloud strip under VoxTool: API to Pennsieve and OpenNeuro.
    sy = 790
    parts += [
        '<g id="strip-cloud">',
        # Two-way: scans come in from the cloud, coordinates go back out.
        f'<path d="M {vx + 120} {vy + vh + 88} L {vx + 120} {sy + 52}" stroke="{ACCENT}" '
        f'stroke-width="4" fill="none" marker-start="url(#arrow-acc)" marker-end="url(#arrow-acc)"/>',
        text(vx + 135, sy + 10, "API", size=26, weight="bold", fill=ACCENT),
        logo_card(vx + 200, sy + 20, 200, 80,
                  image("assets/logos/pennsieve-logo-full.png", vx + 215, sy + 43, 170, 36,
                        preserve="xMidYMid meet")),
        logo_card(vx + 420, sy + 20, 200, 80,
                  image("assets/logos/openneuro-brand-mark.png", vx + 432, sy + 37, 46, 46,
                        preserve="xMidYMid meet")
                  + text(vx + 486, sy + 69, "OpenNeuro", size=20, weight="bold")),
        text(vx + 640, sy + 56, "open scans,", size=16, fill=MUTED),
        text(vx + 640, sy + 78, "save coordinates", size=16, fill=MUTED),
        '</g>',
        arrow(1510, 390, 1545, 390),
    ]

    # 4 · Result: every contact on the brain.
    bw, bh = c["brain"][1]
    bwid = 420
    bhei = bwid * bh / bw
    parts += [
        '<g id="panel-4-result">',
        heading(1555, 60, 4, "Result"),
        image(c["brain"][0], 1550, 170, bwid, bhei, preserve="xMidYMid meet"),
        text(1760, 170 + bhei + 40, "119 contacts · 15 leads", size=22, weight="bold",
             anchor="middle"),
        text(1760, 170 + bhei + 68, "voxel coordinates (JSON / TXT)", size=16, fill=MUTED,
             anchor="middle"),
        arrow(1650, 170 + bhei + 110, 1690, 170 + bhei + 110),
        text(1700, 170 + bhei + 116, "iEEG-recon, MNE, …", size=18, weight="bold"),
        '</g>',
        text(40, H - 30, "Example data: MNE-Python sample sEEG subject (public, BSD-3), "
             "labeled in VoxTool 1.1.1.", size=14, fill=MUTED, italic=True),
        '</svg>',
    ]
    svg_path = FIG / "fig1_v2.svg"
    svg_path.write_text("\n".join(parts))
    cairosvg.svg2png(url=str(svg_path), write_to=str(FIG / "fig1_v2.png"), output_width=W * 2,
                     unsafe=True)  # unsafe: allow linked local images
    print("wrote", svg_path, FIG / "fig1_v2.png")


if __name__ == "__main__":
    build()
