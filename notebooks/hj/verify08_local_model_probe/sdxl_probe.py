"""SDXL + IP-Adapter probe: does reference-image brand-tone transfer actually work?

This is the axis FLUX cannot answer today (the FLUX IP-Adapter ecosystem is built on
FLUX.1-dev, which is non-commercial). Verification task 4 asks for the IP-Adapter
effect, so we measure it on/off with everything else held fixed.
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
VAE_FIX = "madebyollin/sdxl-vae-fp16-fix"  # base fp16 VAE produces NaN/black on SDXL
IP_REPO = "h94/IP-Adapter"
DTYPE = torch.float16


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", type=Path, required=True)
    ap.add_argument("--reference", type=Path, required=True, help="IP-Adapter style reference")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--size", type=int, default=1088)  # 64 * 17, SDXL-friendly
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ip-scale", type=float, default=0.6)
    ap.add_argument("--samples", type=int, default=1, help="seeds seed..seed+n-1")
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    prompts = json.loads(args.prompts.read_text(encoding="utf-8"))
    metrics = {
        "model": "SDXL base 1.0 fp16 + IP-Adapter (ip-adapter_sdxl_vit-h)",
        "steps": args.steps,
        "cfg": args.cfg,
        "size": args.size,
        "seed": args.seed,
        "ip_scale": args.ip_scale,
        "samples": args.samples,
        "reference": args.reference.name,
        "images": [],
    }

    t0 = time.perf_counter()
    # vit-h adapter weights need the vit-h encoder; the default sdxl_models/image_encoder
    # is bigG and silently mismatches.
    image_encoder = CLIPVisionModelWithProjection.from_pretrained(
        IP_REPO, subfolder="models/image_encoder", torch_dtype=DTYPE
    )
    vae = AutoencoderKL.from_pretrained(VAE_FIX, torch_dtype=DTYPE)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        BASE, vae=vae, image_encoder=image_encoder,
        torch_dtype=DTYPE, variant="fp16", use_safetensors=True,
    ).to("cuda")
    metrics["load_s"] = round(time.perf_counter() - t0, 1)
    torch.cuda.reset_peak_memory_stats()

    reference = load_image(str(args.reference))

    def run(item, use_ip, seed):
        tag = f"{item['id']}_{'ip' if use_ip else 'noip'}_s{seed}"
        gen = torch.Generator("cuda").manual_seed(seed)
        kwargs = {}
        if use_ip:
            kwargs["ip_adapter_image"] = reference
        t = time.perf_counter()
        image = pipe(
            prompt=item["prompt"],
            negative_prompt=item.get("negative", ""),
            num_inference_steps=args.steps,
            guidance_scale=args.cfg,
            height=args.size,
            width=args.size,
            generator=gen,
            **kwargs,
        ).images[0]
        dt = time.perf_counter() - t
        path = args.outdir / f"{tag}.png"
        image.save(path)
        metrics["images"].append(
            {"id": tag, "ip_adapter": use_ip, "seed": seed, "seconds": round(dt, 1)}
        )
        print(f"[gen] {tag}: {dt:.1f}s -> {path}", flush=True)

    # Baseline first: the adapter cannot be unloaded cleanly mid-process, so all
    # off-runs happen before it is attached.
    for item in prompts:
        for k in range(args.samples):
            run(item, use_ip=False, seed=args.seed + k)

    pipe.load_ip_adapter(
        IP_REPO, subfolder="sdxl_models", weight_name="ip-adapter_sdxl_vit-h.safetensors"
    )
    pipe.set_ip_adapter_scale(args.ip_scale)
    for item in prompts:
        for k in range(args.samples):
            run(item, use_ip=True, seed=args.seed + k)

    peak = torch.cuda.max_memory_allocated() / 1e9
    metrics["peak_allocated_gb"] = round(peak, 2)
    print(f"[vram] peak {peak:.2f} GB", flush=True)
    (args.outdir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
