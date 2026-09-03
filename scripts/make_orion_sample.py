"""Generate a placeholder orion.jpg matching the M1 mock fixture.

The fixture's stars_overlay pixel_x/y are mapped from the 640x460 atlas
to 6016x4016. We render a dark sky + sparse background stars, then place
white circles exactly at the eight fixture coordinates so the overlay
falls on visible dots during the mock demo.

Run from repo root: ``python scripts/make_orion_sample.py``
Output: ``web/public/samples/orion.jpg``
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "server" / "data" / "fixtures" / "solve_orion.json"
OUTPUT = REPO_ROOT / "web" / "public" / "samples" / "orion.jpg"

IMG_W, IMG_H = 6016, 4016
# Background stars (count, min/max radius, min/max opacity) — purely decorative.
BG_STARS = 240
BG_RADIUS_RANGE = (1, 3)
BG_ALPHA_RANGE = (90, 200)


def magnitude_to_radius(mag: float) -> float:
    """Same formula as atlas (spec §6.1): clamp(4 - 0.4*mag, 1.2, 8) px."""
    return max(1.2, min(8.0, 4 - 0.4 * mag))


def render() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stars = fixture["stars_overlay"]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # Dark-blue sky background (flat, no gradients — matches "flat design" rule).
    img = Image.new("RGB", (IMG_W, IMG_H), (8, 12, 24))

    rng = random.Random(20260822)
    draw = ImageDraw.Draw(img, "RGBA")

    # 1. Background starfield (decorative).
    for _ in range(BG_STARS):
        x = rng.randint(0, IMG_W - 1)
        y = rng.randint(0, IMG_H - 1)
        r = rng.randint(*BG_RADIUS_RANGE)
        a = rng.randint(*BG_ALPHA_RANGE)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(220, 220, 230, a))

    # 2. Featured stars: draw at exact fixture coordinates with a soft glow.
    glow = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for s in stars:
        x, y = s["pixel_x"], s["pixel_y"]
        r = magnitude_to_radius(s["magnitude"])
        # Outer glow
        glow_draw.ellipse(
            (x - r * 4, y - r * 4, x + r * 4, y + r * 4),
            fill=(255, 250, 240, 70),
        )
        # Bright core
        draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=(255, 255, 255, 255),
        )

    glow = glow.filter(ImageFilter.GaussianBlur(radius=8))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Re-stamp bright cores on top of the blurred glow so they stay sharp.
    for s in stars:
        x, y = s["pixel_x"], s["pixel_y"]
        r = magnitude_to_radius(s["magnitude"])
        draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=(255, 255, 255, 255),
        )

    img.save(OUTPUT, "JPEG", quality=82, optimize=True)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    render()