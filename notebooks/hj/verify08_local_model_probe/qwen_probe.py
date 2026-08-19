"""Qwen-Image probe: can an open-weight model draw Hangul on this VM?

This is the question the rest of the exploration could not answer. FLUX and SDXL
cannot render Korean at all (RESULTS.md 3.1), which forces post-composition and
prompt translation. Qwen-Image is Apache-2.0 and claims high-precision Korean text,
so if it holds, the whole local path simplifies.

Same two-phase structure as flux_probe.py: the Qwen2.5-VL text encoder (about 16GB
in bf16) and the transformer (about 13GB at Q4_K_M) do not fit together in 22.5GB,
and host RAM is 16GB so offloading is not an escape.

Caveat for the report: the transformer is 4-bit quantized. Quantization hits text
rendering harder than it hits composition, so a failure here is not conclusive for
the model - only for the model at this quantization on this hardware.
"""

import argparse
import gc
import json
import time
from pathlib import Path

import torch
from diffusers import GGUFQuantizationConfig, QwenImagePipeline, QwenImageTransformer2DModel

REPO = "Qwen/Qwen-Image"
GGUF_NAME = "qwen-image-Q4_K_M.gguf"
DTYPE = torch.bfloat16
NEGATIVE = " "  # Qwen-Image's own examples use a blank negative for true CFG


def find_gguf():
    root = Path.home() / "local-model-probe/hf/hub"
    hits = sorted(root.glob(f"models--unsloth--Qwen-Image-GGUF/snapshots/*/{GGUF_NAME}"))
    if not hits:
        raise FileNotFoundError(f"{GGUF_NAME} not found under {root}")
    return hits[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=4.0)
    ap.add_argument("--size", type=int, default=1088)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--samples", type=int, default=1)
    args = ap.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    prompts = json.loads(args.prompts.read_text(encoding="utf-8"))
    metrics = {
        "model": f"Qwen-Image {GGUF_NAME}",
        "steps": args.steps,
        "true_cfg_scale": args.cfg,
        "size": args.size,
        "seed": args.seed,
        "samples": args.samples,
        "images": [],
    }

    # Phase 1 - Qwen2.5-VL text encoder only.
    t0 = time.perf_counter()
    enc = QwenImagePipeline.from_pretrained(
        REPO, transformer=None, vae=None, torch_dtype=DTYPE
    ).to("cuda")
    metrics["load_encoder_s"] = round(time.perf_counter() - t0, 1)

    # encode_prompt returns mask=None when every token is unmasked, so park() has to
    # tolerate None or phase 2 dies on a NoneType.
    def park(t):
        return None if t is None else t.detach().cpu().clone()

    embeds = []
    t0 = time.perf_counter()
    with torch.inference_mode():
        for item in prompts:
            pe, mask = enc.encode_prompt(prompt=item["prompt"], device="cuda")
            ne, nmask = enc.encode_prompt(prompt=NEGATIVE, device="cuda")
            embeds.append((item["id"], park(pe), park(mask), park(ne), park(nmask)))
    metrics["encode_s"] = round(time.perf_counter() - t0, 1)
    metrics["encoder_peak_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    print(f"[vram] encoder peak {metrics['encoder_peak_gb']} GB", flush=True)

    del enc
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    print(f"[vram] free after encoder: {torch.cuda.mem_get_info()[0] / 1e9:.2f} GB", flush=True)

    # Phase 2 - transformer + VAE.
    t0 = time.perf_counter()
    transformer = QwenImageTransformer2DModel.from_single_file(
        find_gguf(),
        quantization_config=GGUFQuantizationConfig(compute_dtype=DTYPE),
        config=REPO,
        subfolder="transformer",
        torch_dtype=DTYPE,
    )
    pipe = QwenImagePipeline.from_pretrained(
        REPO, transformer=transformer, text_encoder=None, tokenizer=None, torch_dtype=DTYPE
    ).to("cuda")
    metrics["load_transformer_s"] = round(time.perf_counter() - t0, 1)

    for name, pe, mask, ne, nmask, in embeds:
        for k in range(args.samples):
            seed = args.seed + k
            gen = torch.Generator("cuda").manual_seed(seed)
            t0 = time.perf_counter()
            to_gpu = lambda t: None if t is None else t.to("cuda")  # noqa: E731
            image = pipe(
                prompt_embeds=to_gpu(pe),
                prompt_embeds_mask=to_gpu(mask),
                negative_prompt_embeds=to_gpu(ne),
                negative_prompt_embeds_mask=to_gpu(nmask),
                true_cfg_scale=args.cfg,
                num_inference_steps=args.steps,
                height=args.size,
                width=args.size,
                generator=gen,
            ).images[0]
            dt = time.perf_counter() - t0
            path = args.outdir / f"{name}_s{seed}.png"
            image.save(path)
            metrics["images"].append({"id": name, "seed": seed, "seconds": round(dt, 1)})
            print(f"[gen] {name} seed={seed}: {dt:.1f}s -> {path}", flush=True)

    metrics["transformer_peak_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    print(f"[vram] transformer peak {metrics['transformer_peak_gb']} GB", flush=True)
    (args.outdir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
