"""Composite Korean copy onto a text-free generated image.

This is the other half of the local-model path. Neither FLUX nor SDXL can draw
Hangul (RESULTS.md 3.1), so if a local model is adopted the copy has to be drawn
by us. That makes the copy exact by construction - there is no misspelling risk,
which is the axis gpt-image-2 wins on today.

Runs on CPU. No model, no GPU, no VM.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def fit_font(font_path, text, max_width, start_size):
    """Largest size at which the copy still fits the safe width."""
    size = start_size
    while size > 8:
        font = ImageFont.truetype(str(font_path), size)
        if font.getbbox(text)[2] - font.getbbox(text)[0] <= max_width:
            return font, size
        size -= 2
    return ImageFont.truetype(str(font_path), 8), 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--copy", required=True)
    ap.add_argument("--font", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--margin-ratio", type=float, default=0.08)
    ap.add_argument("--color", default="#2f4a2a")
    args = ap.parse_args()

    img = Image.open(args.image).convert("RGB")
    w, h = img.size
    safe_width = int(w * (1 - 2 * args.margin_ratio))
    font, size = fit_font(args.font, args.copy, safe_width, int(h * 0.09))

    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), args.copy, font=font)
    x = (w - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = int(h * args.margin_ratio) - bbox[1]
    draw.text((x, y), args.copy, font=font, fill=args.color)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(json.dumps(
        {"out": str(args.out), "font_px": size, "copy": args.copy, "size": [w, h]},
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
