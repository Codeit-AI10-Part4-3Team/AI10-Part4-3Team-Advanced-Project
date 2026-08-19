"""Experiment C: re-measure style stability with references that follow the protocol.

4.4 measured 11/18 with scene-only references. 4.3 got 6/6 with a reference that was
a blank-package product shot. The difference is the reference, so this rebuilds the
style references to the protocol that 4.3 and 4.4 imply:

  no text  -  a reference with glyphs hands its glyphs to the output (4.3)
  product  -  a reference must show the label surface being blank, or the model
              fills that surface itself and what it fills in is fake text (4.4)
  one background  -  the reference carries its scene across, so styles can only be
              compared if their backgrounds are held constant (4.4)

Two phases so a human can sit in the middle. `refs` generates candidates per style;
someone picks a text-free one and records it in the chosen map; `gen` transfers the
chosen references onto the product prompt. Picking is manual because we have no OCR
gate yet - that is the automation this experiment argues for.
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

# Held constant across styles so the picker compares style and not scene.
BACKGROUND = "on a plain light grey seamless backdrop, centered, soft even lighting"
BLANK = (
    "The packaging is completely blank and unbranded, a plain smooth solid-color label "
    "surface with no printing on it."
)
REF_SUBJECT = f"A single soft plastic pouch of wet wipes, {BACKGROUND}. {BLANK}"
PRODUCT = (
    "A single square advertisement image. A pack of gentle bamboo wet wipes, large and "
    f"centered, product-only shot, bamboo stalks in the background. {BLANK}"
)
NEGATIVE = (
    "text, letters, words, korean characters, typography, writing, caption, "
    "watermark, signature, logo, brand name, people, hands, blurry"
)


def build_pipe():
    image_encoder = CLIPVisionModelWithProjection.from_pretrained(
        IP_REPO, subfolder="models/image_encoder", torch_dtype=DTYPE
    )
    vae = AutoencoderKL.from_pretrained(VAE_FIX, torch_dtype=DTYPE)
    return StableDiffusionXLPipeline.from_pretrained(
        BASE, vae=vae, image_encoder=image_encoder,
        torch_dtype=DTYPE, variant="fp16", use_safetensors=True,
    ).to("cuda")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["refs", "gen"], required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--chosen", type=Path, help="gen phase: {style: ref filename} json")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--size", type=int, default=1088)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    pipe = build_pipe()

    if args.phase == "refs":
        refdir = args.outdir / "ref_candidates"
        refdir.mkdir(exist_ok=True)
        for name, style in STYLES.items():
            for k in range(args.samples):
                seed = args.seed + k
                gen = torch.Generator("cuda").manual_seed(seed)
                image = pipe(
                    prompt=f"{REF_SUBJECT} {style}",
                    negative_prompt=NEGATIVE,
                    num_inference_steps=args.steps, guidance_scale=args.cfg,
                    height=args.size, width=args.size, generator=gen,
                ).images[0]
                image.save(refdir / f"{name}_s{seed}.png")
                print(f"[ref] {name}_s{seed}", flush=True)
        return

    chosen = json.loads(args.chosen.read_text(encoding="utf-8"))
    pipe.load_ip_adapter(
        IP_REPO, subfolder="sdxl_models",
        weight_name="ip-adapter-plus_sdxl_vit-h.safetensors",
        image_encoder_folder="models/image_encoder",
    )
    pipe.set_ip_adapter_scale(STYLE_ONLY)

    metrics = {"base": BASE, "adapter": "ip-adapter-plus_sdxl_vit-h", "blocks": "up.block_0",
               "steps": args.steps, "cfg": args.cfg, "size": args.size,
               "chosen_refs": chosen, "images": []}
    for name, ref_file in chosen.items():
        ref = load_image(str(args.outdir / "ref_candidates" / ref_file))
        for k in range(args.samples):
            seed = args.seed + k
            gen = torch.Generator("cuda").manual_seed(seed)
            t0 = time.perf_counter()
            image = pipe(
                prompt=PRODUCT, negative_prompt=NEGATIVE, ip_adapter_image=ref,
                num_inference_steps=args.steps, guidance_scale=args.cfg,
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
