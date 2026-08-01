# {{GITHUB_REPO}}

[![CI (lint + test)](https://github.com/{{GITHUB_OWNER}}/{{GITHUB_REPO}}/actions/workflows/ci.yml/badge.svg)](https://github.com/{{GITHUB_OWNER}}/{{GITHUB_REPO}}/actions/workflows/ci.yml)
<!-- ⚠️ private 리포에서는 워크플로 배지가 외부 임베드 불가라 렌더되지 않습니다 —
     위 배지 줄을 삭제하거나 public 전환 시 사용하세요 (docs/공통_가이드/저장소_운영.md §6). -->

> TODO: 프로젝트 한 줄 소개를 작성하세요.

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
apps/backend/      # FastAPI — src/api(얇은 라우터) + src/backend_core(도메인)
apps/ai-engine/    # 독립 배포 AI 엔진 — 검색 + 가드레일 생성, eval/ 하네스 포함
apps/frontend/     # 미스캐폴딩
packages/contracts # OpenAPI 계약 (단일 원천)
infra/             # docker-compose, .env.example
e2e/               # 앱 가로지르는 관통 테스트 (HTTP 전용)
docs/              # 설계 문서, ADR, 역할 가이드/일정
```

## 문서

| 목적 | 문서 |
|---|---|
| 프로젝트 배경·온보딩 | [docs/공통_가이드/개발자_가이드.md](docs/공통_가이드/개발자_가이드.md) |
| 환경 세팅 문제 해결 | [docs/공통_가이드/환경_세팅_가이드.md](docs/공통_가이드/환경_세팅_가이드.md) |
| PR 절차 | [docs/pr-checklist.md](docs/pr-checklist.md) |
| 저장소 설정·CI 계약 | [docs/공통_가이드/저장소_운영.md](docs/공통_가이드/저장소_운영.md) |
| 아키텍처 규칙 (사람·에이전트 공용) | [AGENTS.md](AGENTS.md) |
| 결정 기록 | [docs/adr/](docs/adr/) |

## 라이선스

MIT
