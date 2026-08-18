#!/usr/bin/env bash
# FLUX.1-schnell 8-bit stack. Disk budget forces a pre-quantized transformer:
# the bf16 transformer alone is 23.8GB, which we deliberately do not pull.
set -euo pipefail
PROBE=~/local-model-probe
export HF_HOME="$PROBE/hf"
cd "$PROBE"
./.venv/bin/pip install -q gguf
./.venv/bin/python - <<'PY'
from huggingface_hub import hf_hub_download, snapshot_download

# Transformer: Q8_0 (12.7GB). Official BFL repo is gated (401 anonymous),
# so the pipeline scaffolding comes from an ungated mirror of the same weights.
p = hf_hub_download("city96/FLUX.1-schnell-gguf", "flux1-schnell-Q8_0.gguf")
print("transformer:", p)

# Everything except the transformer: T5-XXL bf16, CLIP-L, VAE, tokenizers, scheduler.
d = snapshot_download(
    "unsloth/FLUX.1-schnell",
    allow_patterns=["model_index.json", "scheduler/*", "tokenizer/*",
                    "tokenizer_2/*", "text_encoder/*", "text_encoder_2/*", "vae/*"],
)
print("pipeline:", d)
PY
du -sh "$PROBE/hf"; df -h / | tail -1
