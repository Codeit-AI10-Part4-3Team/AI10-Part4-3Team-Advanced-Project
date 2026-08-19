"""Does a LoRA training step fit on this L4? Memory measurement only.

ADR-0004 puts fine-tuning out of scope, so this deliberately produces no artifact:
no dataset, no checkpoint, no run directory. It runs two synthetic steps on random
latents purely to read peak VRAM, and answers one question for the 04 handoff -
whether the hardware forecloses the option before anyone writes a config.
"""

import json
import time

import torch
from diffusers import UNet2DConditionModel
from peft import LoraConfig

BASE = "stabilityai/stable-diffusion-xl-base-1.0"
RES = 1024
LATENT = RES // 8


def main():
    out = {"base": BASE, "resolution": RES, "rank": 16, "batch_size": 1}

    unet = UNet2DConditionModel.from_pretrained(
        BASE, subfolder="unet", torch_dtype=torch.float32, variant="fp16"
    )
    unet.requires_grad_(False)
    # Same target modules as training/configs/brand-lora.example.yaml
    unet.add_adapter(
        LoraConfig(
            r=16, lora_alpha=16, init_lora_weights="gaussian",
            target_modules=["to_q", "to_k", "to_v", "to_out.0"],
        )
    )
    unet.enable_gradient_checkpointing()
    unet.to("cuda")

    trainable = [p for p in unet.parameters() if p.requires_grad]
    out["trainable_params_m"] = round(sum(p.numel() for p in trainable) / 1e6, 2)
    opt = torch.optim.AdamW(trainable, lr=1e-4)

    torch.cuda.reset_peak_memory_stats()
    out["vram_after_load_gb"] = round(torch.cuda.memory_allocated() / 1e9, 2)

    # Synthetic batch: SDXL needs both the text embeds and the added time ids.
    latents = torch.randn(1, 4, LATENT, LATENT, device="cuda", dtype=torch.float32)
    enc = torch.randn(1, 77, 2048, device="cuda", dtype=torch.float32)
    added = {
        "text_embeds": torch.randn(1, 1280, device="cuda", dtype=torch.float32),
        "time_ids": torch.zeros(1, 6, device="cuda", dtype=torch.float32),
    }
    t = torch.tensor([500], device="cuda")

    times = []
    for _ in range(2):
        t0 = time.perf_counter()
        with torch.autocast("cuda", dtype=torch.bfloat16):
            pred = unet(latents, t, encoder_hidden_states=enc, added_cond_kwargs=added).sample
            loss = torch.nn.functional.mse_loss(pred.float(), latents)
        loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        torch.cuda.synchronize()
        times.append(round(time.perf_counter() - t0, 2))

    out["step_seconds"] = times
    out["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    out["total_vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
