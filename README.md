# AI10-Part4-3Team-Advanced-Project

[![CI (lint + test)](https://github.com/Codeit-AI10-Part4-3Team/AI10-Part4-3Team-Advanced-Project/actions/workflows/ci.yml/badge.svg)](https://github.com/Codeit-AI10-Part4-3Team/AI10-Part4-3Team-Advanced-Project/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](apps/backend/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

**HAPPY 3팀** — 글과 이미지를 넣으면 브랜드 스타일의 광고 소재를 만들어 주는 AI 서비스.
이미지 생성은 외부 API로 하고, GCP VM에 배포해 실제로 운영하는 것까지가 범위입니다.
파인튜닝(LoRA)은 이번 범위가 아닙니다 ([ADR-0003](docs/adr/0003-이미지_생성_경로.md),
[ADR-0004](docs/adr/0004-파인튜닝_보류.md)).
(코드잇 AI10 Part4 3팀 고급 프로젝트 / 2026-08-04 ~ 2026-08-30)

> ⚠️ **워킹 스켈레톤이 2026-08-19에 관통했고, 네 이음매의 실물 분기는 2026-08-20에 전부
> 배선됐습니다.** 브라우저에서 입력부터 결과 저장까지 한 번에 지나가며 `e2e/`의 브라우저·HTTP
> 하네스가 그것을 고정합니다. `image:render`(외부 이미지 생성 API — 만화형은 칸을 따로 생성해
> 3x2로 합성) · `brief:fill` · `draft:generate` · `draft:patch` 넷 다 실물로 돌고, 카피
> 가드레일도 프롬프트 지시와 출력 검증 두 지점에 붙어 있습니다
> ([ADR-0003](docs/adr/0003-이미지_생성_경로.md) ·
> [ADR-0017](docs/adr/0017-만화형은_칸을_따로_생성해_합성한다.md) ·
> [ADR-0019](docs/adr/0019-광고_카피_가드레일은_금지_표현을_검출한다.md)).
> **다만 기본값은 여전히 `ADGEN_GENERATION_MODE=stub` 입니다** — 스텁으로 낸 품질 숫자는
> 자기 자신과의 일치율이니 측정값으로 읽지 마세요. 실측의 정본은 [docs/보고서/](docs/보고서/)이고,
> 새 경로는 옆에 새로 만들지 말고 **이음매에서** 갈아끼웁니다.
> 남은 작업: [docs/공통_가이드/착수_체크리스트.md](docs/공통_가이드/착수_체크리스트.md) ·
> 아직 안 정해진 것: [docs/기술문서/미결정_대장.md](docs/기술문서/미결정_대장.md)

[빠른 시작](#빠른-시작) ·
[실행](#실행) ·
[품질 게이트](#품질-게이트-커밋pr-전-필수--ci와-동일) ·
[구조](#구조) ·
[문서](#문서) ·
[라이선스](#라이선스)

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

curl -X POST localhost:8000/v1/auth/login -H 'content-type: application/json' \
     -d '{"loginId":"demo1","password":"..."}' -c cookies.txt
curl -b cookies.txt localhost:8000/v1/art-styles
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
apps/frontend/     # React 19 + Vite + TS (pnpm) — 로그인 + S7·S8 관통. 화면 값은 전부 backend 응답
training/          # 브랜드 스타일 파인튜닝 (ADR-0004로 보류 — 비어 있는 것이 의도된 상태. 배치 이유는 ADR-0002)
packages/contracts # OpenAPI 계약 (단일 원천)
infra/             # docker-compose, .env.example
e2e/               # 앱 가로지르는 관통 테스트 (HTTP 전용)
notebooks/         # 실험 기록 (배포 대상 아님 — 검증된 로직은 src/ 로 승격)
docs/              # 기획서·기술문서·ADR·회의록·공통 가이드·역할 가이드/일정
```

`training/`은 `apps/`와 **파일로만** 만납니다(어댑터 가중치 + `adapter_card.json`).
양방향 import 금지이며, 그래서 학습이 깨져도 서비스는 base 모델로 뜹니다.

```mermaid
flowchart LR
    FE["apps/frontend"] -->|HTTP| BE["apps/backend<br/>api + backend_core"]
    BE -->|"HTTP 계약만<br/>packages/contracts"| AE["apps/ai-engine<br/>카피 · 이미지 생성 · 가드레일"]
    AE -.->|외부 API 호출| IMG[["이미지 생성 API<br/>gpt-image-2"]]
    TR["training/<br/>LoRA 학습 - 이번 범위 아님, ADR-0004"] -.->|"파일만<br/>adapter_card.json"| AE

    BE -. "import 금지" .-> AE
    AE -. "import 금지" .-> BE

    linkStyle 4,5 stroke:#c0392b,stroke-width:2px
```

두 앱을 잇는 결합은 `packages/contracts`의 HTTP 계약뿐이고, 파이썬 import로 넘는 것은
둘 다 금지입니다(빨간 점선). 전체 배포 그림과 이음매별 상세는
[docs/공통_가이드/아키텍처.md](docs/공통_가이드/아키텍처.md) 1·4·5절이 정본입니다.

## 문서

**무엇을 만드는가** — 기획서가 "무엇을·왜", 기술문서가 "어떻게"를 답합니다.

| 목적 | 문서 |
|---|---|
| 기획서 (정본 — 뜻이 바뀌면 여기부터) | [docs/기획서/기획서.md](docs/기획서/기획서.md) |
| 스키마·API·파이프라인 (읽는 순서 포함) | [docs/기술문서/README.md](docs/기술문서/README.md) |
| **아직 안 정해진 것 전부와 잠정안** | [docs/기술문서/미결정_대장.md](docs/기술문서/미결정_대장.md) |
| 구현 범위 (넣지 않는 것 포함) | [docs/공통_가이드/구현_범위.md](docs/공통_가이드/구현_범위.md) |
| 모듈 경계·의존 방향·이음매 | [docs/공통_가이드/아키텍처.md](docs/공통_가이드/아키텍처.md) |
| HTTP 계약 (모듈 간 단일 원천) | [packages/contracts/openapi.yaml](packages/contracts/openapi.yaml) |
| 결정 기록 | [docs/adr/](docs/adr/) · [docs/회의록/](docs/회의록/) |

**어떻게 일하는가**

| 목적 | 문서 |
|---|---|
| **착수 시 남은 작업** | [docs/공통_가이드/착수_체크리스트.md](docs/공통_가이드/착수_체크리스트.md) |
| 프로젝트 배경·온보딩 | [docs/공통_가이드/개발자_가이드.md](docs/공통_가이드/개발자_가이드.md) |
| 전체 일정·마일스톤 | [docs/역할_일정/00-overall.md](docs/역할_일정/00-overall.md) |
| 역할 정의·겸임 조합 | [docs/역할_가이드/README.md](docs/역할_가이드/README.md) |
| 리스크와 감지·대응 | [docs/공통_가이드/리스크.md](docs/공통_가이드/리스크.md) |
| PR 절차 | [docs/pr-checklist.md](docs/pr-checklist.md) |
| 리뷰 코멘트 작성법 | [docs/공통_가이드/코드_리뷰_가이드.md](docs/공통_가이드/코드_리뷰_가이드.md) |
| 제출물 문체·문자 규칙 | [docs/공통_가이드/문서_작성_규약.md](docs/공통_가이드/문서_작성_규약.md) |
| 팀 메신저 메시지 서식 | [docs/공통_가이드/메신저_규약.md](docs/공통_가이드/메신저_규약.md) |
| 아키텍처 규칙 (사람·에이전트 공용) | [AGENTS.md](AGENTS.md) |

**환경·학습·인프라**

| 목적 | 문서 |
|---|---|
| 환경 세팅 문제 해결 | [docs/공통_가이드/환경_세팅_가이드.md](docs/공통_가이드/환경_세팅_가이드.md) |
| 학습 파이프라인 | [training/README.md](training/README.md) |
| GCP VM 접속·사용법 | [docs/공통_가이드/GCP_VM_사용_가이드.md](docs/공통_가이드/GCP_VM_사용_가이드.md) |
| VM 프로비저닝 실측 기록 | [infra/README.md](infra/README.md) |
| 저장소 설정·CI 계약 | [docs/공통_가이드/저장소_운영.md](docs/공통_가이드/저장소_운영.md) |

근거로 쓸 수 있는 문서와 쓸 수 없는 문서(협업일지·DM·구두 합의)의 구분은
[AGENTS.md](AGENTS.md)의 "근거 자료 규칙"이 정본입니다.

## 라이선스

MIT
