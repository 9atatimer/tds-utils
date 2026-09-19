#!/usr/bin/env python3
"""Draw the chores-monitor menu-bar icons: chores-quiet.png (template) and
chores-alert.png (explicit red). Same rule as skills-drift-icons.py: two
DIFFERENT shapes, not two colors, so the state reads with no color vision.

  quiet: a broom -- a thick diagonal handle and a fan of bristles; rendered
         TEMPLATE so macOS tints it to the menu bar (nothing to say).
  alert: a filled warning triangle with a cut-out exclamation mark in red.

Regenerate only when changing the artwork:

    uv run --with pillow python chores/assets/chores-icons.py
"""

import pathlib

from PIL import Image, ImageDraw

MASTER = 256
OUT_SIZE = 64
BLACK = (0, 0, 0, 255)
RED = (220, 38, 38, 255)
CLEAR = (0, 0, 0, 0)


def draw_quiet() -> Image.Image:
    img = Image.new("RGBA", (MASTER, MASTER), CLEAR)
    d = ImageDraw.Draw(img)
    s = MASTER
    # handle: thick diagonal from top-right to lower-left
    d.line(
        [(0.82 * s, 0.10 * s), (0.42 * s, 0.56 * s)], fill=BLACK, width=int(0.11 * s)
    )
    # head: a fat trapezoid at the end of the handle
    d.polygon(
        [
            (0.46 * s, 0.50 * s),
            (0.30 * s, 0.62 * s),
            (0.10 * s, 0.92 * s),
            (0.52 * s, 0.92 * s),
            (0.58 * s, 0.62 * s),
        ],
        fill=BLACK,
    )
    # bristle gaps cut through to transparent, so the head reads as a broom
    for x in (0.24, 0.36, 0.48):
        d.line(
            [(x * s, 0.74 * s), ((x - 0.03) * s, 0.92 * s)],
            fill=CLEAR,
            width=int(0.035 * s),
        )
    return img.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)


def draw_alert() -> Image.Image:
    img = Image.new("RGBA", (MASTER, MASTER), CLEAR)
    d = ImageDraw.Draw(img)
    s = MASTER
    d.polygon(
        [(0.50 * s, 0.06 * s), (0.96 * s, 0.90 * s), (0.04 * s, 0.90 * s)], fill=RED
    )
    d.rounded_rectangle(
        [0.44 * s, 0.32 * s, 0.56 * s, 0.64 * s], radius=int(0.04 * s), fill=CLEAR
    )
    d.ellipse([0.43 * s, 0.70 * s, 0.57 * s, 0.84 * s], fill=CLEAR)
    return img.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)


def main() -> None:
    here = pathlib.Path(__file__).resolve().parent
    draw_quiet().save(here / "chores-quiet.png")
    draw_alert().save(here / "chores-alert.png")
    print("wrote chores-quiet.png and chores-alert.png")


if __name__ == "__main__":
    main()
