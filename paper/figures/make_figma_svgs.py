"""Turn the figure SVGs into files that import into Figma as editable layers.

The compose scripts write SVGs that render correctly in browsers and cairosvg but
lean on features Figma's importer drops or mangles. This rewrites each one:

- Layers: plain <g> groups are unwrapped, so every label, box and picture is
  its own layer instead of part of a panel you have to double-click into.
- Images: the SVGs link PNGs by relative path, which Figma cannot follow. Each
  becomes a rectangle whose fill is the picture (embedded, downscaled to at
  most 2x its size on the page and 4096 px), the form Figma itself exports, so
  it is one layer with editable corners rather than an image inside a mask.
- Arrows: drawn with <marker>, which Figma ignores. Each becomes a group named
  "arrow" (its line and a triangle head), selected and moved as one.
- Drop shadows: rewritten as the filter chain Figma writes, so they come back
  as an editable Drop shadow effect.
- Hatched placeholders: a <pattern> fill becomes a flat grey.
- Fonts: Helvetica and Menlo are not available to everyone in Figma, so text
  uses Inter and JetBrains Mono (both in Figma for all users). Inter is a
  little wider than Helvetica, so each label's size is reduced just enough to
  keep its original width; nothing overflows its box.
- Centred and right-aligned text is converted to left-aligned at the measured
  position, because Figma places text-anchor text unreliably.
- Multi-line <tspan> text becomes one text layer per line.

Pictures are named after their source file.

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
    """Each marker arrow becomes one group named "arrow": its line plus a triangle."""
    for el in list(parent):
        if el.tag == Q("g") and el.get("id", "").startswith("arrow"):
            continue
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
        group = ET.Element(Q("g"), {"id": "arrow" if not ms else "double arrow"})
        idx = list(parent).index(el)
        parent.remove(el)
        group.append(el)
        for ref, tip_at, from_pt in ((me, e0, e1), (ms, s0, s1)):
            if not ref:
                continue
            mid = re.search(r"#([^)]+)", ref).group(1)
            fill, orient = markers[mid]
            if ref is ms and orient != "auto-start-reverse":
                tip_at, from_pt = s0, (2 * s0[0] - s1[0], 2 * s0[1] - s1[1])  # points along the path
            group.append(arrowhead(tip_at, from_pt, sw, fill))
        parent.insert(idx, group)
        stats["arrows"] += 1


def flatten_groups(parent):
    """Unwrap plain <g> so every shape, label and image is its own layer in Figma.

    Groups that carry a transform, clip, mask or filter are kept (unwrapping
    them would change what is drawn).
    """
    for el in list(parent):
        if el.tag == Q("g") and len(el):
            flatten_groups(el)
            keep = any(el.get(k) for k in ("transform", "clip-path", "mask", "filter"))
            if not keep:
                idx = list(parent).index(el)
                parent.remove(el)
                for k, ch in enumerate(list(el)):
                    parent.insert(idx + k, ch)


def _png_data_uri(path, display_w, display_h):
    im = Image.open(path)
    im.load()
    target = min(MAX_PX, 2 * max(display_w, display_h))
    factor = min(1.0, target / max(im.size))
    if factor < 1.0:
        im = im.resize((round(im.width * factor), round(im.height * factor)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), im.size


def images_to_fills(root, src_dir, defs, stats):
    """<image> -> a rectangle with the picture as its fill, the way Figma itself
    exports images, so each arrives as one layer with editable corners and
    crop instead of a mask group."""
    clips = {c.get("id"): c for c in root.iter(Q("clipPath"))}
    used_clips = set()

    def walk(parent):
        for el in list(parent):
            if len(el):
                walk(el)
            if el.tag != Q("image"):
                continue
            href = el.get(f"{{{XLINK}}}href") or el.get("href")
            x, y = float(el.get("x", 0)), float(el.get("y", 0))
            w, h = float(el.get("width")), float(el.get("height"))
            uri, (iw, ih) = _png_data_uri((src_dir / href).resolve(), w, h)
            mode = (el.get("preserveAspectRatio") or "xMidYMid meet").split()[-1]
            if mode == "slice":
                sc = max(w / iw, h / ih)
                ox, oy = (w - iw * sc) / 2, (h - ih * sc) / 2
                rx_, ry_, rw, rh = x, y, w, h
                matrix = f"matrix({sc / w:.8g} 0 0 {sc / h:.8g} {ox / w:.8g} {oy / h:.8g})"
            else:  # meet: shrink the rectangle to the picture itself
                sc = min(w / iw, h / ih)
                rw, rh = iw * sc, ih * sc
                rx_, ry_ = x + (w - rw) / 2, y + (h - rh) / 2
                matrix = f"matrix({1 / iw:.8g} 0 0 {1 / ih:.8g} 0 0)"
            n = stats["images"]
            stats["images"] += 1
            pat = ET.SubElement(defs, Q("pattern"), {
                "id": f"img-fill-{n}", "patternContentUnits": "objectBoundingBox",
                "width": "1", "height": "1"})
            ET.SubElement(pat, Q("use"), {f"{{{XLINK}}}href": f"#img-{n}", "transform": matrix})
            ET.SubElement(defs, Q("image"), {"id": f"img-{n}", "width": str(iw), "height": str(ih),
                                             f"{{{XLINK}}}href": uri})
            rect = ET.Element(Q("rect"), {
                "id": Path(href).stem.replace("_", " "),
                "x": f"{rx_:.2f}", "y": f"{ry_:.2f}", "width": f"{rw:.2f}", "height": f"{rh:.2f}",
                "fill": f"url(#img-fill-{n})"})
            clip_ref = el.get("clip-path")
            if clip_ref:
                cid = re.search(r"#([^)]+)", clip_ref).group(1)
                shape = next(iter(clips[cid]))
                if shape.get("rx"):
                    rect.set("rx", shape.get("rx"))
                used_clips.add(cid)
            idx = list(parent).index(el)
            parent.remove(el)
            parent.insert(idx, rect)

    walk(root)

    def drop_clips(parent):
        for el in list(parent):
            if el.tag == Q("clipPath") and el.get("id") in used_clips:
                parent.remove(el)
            elif len(el):
                drop_clips(el)

    drop_clips(root)


def figma_shadow(root):
    """feDropShadow -> the filter chain Figma writes for a drop shadow, which it
    reads back as an editable Drop shadow effect."""
    for f in root.iter(Q("filter")):
        ds = f.find(Q("feDropShadow"))
        if ds is None:
            continue
        dx, dy = ds.get("dx", "0"), ds.get("dy", "0")
        sd, op = ds.get("stdDeviation", "4"), ds.get("flood-opacity", "0.25")
        for ch in list(f):
            f.remove(ch)
        f.set("color-interpolation-filters", "sRGB")
        steps = [
            ("feFlood", {"flood-opacity": "0", "result": "BackgroundImageFix"}),
            ("feColorMatrix", {"in": "SourceAlpha", "type": "matrix", "result": "hardAlpha",
                               "values": "0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"}),
            ("feOffset", {"dx": dx, "dy": dy}),
            ("feGaussianBlur", {"stdDeviation": sd}),
            ("feColorMatrix", {"type": "matrix",
                               "values": f"0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 {op} 0"}),
            ("feBlend", {"mode": "normal", "in2": "BackgroundImageFix",
                         "result": "effect1_dropShadow"}),
            ("feBlend", {"mode": "normal", "in": "SourceGraphic", "in2": "effect1_dropShadow",
                         "result": "shape"}),
        ]
        for tag, attrs in steps:
            ET.SubElement(f, Q(tag), attrs)


def convert(rel, measure):
    src = FIGS / rel
    tree = ET.parse(src)
    root = tree.getroot()
    stats = {"images": 0, "arrows": 0, "resized": 0, "anchored": 0}

    markers = {}
    for m in root.iter(Q("marker")):
        shape = next(iter(m))
        markers[m.get("id")] = (shape.get("fill", "#000"), m.get("orient", "auto"))

    defs = root.find(Q("defs"))
    if defs is None:
        defs = ET.Element(Q("defs"))
        root.insert(0, defs)
    flatten_groups(root)
    images_to_fills(root, src.parent, defs, stats)
    fix_arrows(root, markers, stats)
    figma_shadow(root)
    split_multiline(root)
    for el in root.iter():
        if el.get("fill", "").startswith("url(#hatch"):
            el.set("fill", HATCH_FILL)
    for el in list(root.iter(Q("text"))):
        fix_text(el, measure, stats)
    for defs in root.iter(Q("defs")):
        for child in list(defs):
            if child.tag == Q("marker") or (child.tag == Q("pattern") and child.get("id") == "hatch"):
                defs.remove(child)

    OUT.mkdir(exist_ok=True)
    dst = OUT / (src.stem + "_figma.svg")
    tree.write(dst, encoding="utf-8", xml_declaration=True)
    mb = dst.stat().st_size / 1e6
    print(f"{dst.name}: {stats['images']} images as fills, {stats['arrows']} arrows, "
          f"{stats['anchored']} labels re-anchored, {stats['resized']} resized to fit; {mb:.1f} MB")
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True, help="folder with Inter-Regular.ttf etc.")
    args = ap.parse_args()
    m = Measure(args.fonts)
    for rel in FIGURES:
        convert(rel, m)
