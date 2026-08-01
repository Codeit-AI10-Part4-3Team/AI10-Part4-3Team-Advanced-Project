# AI10-Part4-3Team-Advanced-Project

[![CI (lint + test)](https://github.com/Codeit-AI10-Part4-3Team/AI10-Part4-3Team-Advanced-Project/actions/workflows/ci.yml/badge.svg)](https://github.com/Codeit-AI10-Part4-3Team/AI10-Part4-3Team-Advanced-Project/actions/workflows/ci.yml)

**글과 이미지를 넣으면 브랜드 스타일의 광고 소재를 만들어 주는 AI 서비스.**
이미지 생성 모델을 브랜드 데이터로 파인튜닝(LoRA)하고, GCP VM에 배포해 실제로 운영하는
것까지가 범위입니다. (코드잇 AI10 Part4 3팀 고급 프로젝트 / 2026-08-04 ~ 2026-08-31)

> ⚠️ **현재는 워킹 스켈레톤입니다.** 관통하는 경로는 아직 광고 생성이 아니라 템플릿이 갖고 온
> 질의응답이며, 외부 의존은 전부 오프라인 스텁입니다. 이 상태의 값어치는 기능이 아니라
> "폴백·가드레일·계약·CI가 실제로 동작한다"는 증명입니다 — 교체는 **이음매에서** 합니다.
> 남은 착수 작업: [docs/공통_가이드/착수_체크리스트.md](docs/공통_가이드/착수_체크리스트.md)

## 빠른 시작

```bash
bash scripts/setup-dev.sh          # Windows: powershell -File scripts\setup-dev.ps1
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./apps/backend[dev]" -e "./apps/ai-engine[dev]"
pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push
```

## 실행

```bash
uvicorn ai_engine.service:app --reload --port 8100   # AI 엔진 → :8100/docs
uvicorn api.main:app --reload --port 8000            # 백엔드   → :8000/docs

curl -X POST localhost:8000/v1/ask -H 'content-type: application/json' \
     -d '{"question":"환불은 어떻게 하나요?"}'
```

전체 스택:

```bash
cp infra/.env.example infra/.env
docker compose -f infra/docker-compose.yml up --build
```

## 품질 게이트 (커밋/PR 전 필수 — CI와 동일)

```bash
bash scripts/run-tests.sh          # ruff + mypy + pytest, 전 앱
bash scripts/run-tests.sh --tests  # pytest만
```

## 구조

```
apps/backend/      # FastAPI — src/api(얇은 라우터) + src/backend_core(도메인). 잡 수명주기·폴백
apps/ai-engine/    # 독립 배포 AI 엔진 — 카피·이미지 생성 + 가드레일, eval/ 하네스 포함
apps/frontend/     # 미스캐폴딩
training/          # 브랜드 스타일 파인튜닝 (오프라인 — apps/ 가 아닌 이유는 ADR-0002)
packages/contracts # OpenAPI 계약 (단일 원천)
infra/             # docker-compose, .env.example
e2e/               # 앱 가로지르는 관통 테스트 (HTTP 전용)
docs/              # 설계 문서, ADR, 역할 가이드/일정
```

`training/`은 `apps/`와 **파일로만** 만납니다(어댑터 가중치 + `adapter_card.json`).
양방향 import 금지이며, 그래서 학습이 깨져도 서비스는 base 모델로 뜹니다.

## 문서

| 목적 | 문서 |
|---|---|
| **착수 시 남은 작업** | [docs/공통_가이드/착수_체크리스트.md](docs/공통_가이드/착수_체크리스트.md) |
| 프로젝트 배경·온보딩 | [docs/공통_가이드/개발자_가이드.md](docs/공통_가이드/개발자_가이드.md) |
| 구현 범위 (넣지 않는 것 포함) | [docs/공통_가이드/구현_범위.md](docs/공통_가이드/구현_범위.md) |
| 전체 일정·마일스톤 | [docs/역할_일정/00-overall.md](docs/역할_일정/00-overall.md) |
| 역할 정의·겸임 조합 | [docs/역할_가이드/README.md](docs/역할_가이드/README.md) |
| 학습 파이프라인 | [training/README.md](training/README.md) |
| 환경 세팅 문제 해결 | [docs/공통_가이드/환경_세팅_가이드.md](docs/공통_가이드/환경_세팅_가이드.md) |
| PR 절차 | [docs/pr-checklist.md](docs/pr-checklist.md) |
| 리뷰 코멘트 작성법 | [docs/공통_가이드/코드_리뷰_가이드.md](docs/공통_가이드/코드_리뷰_가이드.md) |
| 저장소 설정·CI 계약 | [docs/공통_가이드/저장소_운영.md](docs/공통_가이드/저장소_운영.md) |
| 아키텍처 규칙 (사람·에이전트 공용) | [AGENTS.md](AGENTS.md) |
| 결정 기록 | [docs/adr/](docs/adr/) |

## 라이선스

MIT
