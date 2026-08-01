# apps/ai-engine

검색(RAG) + 가드레일 기반 생성을 담당하는 **독립 배포 단위**입니다. 자체 `pyproject.toml`·
`Dockerfile`·README를 갖고 있고, backend와는 **HTTP 계약으로만** 통신합니다.

> 왜 앱으로 분리했나: 수상작 레포 조사에서 반복 확인된 패턴이 "AI를 인라인 API 호출이 아니라
> **독립 배포 가능한 엔진/모듈**로 두고, 배포·운영을 README에 문서화한다"였습니다.
> 모노레포를 쓰되 그 실질을 만족시키는 구성입니다 ([ADR-0001](../../docs/adr/0001-monorepo.md)).

## 실행

```bash
pip install -e "./apps/ai-engine[dev]"          # 레포 루트에서
uvicorn ai_engine.service:app --reload --port 8100   # → :8100/docs

curl -X POST localhost:8100/v1/generate \
  -H 'content-type: application/json' \
  -d '{"question":"환불은 어떻게 하나요?"}'
```

컨테이너 단독 실행:

```bash
docker build -t adgen-ai-engine:dev apps/ai-engine
docker run --rm -p 8100:8100 adgen-ai-engine:dev
```

## 구조와 방향

```
파싱 → 청킹 → 임베딩 → 검색(retrieval) → 생성(generation)
```

일방향입니다. `retrieval.py`가 `generation.py`를 import하면 파이프라인이 아니라 그물이 됩니다.

| 모듈 | 역할 | 교체 지점(seam) |
|---|---|---|
| `retrieval.py` | 근거 검색 | `Retriever` 프로토콜 — 번들 픽스처 → Chroma/pgvector |
| `guardrail.py` | 프롬프트 제약 + 출력 검증 | `SUPPORT_THRESHOLD`는 측정 파라미터 |
| `generation.py` | 검색→생성→검증 오케스트레이션 | `Generator` 프로토콜 — 스텁 → 실제 모델 클라이언트 |
| `service.py` | HTTP 표면 (thin) | — |
| `eval/` | 재현 가능한 채점 하네스 | [eval/README.md](eval/README.md) |

**교체는 이음매에서.** 스텁을 우회해 옆에 새 경로를 만들지 말고, 프로토콜 구현을 갈아끼우세요.

## 하면 안 되는 것

- ❌ `import backend_core` / `import api` — 독립 배포 성질이 조용히 사라집니다.
- ❌ 검색을 엔드포인트로 노출 — 파이프라인 중간에 호출자를 들이는 일입니다.
- ❌ 테스트를 통과시키려고 가드레일 끄기 — on/off 델타가 보고 지표입니다.
- ❌ 테스트에서 실제 모델 API 호출 — 비용이 들고 CI가 비결정적이 됩니다.

## 현재 상태 (스캐폴딩)

- 검색은 번들 **더미 코퍼스**에 대한 문자 bigram 매칭입니다. 임베딩 검색으로 교체 전까지
  패러프레이즈를 놓칩니다 — 안전한 실패(거절)지만 recall 실패입니다.
- 생성은 `StubGenerator`(근거 텍스트를 그대로 되돌려줌)입니다. **모델이 아닙니다.**
  실제 클라이언트로 바꾸기 전에는 생성 품질 숫자를 보고하지 마세요.
