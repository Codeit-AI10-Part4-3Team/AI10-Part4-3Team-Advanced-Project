"""Experiment B: does SDXL + plus_style hold up across different art styles?

PIPELINE_SURVEY 4.1 measured one style (Korean webtoon) against one reference. The
product needs a style picker (A-3, still open), so the question is whether the same
pipeline transfers an arbitrary style reliably, or whether it only worked because
the reference happened to sit close to what SDXL draws by default.

Two phases in one run:
  1. generate one style reference per style with plain SDXL - no adapter, neutral
     subject, no product. Self-generated on purpose: outside images would need
     rights clearance and this repo is public (A-3).
  2. feed each reference back through plus_style with the same product prompt.

The style list here is a probe list, NOT the A-3 candidate list. A-3 is still
blocked and its list is the team's to decide.
"""

import argparse
import json
import time
from pathlib import Path

import torch
from diffusers import AutoencoderKL, StableDiffusionXLPipeline
from diffusers.utils import load_image
from transformers import CLIPVisionModelWithProjection

BASE = "stabilityai/stable-diffusion-xl-base-1.0"
VAE_FIX = "madebyollin/sdxl-vae-fp16-fix"
IP_REPO = "h94/IP-Adapter"
DTYPE = torch.float16
STYLE_ONLY = {"up": {"block_0": [0.0, 1.0, 0.0]}}

STYLES = {
    "webtoon": "clean Korean webtoon illustration, flat cel shading, crisp linework",
    "watercolor": "soft watercolor painting, wet-on-wet washes, visible paper texture",
    "flat_vector": "flat vector illustration, bold geometric shapes, solid colors, no gradients",
    "render_3d": "glossy 3D product render, soft studio lighting, subsurface scattering",
    "retro_print": "retro screen-print poster, limited palette, halftone dots, print grain",
    "photo_min": "minimal studio product photography, soft shadow, seamless paper backdrop",
}

# Neutral subject so the reference carries style and not the product.
REF_SUBJECT = "a bamboo grove and a few smooth river pebbles on a plain table"

PRODUCT = (
    "A single square advertisement image. A pack of gentle bamboo wet wipes, large and "
    "centered, product-only shot, bamboo stalks in the background. The packaging is "
    "completely blank and unbranded, a plain smooth solid-color label surface with no "
    "printing on it."
)
NEGATIVE = (
    "text, letters, words, korean characters, typography, writing, caption, "
    "watermark, signature, logo, brand name, people, hands, blurry"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--size", type=int, default=1088)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    refdir = args.outdir / "refs"
    refdir.mkdir(parents=True, exist_ok=True)
    metrics = {"base": BASE, "adapter": "ip-adapter-plus_sdxl_vit-h", "blocks": "up.block_0",
               "steps": args.steps, "cfg": args.cfg, "size": args.size,
               "ref_subject": REF_SUBJECT, "styles": STYLES, "images": []}

    image_encoder = CLIPVisionModelWithProjection.from_pretrained(
        IP_REPO, subfolder="models/image_encoder", torch_dtype=DTYPE
    )
    vae = AutoencoderKL.from_pretrained(VAE_FIX, torch_dtype=DTYPE)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        BASE, vae=vae, image_encoder=image_encoder,
        torch_dtype=DTYPE, variant="fp16", use_safetensors=True,
    ).to("cuda")

    # Phase 1 - style references, adapter not yet attached.
    for name, style in STYLES.items():
        gen = torch.Generator("cuda").manual_seed(args.seed)
        image = pipe(
            prompt=f"{REF_SUBJECT}, {style}",
            negative_prompt=NEGATIVE,
            num_inference_steps=args.steps,
            guidance_scale=args.cfg,
            height=args.size, width=args.size, generator=gen,
        ).images[0]
        image.save(refdir / f"{name}.png")
        print(f"[ref] {name}", flush=True)

    # Phase 2 - transfer each reference onto the product prompt.
    pipe.load_ip_adapter(
        IP_REPO, subfolder="sdxl_models",
        weight_name="ip-adapter-plus_sdxl_vit-h.safetensors",
        image_encoder_folder="models/image_encoder",
    )
    pipe.set_ip_adapter_scale(STYLE_ONLY)

    for name in STYLES:
        ref = load_image(str(refdir / f"{name}.png"))
        for k in range(args.samples):
            seed = args.seed + k
            gen = torch.Generator("cuda").manual_seed(seed)
            t0 = time.perf_counter()
            image = pipe(
                prompt=PRODUCT,
                negative_prompt=NEGATIVE,
                ip_adapter_image=ref,
                num_inference_steps=args.steps,
                guidance_scale=args.cfg,
                height=args.size, width=args.size, generator=gen,
            ).images[0]
            dt = time.perf_counter() - t0
            tag = f"{name}_s{seed}"
            image.save(args.outdir / f"{tag}.png")
            metrics["images"].append(
                {"id": tag, "style": name, "seed": seed, "seconds": round(dt, 1)}
            )
            print(f"[gen] {tag}: {dt:.1f}s", flush=True)

    metrics["peak_allocated_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    (args.outdir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
