"""Generate the VoxTool app icon.

Kept as a script rather than a checked-in binary blob so the mark can be
regenerated if the palette changes. Writes desktop/build/icon.png, which
electron-builder converts to .icns and .ico at package time.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
BG = (14, 16, 26)
CLOUD = (150, 162, 178)
LEAD = (31, 184, 76)      # LEAD_PALETTE_HEX[0]
PICK = (255, 31, 122)     # PICK_COLOR

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    return m


def main():
    img = Image.new("RGB", (SIZE, SIZE), BG)
    d = ImageDraw.Draw(img)
    rnd = random.Random(11)

    cx, cy = SIZE * 0.5, SIZE * 0.54
    rx, ry = SIZE * 0.33, SIZE * 0.30

    # Skull-like arc of cloud points: dense band, slightly jittered.
    for _ in range(2600):
        t = rnd.uniform(math.radians(200), math.radians(520))
        jitter = rnd.gauss(0, SIZE * 0.011)
        x = cx + (rx + jitter) * math.cos(t)
        y = cy + (ry + jitter) * math.sin(t)
        r = rnd.uniform(2.5, 5.5)
        shade = rnd.randint(-25, 25)
        col = tuple(max(0, min(255, c + shade)) for c in CLOUD)
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)

    # A depth electrode running through the volume: contacts as filled dots.
    x0, y0 = SIZE * 0.24, SIZE * 0.70
    x1, y1 = SIZE * 0.76, SIZE * 0.34
    n = 7
    r = SIZE * 0.042
    contacts = []
    for i in range(n):
        f = i / (n - 1)
        contacts.append(
            (
                x0 + (x1 - x0) * f,
                y0 + (y1 - y0) * f,
                PICK if i == n - 1 else LEAD,
            )
        )

    # Build every glow on one layer first: blending per-dot would dim the dots
    # already drawn, fading the lead from one end to the other.
    glow = Image.new("RGB", (SIZE, SIZE), BG)
    gd = ImageDraw.Draw(glow)
    for x, y, colour in contacts:
        gd.ellipse([x - r * 1.8, y - r * 1.8, x + r * 1.8, y + r * 1.8], fill=colour)
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(SIZE * 0.022)), 0.30)

    d = ImageDraw.Draw(img)
    for x, y, colour in contacts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=colour)

    os.makedirs(OUT, exist_ok=True)
    img.putalpha(rounded_mask(SIZE, int(SIZE * 0.22)))
    img.save(os.path.join(OUT, "icon.png"))
    print("wrote", os.path.join(OUT, "icon.png"))


if __name__ == "__main__":
    main()
