#!/usr/bin/env python3
"""Draw the Flip Monitor icon: a monitor with a two-way switch arrow.

Regenerates icon.icns, which is committed so that installing the app needs
no Python. Run this only when changing the artwork:

    pip install pillow && ./icon.py

Kept deliberately blunt -- a solid silhouette and one thick arrow. Anything
finer turns to mush at the 16px Finder size.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

MASTER = 1024  # master canvas, downsampled into the iconset

# Sizes macOS expects in an .icns, as (pixels, iconset filename).
ICONSET_SIZES = (
    (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
)

WHITE = (255, 255, 255, 255)
GRADIENT_TOP = (86, 108, 232)
GRADIENT_BOTTOM = (44, 62, 168)


# --- Drawing helpers ---

def rounded_rect_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=255
    )
    return mask


def vertical_gradient(size, top, bottom):
    column = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        column.putpixel(
            (0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        )
    return column.resize((size, size))


def draw_master():
    """The 1024px master image every iconset size is derived from."""
    img = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))

    background = vertical_gradient(MASTER, GRADIENT_TOP, GRADIENT_BOTTOM).convert("RGBA")
    background.putalpha(rounded_rect_mask(MASTER, int(MASTER * 0.225)))
    img.alpha_composite(background)

    draw = ImageDraw.Draw(img)
    s = MASTER

    # Monitor bezel.
    bezel = [0.150 * s, 0.215 * s, 0.850 * s, 0.660 * s]
    draw.rounded_rectangle(bezel, radius=0.048 * s, outline=WHITE, width=int(0.052 * s))

    # Neck and base.
    neck_w = 0.070 * s
    draw.rectangle([s / 2 - neck_w / 2, bezel[3], s / 2 + neck_w / 2, 0.755 * s], fill=WHITE)
    draw.rounded_rectangle(
        [0.325 * s, 0.755 * s, 0.675 * s, 0.808 * s], radius=0.026 * s, fill=WHITE
    )

    # The two-way arrow across the screen: this is the "flip".
    mid_y = (bezel[1] + bezel[3]) / 2
    left_tip, right_tip = 0.275 * s, 0.725 * s
    draw.line([left_tip, mid_y, right_tip, mid_y], fill=WHITE, width=int(0.050 * s))

    head = 0.088 * s
    for tip, direction in ((left_tip, 1), (right_tip, -1)):
        draw.polygon(
            [
                (tip, mid_y),
                (tip + direction * head, mid_y - head * 0.82),
                (tip + direction * head, mid_y + head * 0.82),
            ],
            fill=WHITE,
        )
    return img


# --- Flow ---

def build_icns(destination):
    master = draw_master()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = pathlib.Path(tmp) / "flipmonitor.iconset"
        iconset.mkdir()
        for pixels, name in ICONSET_SIZES:
            master.resize((pixels, pixels), Image.LANCZOS).save(iconset / name)
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(destination)],
            check=True,
        )
    return destination


def main():
    if not shutil.which("iconutil"):
        sys.exit("icon.py: iconutil not found -- this only builds on macOS")
    destination = pathlib.Path(__file__).resolve().parent / "icon.icns"
    print(build_icns(destination))


if __name__ == "__main__":
    main()
