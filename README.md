# ai-team-project-template

[![CI (lint + test)](https://github.com/Yopkigom/ai-team-project-template/actions/workflows/ci.yml/badge.svg)](https://github.com/Yopkigom/ai-team-project-template/actions/workflows/ci.yml)

**여러 명이 함께 하는 AI 프로젝트**용 GitHub 템플릿. 모노레포 골격(백엔드 + 독립 배포 AI 엔진 +
계약 + E2E) · 품질 게이트(CI·pre-commit·gitleaks) · 협업 규약(.github/) · 문서 체계(설계·ADR·역할)를
한 번에 제공하고, **요청 하나가 전 구간을 관통하는 워킹 스켈레톤**이 이미 들어 있습니다.

실전 팀 프로젝트에서 검증된 구성을 일반화한 것입니다. 설계 근거와 원본 대비 변경점은
[docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md)에 있습니다.

> **1인·소규모 단일 앱 프로젝트**라면 더 가벼운
> [ai-project-template](https://github.com/Yopkigom/ai-project-template)(단일 패키지 + FastAPI 골격)이
> 적합합니다. 이 템플릿은 **역할이 나뉜 팀 + 앱이 둘 이상**일 때를 위한 것입니다.

## 빠른 시작

```bash
# 1) GitHub에서 "Use this template" → 새 리포 생성 → clone
git clone https://github.com/<owner>/<repo>.git && cd <repo>

# 2) 프로젝트 이름으로 초기화 (플레이스홀더 일괄 치환 + 스크립트 자신 삭제)
python3 scripts/init_template.py --name my-service --owner <owner>

# 3) 개발 환경
bash scripts/setup-dev.sh          # Windows: powershell -File scripts\setup-dev.ps1
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./apps/backend[dev]" -e "./apps/ai-engine[dev]"
pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push

# 4) 관통 확인 — ai-engine을 꺼도 200 + official_fallback 이 돌아옵니다
bash scripts/run-tests.sh
docker compose -f infra/docker-compose.yml up --build

# 5) 리포 설정 재적용 — 템플릿은 "파일"만 복사하고 "설정"은 복사하지 않습니다!
gh auth login
bash scripts/setup-github.sh <owner>/<repo>          # 팀 프로젝트
bash scripts/setup-github.sh <owner>/<repo> --solo   # 1인 프로젝트
```

전체 절차·주의사항·운용 방법: **[docs/TEMPLATE_GUIDE.md](docs/TEMPLATE_GUIDE.md)**

## 제공하는 것

| 영역 | 내용 |
|---|---|
| 모노레포 | `apps/`(backend·ai-engine·frontend) + `packages/contracts` + `infra` + `e2e`, 앱별 editable 설치 |
| 워킹 스켈레톤 | 요청 → 도메인 → 검색 → 가드레일 생성 → 응답/폴백 전 구간 관통 (외부 의존은 전부 오프라인 스텁) |
| AI 엔진 | 독립 배포 단위 — 자체 Dockerfile·README, `Retriever`/`Generator` 프로토콜이 교체 이음매 |
| 가드레일 | 프롬프트 제약 + **출력 검증** 2단, on/off 대조군 실행 지원 (환각 억제율 측정용) |
| 평가 하네스 | `apps/ai-engine/eval/` — 순수 지표 함수 + 골든셋 + 그 지표 함수의 단위 테스트 |
| 품질 게이트 | ruff · mypy · pytest — CI와 pre-commit이 동일 기준, `scripts/run-tests.sh`로 로컬 재현 |
| 시크릿 방어 | gitleaks(훅 + CI 전체 트리) + detect-private-key + `.gitignore` 패턴 3중 |
| 계약 | OpenAPI 단일 원천 + 스펙 검증 CI + 앱별 계약 준수 테스트 |
| 협업 규약 | 이슈/PR/Discussion 템플릿, 라벨, PR 체크리스트, CODEOWNERS 골격 |
| 리포 설정 | 브랜치 보호·머지 전략·라벨 재적용 스크립트 (`scripts/setup-github.sh`) |
| 환경 진단 | `scripts/setup-dev.sh`/`.ps1` + `dev_env.py` — 설정이 실제로 등록됐는지까지 검증 |
| 문서 체계 | 설계 가이드 · ADR(양식 + 예시) · 역할 가이드/일정 골격 |
| 에이전트 가이드 | `AGENTS.md`(도구 중립 브리프) + `CLAUDE.md`(포인터) |

## 구조

```
├── apps/
│   ├── backend/        # FastAPI — src/api(얇은 라우터) + src/backend_core(도메인, FastAPI 무의존)
│   ├── ai-engine/      # 독립 배포 — 검색·가드레일·생성 + eval/ 하네스
│   └── frontend/       # 미스캐폴딩 (README에 함정 정리)
├── packages/contracts/ # OpenAPI 스펙 (단일 원천)
├── infra/              # docker-compose, .env.example
├── e2e/                # 앱 가로지르는 관통 테스트 (HTTP 전용, non-required CI)
├── notebooks/          # 실험 (검증되면 apps/<app>/src 로 이전)
├── scripts/            # init_template · setup-dev · run-tests · setup-github · apply-labels
├── docs/               # 공통_가이드 · 역할_가이드 · 역할_일정 · adr · pr-checklist
└── .github/            # CI 6종(required 5 / non-required), 템플릿, labels, dependabot
```

## 라이선스

MIT
