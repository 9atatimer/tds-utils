#!/usr/bin/env python3
"""Draw the skills-drift-monitor menu-bar icons: skills-current.png (quiet,
template) and skills-drift.png (alert, full-color).

Regenerates both PNGs, which are committed so running the monitor needs no
Pillow. Run this only when changing the artwork:

    uv run --with pillow python assets/skills-drift-icons.py

Two DIFFERENT shapes, not just two colors -- a colorblind viewer must be
able to tell them apart with no color perception at all (see
docs/design/LMDE.DESIGN.md's skills-drift section for the rationale):

  current: a plain rounded badge outline, rendered TEMPLATE (macOS tints it
           to match the menu bar; quiet by design -- nothing to say).
  drift:   a filled warning triangle with a cut-out exclamation mark,
           rendered in explicit red (NOT template) -- shape AND color both
           say "stop", so the signal survives even without color vision.

Kept deliberately blunt, same rule flip-monitor/icon.py uses: a status item
renders at ~18-22pt, so anything finer than a thick outline turns to mush.
"""

import pathlib

from PIL import Image, ImageDraw

MASTER = 256  # downsampled for the menu bar; kept large enough to stay crisp on Retina
OUT_SIZE = 64  # final PNG edge

BLACK = (0, 0, 0, 255)
RED = (220, 38, 38, 255)  # a single, unambiguous "stop" red -- see LMDE.DESIGN.md


def draw_current() -> Image.Image:
    """A plain rounded badge outline. Template-rendered, so only the alpha
    channel matters -- fill color here is irrelevant, kept black for clarity
    while editing."""
    img = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = MASTER
    draw.rounded_rectangle(
        [0.12 * s, 0.22 * s, 0.88 * s, 0.78 * s],
        radius=0.14 * s,
        outline=BLACK,
        width=int(0.11 * s),
    )
    return img


def draw_drift() -> Image.Image:
    """A filled warning triangle with a cut-out exclamation mark, solid red.
    NOT template -- the color must survive as-is, it is half the signal."""
    img = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = MASTER
    draw.polygon(
        [(0.5 * s, 0.06 * s), (0.95 * s, 0.90 * s), (0.05 * s, 0.90 * s)],
        fill=RED,
    )
    # Cut the exclamation mark out of the triangle (stem + dot) so it reads
    # even at menu-bar scale -- a drawn-on-top mark of the same red vanishes.
    stem = [0.46 * s, 0.32 * s, 0.54 * s, 0.62 * s]
    dot = [0.45 * s, 0.70 * s, 0.55 * s, 0.80 * s]
    draw.rectangle(stem, fill=(0, 0, 0, 0))
    draw.ellipse(dot, fill=(0, 0, 0, 0))
    return img


def main() -> None:
    out_dir = pathlib.Path(__file__).resolve().parent
    for name, builder in (("skills-current.png", draw_current), ("skills-drift.png", draw_drift)):
        img = builder().resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
        dest = out_dir / name
        img.save(dest)
        print(dest)


if __name__ == "__main__":
    main()
