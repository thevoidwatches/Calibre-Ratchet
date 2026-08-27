#!/usr/bin/env python3
"""Generate the Ratchet icon set into ratchet/static/.

One geometry, three outputs — icon.svg (favicon + header logo), icon-192.png /
icon-512.png (PWA manifest), icon-maskable-512.png (Android adaptive /
maskable, glyph inside the 80% safe zone) — so the vector and raster versions
cannot drift apart.

The mark: a ratchet wheel (asymmetric sawtooth teeth — the tool the project is
named for). Two-tone, matching the UI's black-on-white / white-on-black
palette.

Usage:  python scripts/make_icons.py
Needs pillow (dev-only dependency; not required to run the service).
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "ratchet" / "static"

# All geometry on a 512x512 canvas, centre (256, 256).
C = 256.0
DISC_R = 248          # white background disc
RING_OUTER = 236      # tooth tips
RING_ROOT = 212       # tooth roots (outer edge of the solid ring)
RING_INNER = 168      # inner edge of the ring
TEETH = 16
TOOTH_SLOPE = 0.55    # fraction of the pitch the sawtooth back-slope spans


def _pt(r: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return (C + r * math.cos(a), C + r * math.sin(a))


def ratchet_outline() -> list[tuple[float, float]]:
    """Sawtooth wheel outline: a radial face then a slope back to the root —
    the asymmetric profile that reads as 'ratchet' rather than 'gear'."""
    pts: list[tuple[float, float]] = []
    pitch = 360.0 / TEETH
    for i in range(TEETH):
        a0 = i * pitch - 90.0
        pts.append(_pt(RING_ROOT, a0))                        # root
        pts.append(_pt(RING_OUTER, a0))                       # radial face
        pts.append(_pt(RING_ROOT, a0 + pitch * TOOTH_SLOPE))  # back-slope
        # flat root run to the next tooth comes from its first point
    return pts


def svg() -> str:
    def poly(points, fill):
        coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        return f'<polygon points="{coords}" fill="{fill}"/>'

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">\n'
        f'  <circle cx="{C:g}" cy="{C:g}" r="{DISC_R}" fill="#fff"/>\n'
        f"  {poly(ratchet_outline(), '#000')}\n"
        f'  <circle cx="{C:g}" cy="{C:g}" r="{RING_INNER}" fill="#fff"/>\n'
        "</svg>\n"
    )


def raster(size: int, glyph_scale: float) -> Image.Image:
    """White square, glyph centred at glyph_scale of the canvas. Drawn 4x and
    downsampled for clean edges."""
    ss = 4
    big = size * ss
    img = Image.new("RGB", (big, big), "white")
    d = ImageDraw.Draw(img)

    k = (big / 512.0) * glyph_scale
    off = (big - 512.0 * k) / 2.0
    t = lambda pts: [(x * k + off, y * k + off) for x, y in pts]

    d.polygon(t(ratchet_outline()), fill="black")
    (ix0, iy0), (ix1, iy1) = t([(C - RING_INNER, C - RING_INNER),
                                (C + RING_INNER, C + RING_INNER)])
    d.ellipse([ix0, iy0, ix1, iy1], fill="white")

    return img.resize((size, size), Image.LANCZOS)


def raster_tray(size: int) -> Image.Image:
    """Round badge on transparency, for the Windows notification area.

    Kept as a white disc rather than a bare glyph: the taskbar may be dark or
    light, and a single-colour mark would disappear against one of them.
    """
    ss = 4
    big = size * ss
    img = Image.new("RGBA", (big, big), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)

    k = big / 512.0
    t = lambda pts: [(x * k, y * k) for x, y in pts]
    circle = lambda r: [(C - r) * k, (C - r) * k, (C + r) * k, (C + r) * k]

    d.ellipse(circle(DISC_R), fill=(255, 255, 255, 255))
    d.polygon(t(ratchet_outline()), fill=(0, 0, 0, 255))
    d.ellipse(circle(RING_INNER), fill=(255, 255, 255, 255))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    (OUT / "icon.svg").write_text(svg(), encoding="utf-8")
    raster(512, 0.94).save(OUT / "icon-512.png")
    raster(192, 0.94).save(OUT / "icon-192.png")
    # Maskable: any launcher shape may crop to ~80% — keep the glyph inside.
    raster(512, 0.70).save(OUT / "icon-maskable-512.png")
    # Tray: pystray scales this down to whatever the shell asks for.
    raster_tray(64).save(OUT / "icon-tray.png")
    for name in ["icon.svg", "icon-512.png", "icon-192.png",
                 "icon-maskable-512.png", "icon-tray.png"]:
        print(f"  wrote {OUT / name}")


if __name__ == "__main__":
    main()
