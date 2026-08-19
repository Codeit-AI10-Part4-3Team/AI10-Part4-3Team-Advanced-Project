"""Experiment D: split the reference in two, so neither has to carry both things.

PIPELINE_SURVEY 4.5 ended on a contradiction. One reference cannot say both "draw in
this style" and "the label surface is blank":

  scene reference   style transfers 6/6, text leaks back in (11/18)
  blank-product     text is controllable (6/6 in 4.3) but the style does not land

diffusers supports loading the same adapter twice and scaling each copy into
different UNet blocks, so each reference only has to carry one thing:

  adapter 0  style ref (4.4's scene image)   -> up.block_0      InstantStyle "style"
  adapter 1  blank-product ref (4.3's image) -> down.block_2    InstantStyle "layout"

The block split is the hypothesis under test, not a known answer, so `sweep` walks the
product-side scale on two styles first and `full` runs the winner across all six with
a single-adapter control arm on the same seeds and the same refs.

Text is scored by text_detect.py, not by eye. Style transfer is still judged by eye -
we have no validated style metric (AGENTS.md quality rules).
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
ADAPTER = "ip-adapter-plus_sdxl_vit-h.safetensors"
DTYPE = torch.float16

# InstantStyle blocks. up.block_0[1] is the style layer, down.block_2[1] the layout
# layer; every other entry stays 0 so an adapter only speaks through its own block.
STYLE_BLOCK = {"up": {"block_0": [0.0, 1.0, 0.0]}}
OFF = {"up": {"block_0": [0.0, 0.0, 0.0]}}


def layout_block(scale, both=False):
    """Product-side scale: layout attention only, or both attentions of down.block_2."""
    return {"down": {"block_2": [scale if both else 0.0, scale]}}


# Product-side strength is the unknown - the two references can push each other out.
SWEEP = {
    "p04": layout_block(0.4),
    "p07": layout_block(0.7),
    "p10": layout_block(1.0),
    "p10w": layout_block(1.0, both=True),
}
SWEEP_STYLES = ["webtoon", "watercolor"]  # worst (0/3) and typical (2/3) in 4.4

STYLES = ["webtoon", "watercolor", "flat_vector", "render_3d", "retro_print", "photo_min"]

# Held identical to style_probe.py so 4.4 and this round are comparable.
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


def build_pipe():
    image_encoder = CLIPVisionModelWithProjection.from_pretrained(
        IP_REPO, subfolder="models/image_encoder", torch_dtype=DTYPE
    )
    vae = AutoencoderKL.from_pretrained(VAE_FIX, torch_dtype=DTYPE)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        BASE, vae=vae, image_encoder=image_encoder,
        torch_dtype=DTYPE, variant="fp16", use_safetensors=True,
    ).to("cuda")
    # Two copies of the same adapter. image_encoder_folder is mandatory: without it the
    # encoder silently falls back to bigG and the projection dimensions stop matching.
    pipe.load_ip_adapter(
        IP_REPO, subfolder="sdxl_models",
        weight_name=[ADAPTER, ADAPTER],
        image_encoder_folder="models/image_encoder",
    )
    return pipe


def generate(pipe, prompt, refs, seed, args):
    gen = torch.Generator("cuda").manual_seed(seed)
    t0 = time.perf_counter()
    image = pipe(
        prompt=prompt, negative_prompt=NEGATIVE, ip_adapter_image=refs,
        num_inference_steps=args.steps, guidance_scale=args.cfg,
        height=args.size, width=args.size, generator=gen,
    ).images[0]
    return image, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["sweep", "full"], required=True)
    ap.add_argument("--refdir", type=Path, required=True, help="4.4 style refs, <style>.png")
    ap.add_argument("--ref-product", type=Path, required=True, help="4.3 blank-package ref")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--config", choices=sorted(SWEEP), help="full phase: winning config")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--size", type=int, default=1088)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    if args.phase == "full" and not args.config:
        ap.error("--config is required for --phase full")

    args.outdir.mkdir(parents=True, exist_ok=True)
    pipe = build_pipe()
    product_ref = load_image(str(args.ref_product))
    style_refs = {s: load_image(str(args.refdir / f"{s}.png")) for s in STYLES}

    metrics = {
        "base": BASE, "adapter": ADAPTER, "phase": args.phase,
        "style_blocks": "up.block_0", "product_blocks": "down.block_2",
        "steps": args.steps, "cfg": args.cfg, "size": args.size,
        "product_ref": str(args.ref_product), "images": [],
    }

    if args.phase == "sweep":
        metrics["configs"] = {k: v for k, v in SWEEP.items()}
        for cfg_name, product_scale in SWEEP.items():
            pipe.set_ip_adapter_scale([STYLE_BLOCK, product_scale])
            for style in SWEEP_STYLES:
                for k in range(args.samples):
                    seed = args.seed + k
                    image, dt = generate(
                        pipe, PRODUCT, [style_refs[style], product_ref], seed, args
                    )
                    tag = f"{cfg_name}_{style}_s{seed}"
                    image.save(args.outdir / f"{tag}.png")
                    metrics["images"].append({
                        "id": tag, "arm": "dual", "config": cfg_name,
                        "style": style, "seed": seed, "seconds": round(dt, 1),
                    })
                    print(f"[sweep] {tag}: {dt:.1f}s", flush=True)
    else:
        # Both arms in one run so the control shares refs, seeds and pipeline state.
        # The control zeroes the second adapter rather than unloading it - unloading and
        # reloading swaps the image encoder back to bigG (RESULTS trap table).
        arms = {"dual": SWEEP[args.config], "style_only": OFF}
        metrics["config"] = args.config
        metrics["product_scale"] = SWEEP[args.config]
        for arm, product_scale in arms.items():
            pipe.set_ip_adapter_scale([STYLE_BLOCK, product_scale])
            for style in STYLES:
                for k in range(args.samples):
                    seed = args.seed + k
                    image, dt = generate(
                        pipe, PRODUCT, [style_refs[style], product_ref], seed, args
                    )
                    tag = f"{arm}_{style}_s{seed}"
                    (args.outdir / arm).mkdir(exist_ok=True)
                    image.save(args.outdir / arm / f"{style}_s{seed}.png")
                    metrics["images"].append({
                        "id": tag, "arm": arm, "style": style,
                        "seed": seed, "seconds": round(dt, 1),
                    })
                    print(f"[full] {tag}: {dt:.1f}s", flush=True)

    metrics["peak_allocated_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    (args.outdir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"done: {len(metrics['images'])} images", flush=True)


if __name__ == "__main__":
    main()
