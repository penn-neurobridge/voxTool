"""Turn the figure SVGs into files that import into Figma as editable layers.

The compose scripts write SVGs that render correctly in browsers and cairosvg but
lean on features Figma's importer drops or mangles. This rewrites each one:

- Images: the SVGs link PNGs by relative path, which Figma cannot follow. Each
  is embedded as a data URI, downscaled to at most 2x its size on the page
  (and 4096 px, Figma's limit) to keep files small.
- Arrowheads: drawn with <marker>, which Figma ignores. Each becomes a plain
  triangle you can select and move.
- Hatched placeholders: a <pattern> fill becomes a flat grey.
- Fonts: Helvetica and Menlo are not available to everyone in Figma, so text
  uses Inter and JetBrains Mono (both in Figma for all users). Inter is a
  little wider than Helvetica, so each label's size is reduced just enough to
  keep its original width; nothing overflows its box.
- Centred and right-aligned text is converted to left-aligned at the measured
  position, because Figma places text-anchor text unreliably.
- Multi-line <tspan> text becomes one text layer per line.

Groups and their ids are kept, so panels arrive as named layers.

    conda run -n voxfig python paper/figures/make_figma_svgs.py [--fonts DIR]

--fonts points at a folder with Inter-{Regular,Bold,Italic,BoldItalic}.ttf
(rsms/inter, OFL), used only to measure text. Writes paper/figures/figma/.
"""
import argparse
import base64
import copy
import io
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageFont

FIGS = Path(__file__).resolve().parent
OUT = FIGS / "figma"
FIGURES = ["fig1/fig1_v2.svg", "fig1/fig1_v1.svg", "fig2/fig2_v1.svg", "fig3/fig3_v1.svg",
           "fig4/fig4_v1.svg", "fig5/fig5_v1.svg"]

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
XML = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)
Q = lambda tag: f"{{{SVG}}}{tag}"  # noqa: E731

SANS, MONO = "Inter", "JetBrains Mono"
HELVETICA = "/System/Library/Fonts/Helvetica.ttc"  # faces: 0 regular, 1 bold, 2 oblique, 3 bold oblique
MAX_PX = 4096
HATCH_FILL = "#f4f5f8"


class Measure:
    """Text widths in the original font and in its Figma replacement."""

    def __init__(self, inter_dir):
        self.inter = {(b, i): str(Path(inter_dir) / f"Inter-{n}.ttf") for (b, i), n in {
            (False, False): "Regular", (True, False): "Bold",
            (False, True): "Italic", (True, True): "BoldItalic"}.items()}
        self._cache = {}

    def _font(self, which, size, bold, italic):
        key = (which, round(size * 4), bold, italic)
        if key not in self._cache:
            if which == "inter":
                self._cache[key] = ImageFont.truetype(self.inter[(bold, italic)], size)
            else:
                self._cache[key] = ImageFont.truetype(HELVETICA, size, index=int(bold) + 2 * int(italic))
        return self._cache[key]

    def width(self, runs, which):
        """runs: [(text, size, bold, italic, mono)] -> width in px."""
        w = 0.0
        for s, size, bold, italic, mono in runs:
            if mono:
                w += 0.6 * size * len(s)  # Menlo and JetBrains Mono are both 0.6 em
            else:
                w += self._font(which, size, bold, italic).getlength(s)
        return w


def style_of(el, inherited):
    st = dict(inherited)
    for k in ("font-family", "font-size", "font-weight", "font-style", "fill", "text-anchor"):
        if el.get(k) is not None:
            st[k] = el.get(k)
    return st


def runs_of(text_el):
    """The text's runs with their effective size/weight/style, in order."""
    base = style_of(text_el, {"font-size": "16", "font-weight": "normal", "font-style": "normal",
                              "font-family": ""})
    out = []

    def add(s, st):
        if s:
            out.append((s, float(st["font-size"]), st["font-weight"] in ("bold", "700"),
                        st["font-style"] == "italic", "mono" in st["font-family"].lower()
                        or "menlo" in st["font-family"].lower()))

    add(text_el.text, base)
    for ts in text_el:
        st = style_of(ts, base)
        add(ts.text, st)
        add(ts.tail, base)
    return out


def map_family(fam):
    f = (fam or "").lower()
    return MONO if ("mono" in f or "menlo" in f or "courier" in f) else SANS


def split_multiline(parent):
    """<text><tspan x= dy=>…</tspan>…</text> -> one <text> per line."""
    for i, el in list(enumerate(parent)):
        if el.tag == Q("text") and any(ts.get("dy") or ts.get("y") for ts in el):
            y = float(el.get("y"))
            pieces = []
            for ts in el:
                y = float(ts.get("y")) if ts.get("y") else y + float(ts.get("dy") or 0)
                line = copy.deepcopy(el)
                for ch in list(line):
                    line.remove(ch)
                line.text = ts.text
                line.set("x", ts.get("x") or el.get("x"))
                line.set("y", f"{y:g}")
                pieces.append(line)
            idx = list(parent).index(el)
            parent.remove(el)
            for k, line in enumerate(pieces):
                parent.insert(idx + k, line)
        elif len(el):
            split_multiline(el)


def fix_text(el, measure, stats):
    runs = runs_of(el)
    if not runs:
        return
    old_w = measure.width(runs, "helvetica")
    new_w = measure.width(runs, "inter")
    scale = 1.0
    if not all(r[4] for r in runs) and new_w > old_w > 0:
        scale = old_w / new_w
        for node in [el, *el]:
            if node.get("font-size"):
                node.set("font-size", f"{math.floor(float(node.get('font-size')) * scale * 4) / 4:g}")
        stats["resized"] += 1
    fam = map_family(el.get("font-family"))
    el.set("font-family", fam)
    for ts in el:
        if ts.get("font-family"):
            ts.set("font-family", map_family(ts.get("font-family")))
        ts.attrib.pop("baseline-shift", None)  # Figma ignores it; keep the text, drop the shift
    # Column-aligned text (xml:space="preserve") relies on runs of spaces, which
    # importers collapse; non-breaking spaces have the same width and survive.
    if el.get(f"{{{XML}}}space") == "preserve":
        for node in [el, *el]:
            if node.text:
                node.text = re.sub(r" {2,}", lambda m: " " * len(m.group()), node.text)
    anchor = el.attrib.pop("text-anchor", "start")
    if anchor in ("middle", "end"):
        w = measure.width(runs_of(el), "inter")
        x = float(el.get("x"))
        el.set("x", f"{x - (w / 2 if anchor == 'middle' else w):.1f}")
        stats["anchored"] += 1
    # Figma treats an explicit start anchor fine; leaving none is cleanest.


def path_ends(d):
    """(start, direction at start, end, direction at end) for M/L/C/l/h/v/z-free paths."""
    toks = re.findall(r"[MLCmlc]|-?\d*\.?\d+(?:e-?\d+)?", d)
    pts, cmd, cur, i = [], None, (0.0, 0.0), 0
    while i < len(toks):
        if toks[i] in "MLCmlc":
            cmd = toks[i]
            i += 1
            continue
        n = 6 if cmd in "Cc" else 2
        vals = [float(t) for t in toks[i:i + n]]
        i += n
        if cmd.islower():
            vals = [v + (cur[k % 2]) for k, v in enumerate(vals)]
        for k in range(0, n, 2):
            pts.append((vals[k], vals[k + 1]))
        cur = (vals[-2], vals[-1])
    return pts[0], pts[1], pts[-1], pts[-2]


def arrowhead(tip_at, from_pt, stroke_w, fill):
    """The marker's triangle (viewBox 0..10, refX 8, markerWidth 5) as a polygon."""
    dx, dy = tip_at[0] - from_pt[0], tip_at[1] - from_pt[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    s = 0.5 * stroke_w  # markerWidth / viewBox width, in stroke widths
    tip = (tip_at[0] + 2 * s * ux, tip_at[1] + 2 * s * uy)
    base = (tip_at[0] - 8 * s * ux, tip_at[1] - 8 * s * uy)
    a = (base[0] - 5 * s * uy, base[1] + 5 * s * ux)
    b = (base[0] + 5 * s * uy, base[1] - 5 * s * ux)
    el = ET.Element(Q("polygon"), {
        "points": " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in (tip, a, b)), "fill": fill})
    return el


def fix_arrows(parent, markers, stats):
    for el in list(parent):
        if len(el):
            fix_arrows(el, markers, stats)
        ms, me = el.attrib.pop("marker-start", None), el.attrib.pop("marker-end", None)
        if not (ms or me):
            continue
        sw = float(el.get("stroke-width", 1))
        if el.tag == Q("line"):
            p0 = (float(el.get("x1")), float(el.get("y1")))
            p1 = (float(el.get("x2")), float(el.get("y2")))
            s0, s1, e0, e1 = p0, p1, p1, p0
        else:
            s0, s1, e0, e1 = path_ends(el.get("d"))
        idx = list(parent).index(el) + 1
        for ref, tip_at, from_pt in ((me, e0, e1), (ms, s0, s1)):
            if not ref:
                continue
            mid = re.search(r"#([^)]+)", ref).group(1)
            fill, orient = markers[mid]
            if ref is ms and orient != "auto-start-reverse":
                tip_at, from_pt = s0, (2 * s0[0] - s1[0], 2 * s0[1] - s1[1])  # points along the path
            parent.insert(idx, arrowhead(tip_at, from_pt, sw, fill))
            stats["arrows"] += 1


def embed_images(root, src_dir, stats):
    for el in root.iter(Q("image")):
        href = el.get(f"{{{XLINK}}}href") or el.get("href")
        if not href or href.startswith("data:"):
            continue
        path = (src_dir / href).resolve()
        im = Image.open(path)
        im.load()
        w, h = float(el.get("width")), float(el.get("height"))
        target = min(MAX_PX, 2 * max(w, h))
        factor = min(1.0, target / max(im.size))
        if factor < 1.0:
            im = im.resize((round(im.width * factor), round(im.height * factor)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        el.set("href", uri)
        el.set(f"{{{XLINK}}}href", uri)
        stats["images"] += 1


def convert(rel, measure):
    src = FIGS / rel
    tree = ET.parse(src)
    root = tree.getroot()
    stats = {"images": 0, "arrows": 0, "resized": 0, "anchored": 0}

    markers = {}
    for m in root.iter(Q("marker")):
        shape = next(iter(m))
        markers[m.get("id")] = (shape.get("fill", "#000"), m.get("orient", "auto"))

    embed_images(root, src.parent, stats)
    fix_arrows(root, markers, stats)
    split_multiline(root)
    for el in root.iter():
        if el.get("fill", "").startswith("url(#hatch"):
            el.set("fill", HATCH_FILL)
    for el in list(root.iter(Q("text"))):
        fix_text(el, measure, stats)
    for defs in root.iter(Q("defs")):
        for child in list(defs):
            if child.tag in (Q("marker"), Q("pattern")):
                defs.remove(child)

    OUT.mkdir(exist_ok=True)
    dst = OUT / (src.stem + "_figma.svg")
    tree.write(dst, encoding="utf-8", xml_declaration=True)
    mb = dst.stat().st_size / 1e6
    print(f"{dst.name}: {stats['images']} images embedded, {stats['arrows']} arrowheads, "
          f"{stats['anchored']} labels re-anchored, {stats['resized']} resized to fit; {mb:.1f} MB")
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True, help="folder with Inter-Regular.ttf etc.")
    args = ap.parse_args()
    m = Measure(args.fonts)
    for rel in FIGURES:
        convert(rel, m)
