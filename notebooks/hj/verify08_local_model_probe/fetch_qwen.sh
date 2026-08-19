#!/usr/bin/env bash
# Qwen-Image weights, about 29GB. Cannot coexist with the FLUX set on the 100GB disk.
set -euo pipefail
PROBE=~/local-model-probe
export HF_HOME="$PROBE/hf"
cd "$PROBE"
./.venv/bin/python - <<'PY'
from huggingface_hub import hf_hub_download, snapshot_download

# Q4_K_M is the largest quant that still leaves room for the bf16 text encoder.
# Q8_0 (21.8GB) + encoder (16.6GB) does not fit, so Q4 is the ceiling here.
p = hf_hub_download("unsloth/Qwen-Image-GGUF", "qwen-image-Q4_K_M.gguf")
print("transformer:", p)

# Everything except the transformer shards: Qwen2.5-VL text encoder, VAE, tokenizer, scheduler.
d = snapshot_download(
    "Qwen/Qwen-Image",
    allow_patterns=["model_index.json", "scheduler/*", "tokenizer/*",
                    "text_encoder/*", "vae/*", "processor/*"],
)
print("pipeline:", d)
PY
df -h / | tail -1
