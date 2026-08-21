# apps/ai-engine

광고 카피 생성과 이미지 생성, 그리고 가드레일을 담당하는 **독립 배포 단위**입니다. 자체 `pyproject.toml`·
`Dockerfile`·README를 갖고 있고, backend와는 **HTTP 계약으로만** 통신합니다.

> 왜 앱으로 분리했나: 수상작 레포 조사에서 반복 확인된 패턴이 "AI를 인라인 API 호출이 아니라
> **독립 배포 가능한 엔진/모듈**로 두고, 배포·운영을 README에 문서화한다"였습니다.
> 모노레포를 쓰되 그 실질을 만족시키는 구성입니다 ([ADR-0001](../../docs/adr/0001-모노레포_채택.md)).

## 실행

```bash
pip install -e "./apps/ai-engine[dev]"          # 레포 루트에서
uvicorn ai_engine.service:app --reload --port 8100   # → :8100/docs

curl -X POST localhost:8100/v1/draft:generate \
  -H 'content-type: application/json' \
  -d '{"outputType":"single_ad","brief":{...},"guardrailApplied":true}'
```

컨테이너 단독 실행:

```bash
docker build -t adgen-ai-engine:dev apps/ai-engine
docker run --rm -p 8100:8100 adgen-ai-engine:dev
```

## 구조와 방향

```
입력 정규화 → 프롬프트 조립 → 생성 → 가드레일 검증 → 출력
```

일방향입니다. 역방향 import가 들어오면 파이프라인이 아니라 그물이 됩니다.

| 모듈 | 역할 | 교체 지점(seam) |
|---|---|---|
| `brief_fill.py` | 사진과 글에서 카테고리·타겟 추론 | `_infer_stub` ↔ `_infer_with_model` |
| `draft.py` | 시안 생성과 부분 교체 | `_generate_stub` ↔ `_generate_with_model`, `_patch_stub` ↔ `_patch_with_model` |
| `render.py` | 이미지 생성 (만화형은 칸별 생성 후 3x2 합성) | `_render_stub` ↔ `_render_with_model` |
| `guardrail.py` | 프롬프트 제약 + 출력 검증 (`check_claims`) | 패턴은 측정 파라미터 — 느슨하게 고치면 억제율이 거짓으로 오릅니다 |
| `*_prompt.py` | 프롬프트 조립 | 모델 호출 없음 |
| `service.py` | HTTP 표면 (thin) | — |
| `eval/` | 재현 가능한 채점 하네스 | [eval/README.md](eval/README.md) |

**교체는 이음매에서.** 스텁을 우회해 옆에 새 경로를 만들지 말고, 같은 함수 안의 분기를
갈아끼우세요. 어느 쪽이 도는지는 `ADGEN_GENERATION_MODE` 하나가 정합니다.

## 하면 안 되는 것

- ❌ `import backend_core` / `import api` — 독립 배포 성질이 조용히 사라집니다.
- ❌ 계약에 없는 경로 추가 — `tests/test_service.py`가 정확한 집합으로 막습니다.
- ❌ 테스트를 통과시키려고 가드레일 끄기 — on/off 델타가 보고 지표입니다.
- ❌ 테스트에서 실제 모델 API 호출 — 비용이 들고 CI가 비결정적이 됩니다.

## 현재 상태

- **이음매 넷 다 실물 분기가 있습니다** (2026-08-20). 다만 기본값은 `ADGEN_GENERATION_MODE=stub`
  이라, 설정을 바꾸지 않고 얻은 숫자는 스텁이 자기 자신과 일치한 값입니다. **그 상태의 품질
  숫자를 보고하지 마세요.**
- **템플릿의 질의응답(`/v1/generate`, `retrieval.py`, `generation.py`, 번들 더미 코퍼스)은
  2026-08-20 에 삭제됐습니다.** 가드레일의 `verify` 계열도 함께 나갔습니다 - 광고 카피에서는
  어휘 겹침이 판정 근거가 되지 못하기 때문입니다
  ([ADR-0019](../../docs/adr/0019-광고_카피_가드레일은_금지_표현을_검출한다.md)).
