"""Regenerate every app icon from the artwork in icons-src/texi-robot.png.

    python3 apps/web/scripts/make_icons.py      (Pillow + numpy; dev tool, not part of the build)

The artwork is a rounded lavender tile with a soft purple glow on a light background. The tile
is cut out, its rounded corners are filled by extending the tile's own edge colour, and then:

* favicon.ico (16/32/48), favicon.png (96) and icons/icon-{192,512}.png — the tile with
  transparent rounded corners;
* icons/apple-touch-icon.png (180) — full-bleed square (iOS rounds the corners itself);
* icons/maskable-512.png — full-bleed, artwork shrunk into the 80 % safe circle;
* src/assets/logo.png (96) — the header mark.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

WEB = Path(__file__).resolve().parents[1]
SRC = WEB / "icons-src" / "texi-robot.png"
TILE = (243, 227, 1025, 988)  # the rounded tile inside the artwork (measured)
INSET = 64  # past the tile's rounded corners and bright rim
ART_CENTER = (0.525, 0.485)  # of the tile: hat, robot and book
ART_RADIUS = 0.45  # farthest artwork pixel from ART_CENTER, in tile widths
CORNER = 0.225  # corner radius of the transparent-corner icons, in icon widths


def flat_tile(size: int) -> Image.Image:
    """The tile as a full square: the inset content, edge-extended back to the full size."""
    tile = Image.open(SRC).convert("RGB").crop(TILE).resize((782, 782), Image.LANCZOS)
    inner = np.asarray(tile)[INSET:-INSET, INSET:-INSET]
    full = np.pad(inner, ((INSET, INSET), (INSET, INSET), (0, 0)), mode="edge")
    return Image.fromarray(full).resize((size, size), Image.LANCZOS)


def rounded(size: int) -> Image.Image:
    big = size * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * CORNER), fill=255)
    icon = flat_tile(size).convert("RGBA")
    icon.putalpha(mask.resize((size, size), Image.LANCZOS))
    return icon


def maskable(size: int) -> Image.Image:
    """Full-bleed: the artwork must fit the circle of radius 0.4 × size (with 12 % to spare)."""
    scale = 0.4 * 0.88 / ART_RADIUS
    inner_px = round(size * scale)
    art = np.asarray(flat_tile(inner_px))
    # put the artwork's centre (not the tile's) in the middle of the icon
    cx, cy = (round(size / 2 - ART_CENTER[0] * inner_px), round(size / 2 - ART_CENTER[1] * inner_px))
    pad = ((cy, size - inner_px - cy), (cx, size - inner_px - cx), (0, 0))
    icon = Image.fromarray(np.pad(art, pad, mode="edge"))
    # edge-extended rows and columns show as streaks: blur them into a smooth backdrop
    backdrop = icon.filter(ImageFilter.GaussianBlur(size / 12))
    keep = Image.new("L", icon.size, 0)
    f = size // 40
    ImageDraw.Draw(keep).rectangle((cx + f, cy + f, cx + inner_px - f, cy + inner_px - f), fill=255)
    return Image.composite(icon, backdrop, keep.filter(ImageFilter.GaussianBlur(f)))


def main() -> None:
    pub, icons = WEB / "public", WEB / "public" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        rounded(size).save(icons / f"icon-{size}.png", optimize=True)
    flat_tile(180).save(icons / "apple-touch-icon.png", optimize=True)
    # opaque, so a dithered 256-colour palette halves the file without visible banding
    maskable(512).quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(
        icons / "maskable-512.png", optimize=True)
    rounded(96).save(pub / "favicon.png", optimize=True)
    rounded(256).save(pub / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    rounded(96).save(WEB / "src" / "assets" / "logo.png", optimize=True)
    for p in [*icons.glob("*.png"), pub / "favicon.png", pub / "favicon.ico", WEB / "src" / "assets" / "logo.png"]:
        print(f"{p.relative_to(WEB)}: {p.stat().st_size // 1024 or 1} KB")


if __name__ == "__main__":
    main()
