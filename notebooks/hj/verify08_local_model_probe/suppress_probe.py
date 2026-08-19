"""Experiment A: how far can text leakage be pushed down on SDXL + plus_style?

PIPELINE_SURVEY 4.1 got 8/10 text-free with ip-adapter-plus restricted to the style
block. The two remaining leaks have obvious suspects, and this separates them:

  reference  the current reference is a gpt-image-2 ad that HAS Korean copy in it,
             so the adapter may simply be carrying glyphs across. A text-free
             reference should remove that channel.
  wording    "do not write text" is a negation, and diffusion models follow
             descriptions better than prohibitions. Describing the surface we want
             ("blank unbranded packaging, plain solid-color label") may work where
             the negative prompt does not.

2 x 2 x 3 seeds. Everything else is held at the PIPELINE_SURVEY 4.1 winner.
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
STYLE_ONLY = {"up": {"block_0": [0.0, 1.0, 0.0]}}  # InstantStyle style block

SCENE = (
    "A single square advertisement image, clean Korean webtoon illustration style. "
    "A pack of gentle bamboo wet wipes, large and centered, product-only shot, "
    "soft pale green palette, bamboo stalks in the background."
)
# Positive framing: describe the blank surface we want instead of forbidding text.
BLANK = (
    " The packaging is completely blank and unbranded, a plain smooth solid-color "
    "label surface with no printing on it."
)
NEGATIVE = (
    "text, letters, words, korean characters, typography, writing, caption, "
    "watermark, signature, logo, brand name, people, hands, blurry"
)

WORDINGS = {"neg": SCENE, "pos": SCENE + BLANK}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-withtext", type=Path, required=True)
    ap.add_argument("--ref-clean", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--size", type=int, default=1088)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    metrics = {"base": BASE, "adapter": "ip-adapter-plus_sdxl_vit-h", "blocks": "up.block_0",
               "steps": args.steps, "cfg": args.cfg, "size": args.size, "images": []}

    image_encoder = CLIPVisionModelWithProjection.from_pretrained(
        IP_REPO, subfolder="models/image_encoder", torch_dtype=DTYPE
    )
    vae = AutoencoderKL.from_pretrained(VAE_FIX, torch_dtype=DTYPE)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        BASE, vae=vae, image_encoder=image_encoder,
        torch_dtype=DTYPE, variant="fp16", use_safetensors=True,
    ).to("cuda")
    pipe.load_ip_adapter(
        IP_REPO, subfolder="sdxl_models",
        weight_name="ip-adapter-plus_sdxl_vit-h.safetensors",
        image_encoder_folder="models/image_encoder",
    )
    pipe.set_ip_adapter_scale(STYLE_ONLY)

    refs = {"withtext": load_image(str(args.ref_withtext)),
            "clean": load_image(str(args.ref_clean))}

    for ref_name, ref in refs.items():
        for wording, prompt in WORDINGS.items():
            for k in range(args.samples):
                seed = args.seed + k
                gen = torch.Generator("cuda").manual_seed(seed)
                t0 = time.perf_counter()
                image = pipe(
                    prompt=prompt,
                    negative_prompt=NEGATIVE,
                    ip_adapter_image=ref,
                    num_inference_steps=args.steps,
                    guidance_scale=args.cfg,
                    height=args.size,
                    width=args.size,
                    generator=gen,
                ).images[0]
                dt = time.perf_counter() - t0
                tag = f"{ref_name}_{wording}_s{seed}"
                image.save(args.outdir / f"{tag}.png")
                metrics["images"].append(
                    {"id": tag, "reference": ref_name, "wording": wording,
                     "seed": seed, "seconds": round(dt, 1)}
                )
                print(f"[gen] {tag}: {dt:.1f}s", flush=True)

    metrics["peak_allocated_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    (args.outdir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
