"""FLUX.1-schnell probe on the L4 (22.5GB VRAM / 16GB host RAM).

Two-phase by design: text encoders and the transformer are never resident at the
same time. Co-residency is 9.5GB + 12.7GB = 22.2GB, which fits VRAM only barely and
does NOT fit the 16GB host RAM once diffusers offloads one of them - that path
thrashes on swap. So we encode, free, then denoise.
"""

import argparse
import gc
import json
import time
from pathlib import Path

import torch
from diffusers import FluxPipeline, FluxTransformer2DModel, GGUFQuantizationConfig

REPO = "unsloth/FLUX.1-schnell"  # ungated mirror; BFL repo is gated (401 anonymous)
GGUF = Path.home() / (
    "local-model-probe/hf/hub/models--city96--FLUX.1-schnell-gguf/snapshots"
    "/f495746ed9c5efcf4661f53ef05401dceadc17d2/flux1-schnell-Q8_0.gguf"
)
DTYPE = torch.bfloat16


def vram(tag, out):
    """Peak VRAM since the last reset, in GB."""
    torch.cuda.synchronize()
    peak = torch.cuda.max_memory_allocated() / 1e9
    resv = torch.cuda.max_memory_reserved() / 1e9
    out[tag] = {"peak_allocated_gb": round(peak, 2), "peak_reserved_gb": round(resv, 2)}
    print(f"[vram] {tag}: allocated {peak:.2f} GB / reserved {resv:.2f} GB", flush=True)
    torch.cuda.reset_peak_memory_stats()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", type=Path, required=True, help="JSON list of {id, prompt}")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--steps", type=int, default=4)  # schnell is distilled to 1-4 steps
    ap.add_argument("--size", type=int, default=1088)  # A-8 provisional, multiple of 16
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=1, help="seeds seed..seed+n-1")
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    prompts = json.loads(args.prompts.read_text(encoding="utf-8"))
    metrics = {
        "model": "FLUX.1-schnell Q8_0 (gguf)",
        "steps": args.steps,
        "size": args.size,
        "seed": args.seed,
        "samples": args.samples,
        "guidance_scale": 0.0,
        "images": [],
    }

    # Phase 1 - text encoders only. transformer/vae stay unloaded.
    t0 = time.perf_counter()
    enc = FluxPipeline.from_pretrained(
        REPO, transformer=None, vae=None, torch_dtype=DTYPE
    ).to("cuda")
    metrics["load_encoders_s"] = round(time.perf_counter() - t0, 1)

    embeds = []
    t0 = time.perf_counter()
    # inference_mode + park on CPU: without it the embeddings keep an autograd graph
    # alive that pins the 12GB of encoder weights, and phase 2 then OOMs.
    with torch.inference_mode():
        for item in prompts:
            pe, pooled, _ = enc.encode_prompt(
                prompt=item["prompt"], prompt_2=None, max_sequence_length=256
            )
            embeds.append((item["id"], pe.detach().cpu().clone(), pooled.detach().cpu().clone()))
    metrics["encode_s"] = round(time.perf_counter() - t0, 1)
    vram("phase1_text_encoders", metrics)

    del enc
    gc.collect()
    torch.cuda.empty_cache()
    free_gb = torch.cuda.mem_get_info()[0] / 1e9
    print(f"[vram] after freeing encoders: {free_gb:.2f} GB free", flush=True)
    metrics["free_after_encoders_gb"] = round(free_gb, 2)

    # Phase 2 - transformer + VAE. GGUF dequantizes to bf16 per-layer at compute time.
    t0 = time.perf_counter()
    transformer = FluxTransformer2DModel.from_single_file(
        GGUF,
        quantization_config=GGUFQuantizationConfig(compute_dtype=DTYPE),
        config=REPO,
        subfolder="transformer",
        torch_dtype=DTYPE,
    )
    pipe = FluxPipeline.from_pretrained(
        REPO,
        transformer=transformer,
        text_encoder=None,
        text_encoder_2=None,
        tokenizer=None,
        tokenizer_2=None,
        torch_dtype=DTYPE,
    ).to("cuda")
    metrics["load_transformer_s"] = round(time.perf_counter() - t0, 1)

    for name, pe, pooled in embeds:
      for k in range(args.samples):
        seed = args.seed + k
        gen = torch.Generator("cuda").manual_seed(seed)
        t0 = time.perf_counter()
        image = pipe(
            prompt_embeds=pe.to("cuda"),
            pooled_prompt_embeds=pooled.to("cuda"),
            num_inference_steps=args.steps,
            guidance_scale=0.0,  # schnell is guidance-distilled: CFG is a no-op here
            height=args.size,
            width=args.size,
            generator=gen,
        ).images[0]
        dt = time.perf_counter() - t0
        path = args.outdir / f"{name}_s{seed}.png"
        image.save(path)
        metrics["images"].append(
            {"id": name, "seed": seed, "seconds": round(dt, 1), "path": str(path)}
        )
        print(f"[gen] {name} seed={seed}: {dt:.1f}s -> {path}", flush=True)

    vram("phase2_transformer", metrics)
    (args.outdir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
