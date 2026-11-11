"""Make an example implant plan (PDF) for the public MNE sample, as tutorial input.

The sample ships no surgical plan, so this builds one from what it does ship:
the recorded channels (lead names, contacts) and, as the target, the atlas
region at each lead's deepest contact (fig5/assets/contact_labels.json). The
page says on its face that it was made for the tutorial.

    conda run -n voxfig python paper/figures/fig4/scripts/make_plan.py
"""
import json
import re
from collections import OrderedDict
from pathlib import Path

import cairosvg
import mne

MISC = Path.home() / "mne_data" / "dl" / "mne-misc-data-0.30" / "seeg"
FIGS = Path(__file__).resolve().parents[2]
LABELS = FIGS / "fig5" / "assets" / "contact_labels.json"
OUT = FIGS / "fig4" / "assets"
FONT = "Helvetica, Arial, sans-serif"


def region(names):
    for n in names:
        if n == "Unknown" or "White-Matter" in n:
            continue
        n = n.replace("ctx-lh-", "L ").replace("ctx-rh-", "R ")
        return n.replace("Left-", "L ").replace("Right-", "R ")
    return "white matter"


def main():
    raw = mne.io.read_raw_fif(MISC / "sample_seeg_ieeg.fif", verbose="error")
    leads = OrderedDict()
    for ch in raw.ch_names:
        m = re.match(r"([A-Za-z']+)\s*(\d+)", ch)
        leads.setdefault(m.group(1), []).append(int(m.group(2)))
    labels = json.loads(LABELS.read_text())

    W, H = 816, 1056  # US letter at 96 dpi
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         f'<rect width="{W}" height="{H}" fill="white"/>']

    def t(x, y, s, size=13, weight="normal", fill="#111", anchor="start", mono=False):
        fam = "Menlo, Courier New, monospace" if mono else FONT
        p.append(f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" '
                 f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>')

    t(60, 70, "Stereo-EEG implant plan", size=24, weight="bold")
    t(60, 96, "Example made for the VoxTool tutorial from the public MNE sample_seeg subject.",
      size=12, fill="#555")
    t(60, 114, "Not a clinical document. Targets = atlas region at each lead's deepest contact.",
      size=12, fill="#555")

    y = 160
    t(60, y, "Lead", weight="bold"); t(170, y, "Contacts", weight="bold")
    t(270, y, "Target", weight="bold")
    p.append(f'<line x1="60" y1="{y + 8}" x2="756" y2="{y + 8}" stroke="#999"/>')
    for name, nums in leads.items():
        y += 26
        deepest = labels.get(name, {}).get(f"{name} {min(nums)}") or ["Unknown"]
        t(60, y, name); t(170, y, str(len(nums))); t(270, y, region(deepest))
        p.append(f'<line x1="60" y1="{y + 8}" x2="756" y2="{y + 8}" stroke="#e5e5e5"/>')

    y += 60
    t(60, y, "Amplifier channel map", size=16, weight="bold")
    y += 10
    tokens = [f"{name}{n}" for name, nums in leads.items() for n in nums]
    per_row = 10
    for r in range(0, len(tokens), per_row):
        y += 20
        for c, tok in enumerate(tokens[r:r + per_row]):
            t(60 + c * 70, y, tok, size=11, mono=True)
    p.append("</svg>")

    OUT.mkdir(parents=True, exist_ok=True)
    svg = "\n".join(p)
    (OUT / "example_implant_plan.svg").write_text(svg)
    cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(OUT / "example_implant_plan.pdf"))
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(OUT / "example_implant_plan.png"),
                     output_width=W * 2)
    print(len(leads), "leads,", len(tokens), "channels ->", OUT / "example_implant_plan.pdf")


if __name__ == "__main__":
    main()
