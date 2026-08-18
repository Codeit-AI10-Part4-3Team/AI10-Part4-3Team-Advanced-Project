"""Smoke test of candidate generation pipelines on top of SDXL.

Motivated by two measured gaps (RESULTS.md 3.2, 3.3):
  - plain IP-Adapter transfers the reference image's *text* into the output;
  - SDXL alone loses the product, IP-Adapter fixes it but drags text along.

InstantStyle claims to separate style from content by injecting the image
embedding only into style-specific blocks. If that holds here, we get the brand
tone without the glyph leakage, which is the combination the ad path needs.

Variants
  ip_full   IP-Adapter on every block (the RESULTS.md 3.3 baseline)
  is_style  InstantStyle, style block only         (up.block_0)
  is_both   InstantStyle, style + layout blocks    (up.block_0 + down.block_2)
  plus_style  ip-adapter-plus (patch embeddings) restricted to the style block
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

# Block scales per InstantStyle: down.block_2 carries layout, up.block_0 carries style.
VARIANTS = {
    "ip_full": ("ip-adapter_sdxl_vit-h.safetensors", 0.6),
    "is_style": ("ip-adapter_sdxl_vit-h.safetensors", {"up": {"block_0": [0.0, 1.0, 0.0]}}),
    "is_both": (
        "ip-adapter_sdxl_vit-h.safetensors",
        {"down": {"block_2": [0.0, 1.0]}, "up": {"block_0": [0.0, 1.0, 0.0]}},
    ),
    "plus_style": ("ip-adapter-plus_sdxl_vit-h.safetensors", {"up": {"block_0": [0.0, 1.0, 0.0]}}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", type=Path, required=True)
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--size", type=int, default=1088)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=1)
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    prompts = json.loads(args.prompts.read_text(encoding="utf-8"))
    metrics = {"base": BASE, "steps": args.steps, "cfg": args.cfg, "size": args.size,
               "seed": args.seed, "reference": args.reference.name, "images": []}

    image_encoder = CLIPVisionModelWithProjection.from_pretrained(
        IP_REPO, subfolder="models/image_encoder", torch_dtype=DTYPE
    )
    vae = AutoencoderKL.from_pretrained(VAE_FIX, torch_dtype=DTYPE)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        BASE, vae=vae, image_encoder=image_encoder,
        torch_dtype=DTYPE, variant="fp16", use_safetensors=True,
    ).to("cuda")
    reference = load_image(str(args.reference))

    loaded = None
    for variant, (weight_name, scale) in VARIANTS.items():
        # Reloading the same weights is wasteful; only swap when the file changes.
        if weight_name != loaded:
            if loaded is not None:
                pipe.unload_ip_adapter()
            pipe.load_ip_adapter(
                IP_REPO, subfolder="sdxl_models", weight_name=weight_name,
                image_encoder_folder="models/image_encoder",
            )
            loaded = weight_name
        pipe.set_ip_adapter_scale(scale)

        for item in prompts:
          for k in range(args.samples):
            seed = args.seed + k
            gen = torch.Generator("cuda").manual_seed(seed)
            t0 = time.perf_counter()
            image = pipe(
                prompt=item["prompt"],
                negative_prompt=item.get("negative", ""),
                ip_adapter_image=reference,
                num_inference_steps=args.steps,
                guidance_scale=args.cfg,
                height=args.size,
                width=args.size,
                generator=gen,
            ).images[0]
            dt = time.perf_counter() - t0
            tag = f"{item['id']}_{variant}_s{seed}"
            image.save(args.outdir / f"{tag}.png")
            metrics["images"].append(
                {"id": tag, "variant": variant, "seed": seed, "seconds": round(dt, 1)}
            )
            print(f"[gen] {tag}: {dt:.1f}s", flush=True)

    metrics["peak_allocated_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    (args.outdir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
