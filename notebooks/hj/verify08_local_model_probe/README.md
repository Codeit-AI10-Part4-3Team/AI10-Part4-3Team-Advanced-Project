# 검증 8순위 - VM 로컬 모델 구동 확인 (+ 4순위 인계용 사전 측정)

기획서 15절 8순위("VM 스펙 확인 마무리, 완료 조건: 로컬 모델 구동 가능 여부 확정")를 닫고,
그 결과를 검증 4순위(로컬 모델과 GPT 비교, 소관 04 정승호)에 넘기기 위한 하네스입니다.

수행: 신호정(02 테크리드 겸 03 생성 서빙), 2026-08-15.

**이어받는 분은 [NEXT_STEPS.md](NEXT_STEPS.md) 를 먼저 보십시오** - 시작점(VM 상태), 후속
과제의 우선순위, 실측으로 겪은 함정 목록이 거기 있습니다.

## 이 폴더가 결정하지 않는 것

**여기에는 채택 권고가 없습니다.** A-5(로컬 모델 채택 여부)의 판단 근거는 검증 4순위 결과이고,
그 과제의 수행자는 04이며 판정자는 임동규, 송기하 2명입니다
([미결정_대장.md](../../../docs/기술문서/미결정_대장.md) B-15). 이 폴더는 그 과제가 쓸
**입력물**입니다. 수치와 재현 절차까지가 범위이고, 우열 판정은 범위 밖입니다.

휴지기(2026-08-15 ~ 08-17) 탐색으로 수행했으며, 승인은 메신저로 받았습니다. 메신저는 근거
자료가 아니므로([AGENTS.md](../../../AGENTS.md) 근거 자료 규칙) **이 문서의 수치는 회의록에
올려 확정하기 전까지 결정의 근거가 아닙니다.**

## 무엇을 쟀는가

| 축 | 왜 재는가 |
|---|---|
| 구동 가능 여부와 peak VRAM | 8순위의 완료 조건. 가용 22.5GB 안에 들어가는지 |
| 장당 생성 시간 | 4순위 비교의 정량 축. gpt-image-2 기준선이 이미 있음 |
| 한국어 카피 렌더와 한국어 프롬프트 이해 | 로컬 채택 시 파이프라인이 바뀌는 지점 |
| IP-Adapter on/off 델타 | 4순위 완료 조건에 명시된 항목 |
| LoRA 학습 1스텝 peak VRAM | 04가 config를 쓰기 전에 하드웨어가 막는지 |

## 조건 (바꾸면 이전 회차와 비교가 깨집니다)

- 해상도 **1088 x 1088**. gpt-image-2 `single` 회차와 같은 값입니다
  ([conditions.py](../verify01_korean_text_rendering/conditions.py)의 `SINGLE_AD_SIZE`,
  미결정_대장 A-8 잠정값).
- 시드 42 고정 (저장소 공통 규약).
- FLUX는 4 steps, `guidance_scale=0.0`. schnell 은 timestep distilled 이라 CFG 가 동작하지
  않습니다. SDXL 은 30 steps, CFG 7.0.
- 프롬프트는 `prompts_*.json` 에 있습니다. **영어입니다** - 이유는 RESULTS.md 3.1절.

## 실행

VM 안의 호스트 venv 에서 돕니다. compose 스택과 분리되어 있고 서빙 경로를 건드리지 않습니다
([ADR-0003](../../../docs/adr/0003-이미지_생성_경로.md)이 이음매를 둘로 만드는 것을 금지).

```bash
# VM 에서
python3 -m venv ~/local-model-probe/.venv
~/local-model-probe/.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128
~/local-model-probe/.venv/bin/pip install diffusers transformers accelerate safetensors \
    sentencepiece protobuf huggingface_hub gguf peft

export HF_HOME=~/local-model-probe/hf
bash fetch_weights.sh                                     # FLUX 계열, 약 23GB
bash fetch_qwen.sh                                        # Qwen-Image, 약 30GB

python flux_probe.py     --prompts prompts_scenes.json --outdir out/flux --samples 5
python sdxl_probe.py     --prompts prompts_sdxl.json --reference <레퍼런스>.png \
                         --outdir out/sdxl --samples 5
python pipeline_smoke.py --prompts prompts_sdxl.json --reference <레퍼런스>.png \
                         --outdir out/pipeline --samples 5   # IP-Adapter 변형 4종
python qwen_probe.py     --prompts prompts_qwen.json --outdir out/qwen --samples 5
python lora_memprobe.py                                   # 메모리 측정만, 산출물 없음

# 레퍼런스 2장 구성 (SURVEY 4.8). 화풍 레퍼런스는 style_probe.py 가 만든 out/styles/refs/ 를,
# 제품 레퍼런스는 4.3 의 글자 없는 무지 패키지 컷을 씁니다.
python dual_probe.py --phase sweep --refdir out/styles/refs --ref-product ref_clean.png \
                     --outdir out/dual_sweep --samples 3     # 제품쪽 scale 4종
python dual_probe.py --phase full --config p10 --refdir out/styles/refs \
                     --ref-product ref_clean.png --outdir out/dual_full --samples 5

# 글자 판정은 CPU 라 GPU 와 다투지 않습니다. 생성이 끝난 뒤 따로 돌립니다.
python text_detect.py out/dual_full/dual out/dual_full/style_only --out out/dual_full/ocr.json

# 후처리 합성은 CPU 만 씁니다. VM 이 필요 없습니다.
python compose_copy.py --image <글자없는이미지>.png --copy "한 장이면 충분해." \
                       --font NanumGothic.ttf --out out/composed.png
```

**FLUX 와 Qwen 을 동시에 두지 못합니다.** 디스크 상한 때문이며, 2026-08-15 회차는 FLUX 실측을
마친 뒤 지우고 Qwen 을 받았습니다. 어느 쪽을 다시 재려면 그쪽을 다시 받아야 합니다.

주의: **GPU 를 다른 사람이 쓰고 있지 않은지 먼저 확인하세요.** 한 대뿐이라 겹치면 둘 다 죽습니다
(`nvidia-smi --query-compute-apps=pid,used_memory --format=csv`). 2026-08-15 기준 compose 스택은
GPU 를 쓰지 않습니다.

## 결과물 위치

이미지와 `metrics.json` 은 **`outputs/로컬모델_탐색/`** 에 있고, 회차별로 폴더가 나뉘어
있습니다. **어느 폴더가 어느 절의 근거인지는 그 폴더의 `README.md`** 에 표로 있습니다
(gpt-image-2 쪽 `outputs/API_이미지생성_검증/` 과 같은 배치입니다).

`/outputs/` 는 저장소 루트 `.gitignore` 142번 줄에 걸려 **커밋되지 않습니다** - 공개
저장소이므로 의도된 배치입니다. 판정자에게는 파일로 전달하고, 수치는 이 폴더의 문서에만
남깁니다. **수치의 정본은 이미지가 아니라 문서입니다.**

폴더 이름은 한글입니다. 저장소의 명명 규약은 코드와 에셋 경로를 영어로 정하고 있지만
([AGENTS.md](../../../AGENTS.md) 명명 규약), `/outputs/` 는 커밋되지 않아 빌드 도구와 CI 가
소비하지 않는 로컬 산출물 영역이고, 실험이 쌓이면서 영어 한 단어로는 회차를 구분할 수 없게
되어 팀이 한글로 정했습니다. **스크립트가 VM 에서 쓰는 `out/` 경로는 영어 그대로입니다.**

## 디스크 주의

가중치가 큽니다. 2026-08-15 기준 다운로드 후 VM 여유는 **16GB** 입니다.

| 대상 | 크기 |
|---|---|
| FLUX transformer Q8_0 (gguf) | 12.7GB |
| FLUX 텍스트 인코더(T5-XXL bf16) + VAE + 토크나이저 | 약 10GB |
| SDXL base 1.0 fp16 + fp16-fix VAE | 약 7GB |
| IP-Adapter (ViT-H 인코더 포함) | 약 3GB |
| torch + CUDA 휠 | 약 8GB |

**FLUX bf16 원본(23.8GB)은 받지 않았습니다.** 받으면 디스크가 무너지고, 그것이 RESULTS.md
3.4절의 결론으로 이어집니다.
