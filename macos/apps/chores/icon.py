#!/usr/bin/env python3
"""Draw the Chores Dock icon: a broom on a rounded gradient tile.

Regenerates icon.icns, which is committed so installing the app needs no
Python. Pillow writes ICNS directly, so this runs on any platform:

    uv run --with pillow python macos/apps/chores/icon.py

Kept deliberately blunt -- a solid silhouette. Anything finer turns to mush
at the 16px Finder size (the rule flip-monitor/icon.py established).
"""

import pathlib

from PIL import Image, ImageDraw

MASTER = 1024
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)
GRADIENT_TOP = (240, 160, 40)
GRADIENT_BOTTOM = (176, 96, 16)
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def tile(size: int) -> Image.Image:
    column = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        column.putpixel(
            (0, y),
            tuple(int(GRADIENT_TOP[i] * (1 - t) + GRADIENT_BOTTOM[i] * t) for i in range(3)),
        )
    gradient = column.resize((size, size)).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=255)
    out = Image.new("RGBA", (size, size), CLEAR)
    out.paste(gradient, (0, 0), mask)
    return out


def broom(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), CLEAR)
    d = ImageDraw.Draw(img)
    s = size
    d.line([(0.78 * s, 0.16 * s), (0.44 * s, 0.56 * s)], fill=WHITE, width=int(0.10 * s))
    d.polygon(
        [(0.48 * s, 0.50 * s), (0.30 * s, 0.62 * s), (0.14 * s, 0.88 * s),
         (0.54 * s, 0.88 * s), (0.60 * s, 0.62 * s)],
        fill=WHITE,
    )
    for x in (0.27, 0.38, 0.49):
        d.line([(x * s, 0.72 * s), ((x - 0.03) * s, 0.88 * s)], fill=CLEAR, width=int(0.03 * s))
    return img


def main() -> None:
    master = tile(MASTER)
    master.alpha_composite(broom(MASTER))
    here = pathlib.Path(__file__).resolve().parent
    master.save(
        here / "icon.icns", format="ICNS",
        sizes=[(n, n) for n in ICNS_SIZES],
    )
    print("wrote icon.icns")


if __name__ == "__main__":
    main()
