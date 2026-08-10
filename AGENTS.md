# AGENTS.md

모든 코딩 에이전트(Claude Code, Codex, Antigravity …)와 사람이 공유하는 **프로젝트 브리프**이며,
**전역 규칙의 단일 원천**입니다. 특정 디렉토리에만 유효한 규칙은 그 디렉토리의 AGENTS.md에,
도구별 노트는 각 도구 파일(`CLAUDE.md` 등)에 두고 여기 내용을 복제하지 않습니다.

> ⚠️ **아래 경로의 파일을 수정하기 전에 그 디렉토리의 `AGENTS.md`를 먼저 읽으세요**
> (중첩 파일을 자동으로 읽지 않는 도구를 위한 명시 규칙입니다):
> `apps/backend/` · `apps/ai-engine/` · `apps/frontend/` · `training/` · `e2e/`

## 프로젝트 개요

- 글(제품·브랜드 정보)과 이미지(레퍼런스·제품컷)를 입력받아 **브랜드 스타일의 광고 소재(이미지+카피)**를
  생성하는 서비스. 이미지 생성 모델을 브랜드 데이터로 LoRA 파인튜닝하고 GCP GPU VM 1대에 배포합니다.
- 푸는 문제: 디자이너를 두기 어려운 소상공인·소규모 마케팅 팀이 외주 없이 **일관된 브랜드 톤**의
  소재를 분 단위로 뽑는 것.
- 마일스톤(2026, 실작업 22일): 착수 08-04 → 계약 동결 08-08(`openapi.yaml`이 광고 계약으로 교체) →
  중간 점검 08-17(파인튜닝 1회전 + VM GPU 추론 관통) → 배포 08-24 → 제출 08-31.
  상세: [docs/역할_일정/00-overall.md](docs/역할_일정/00-overall.md).
- **저장소는 public** — 키·브랜드 원본 이미지·고객 데이터는 어떤 경우에도 커밋 대상이 아닙니다.
- 5명이 7역할 겸임. 배정 표·소유 경로: [개발자_가이드.md](docs/공통_가이드/개발자_가이드.md) 5절 +
  `CODEOWNERS`. 배정이 정해지면 그 표 · `CODEOWNERS` · `docs/역할_가이드/`를 **같은 PR에서** 함께
  채우세요 — 셋이 어긋나면 리뷰 자동 배정이 오류 없이 조용히 죽습니다.

## 아직 확정되지 않은 것 (TBD)

확정 전에는 관련 코드를 쓰지 말고 **계약과 문서를 먼저** 정합니다. TBD가 남은 항목에 대해
에이전트는 추측으로 코드를 씁니다.

- base 이미지 생성 모델(SDXL/FLUX/…) — 라이선스가 함께 걸리므로 ADR로 남길 것.
  **하드웨어 예산은 이미 확정**입니다(가용 VRAM **22.5GB** · 호스트 RAM 16GB · 디스크 100GB,
  2026-08-10 실측) — 넘는 후보는
  검토 대상이 아닙니다: [ADR-0011](docs/adr/0011-배포_환경_스펙과_권한_경계.md)
- 카피 생성 경로(외부 LLM API / 로컬 모델) — 지연·키 관리가 갈립니다 (비용은 학원 부담)
- 브랜드 데이터셋 출처와 권리 범위 · 품질 지표 목표치

**GCP VM 스펙은 TBD가 아닙니다.** 학원이 배정한 고정값이며 우리가 고를 수 있는 것은 OS뿐입니다
([ADR-0011](docs/adr/0011-배포_환경_스펙과_권한_경계.md)). 상향 요청을 전제로 코드를 쓰지 마세요.

## 근거 자료 규칙 (Source of Truth)

결정의 근거는 아래 표의 정의를 따른다. 표에 없는 자료는 근거가 아니다.

| 등급 | 대상 | 효력 |
|---|---|---|
| 근거 | `docs/기획서/` `docs/기술문서/` `docs/공통_가이드/` `docs/adr/` **루트·디렉토리별 `AGENTS.md`** `CLAUDE.md` `packages/contracts/openapi.yaml` `CODEOWNERS` | 그대로 따른다 |
| 조건부 근거 | 이슈 본문·코멘트, PR 리뷰 코멘트 | **해당 이슈/PR 범위의 변경**에만 효력 |
| 비근거 | `docs/TEMPLATE_GUIDE.md` `docs/DESIGN_DECISIONS.md`, Discussions 협업일지, DM, 구두·회의 중 발언 | 정황 정보. 결정으로 읽지 않는다 |

1. 협업일지는 개인 기록이다 — "~하기로 함", "~할 예정"도 결정이 아니다.
2. 미결정 대장 항목의 **확정** 근거는 회의록뿐(기획서 14.3). 소관자 코멘트로는 잠정안만 갱신한다.
3. 비근거 자료가 근거 문서와 어긋나면 어디에도 반영하지 않고 **발견 사실만 보고**한다.
   반영은 사용자의 명시적 요청·동의가 있을 때만.

이유: 근거 밖 내용을 반영하면 정본이 둘이 되어 문서 전체가 신뢰를 잃는다.

## 현재 상태: 워킹 스켈레톤

- 코드는 동작하는 서비스가 아니라 **워킹 스켈레톤**입니다. 외부 의존은 전부 이름 붙은 이음매 뒤의
  오프라인 스텁 — **스텁을 측정값으로 읽지 마세요.** 이 상태의 품질 숫자는 자기 자신과의 일치율입니다.
- 관통 도메인은 아직 광고 생성이 아니라 템플릿의 질의응답(`/v1/ask` → `/v1/generate`)입니다.
  광고 생성으로 바꿀 때는 경로를 옆에 새로 만들지 말고 **같은 이음매에서 갈아끼웁니다** — 우회하면
  스켈레톤이 검증하던 성질(폴백·가드레일·계약)이 조용히 사라집니다.
  이음매 목록: [아키텍처.md](docs/공통_가이드/아키텍처.md) 5절.
- 교체 순서: 계약(`packages/contracts/openapi.yaml`) → 스키마 → 구현 → 테스트.
  **계약 없이 먼저 짜인 구현은 리뷰 대상이 아닙니다.**

## 설계 제약 (편의상 "단순화"하면 안 되는 것)

- **근거 기반 생성** — 카피는 입력된 제품 정보에만 근거합니다. 없는 효능·수치·수상 이력을 지어내면
  표시광고법상 허위·과장 광고이고, 가드레일 on/off 델타 자체가 보고 지표라 우회하면 측정이 무효가 됩니다.
- **열화는 자동화 생략 하나뿐이고, 나머지는 명시적으로 실패합니다** — `brief:fill`이 죽으면
  자동 채움을 건너뛰고 사용자 입력으로 진행하며 그 사실을 `messageMode: degraded`로 드러냅니다.
  시안 생성·부분 교체·렌더에는 폴백이 없습니다(카피는 제품마다 달라 사전 승인 응답이 성립하지
  않습니다). 조용히 실패하거나 모델 없이 카피를 지어내는 경로는 둘 다 금지:
  [ADR-0005](docs/adr/0005-열화_폴백은_자동화_생략으로_한정.md).
- **학습과 서빙은 파일로만 만납니다** — `training/` ↔ `apps/` 양방향 import 금지. 넘기는 것은
  어댑터 가중치 + `adapter_card.json`뿐. 상세: [training/AGENTS.md](training/AGENTS.md).
- **GPU는 한 대** — 학습·추론이 동시에 VRAM을 요구하면 둘 다 OOM. 운영 시간 분할 또는 명시적
  VRAM 예산 분할이 필요하며, "일단 돌려보자"는 서비스 다운으로 직결됩니다.
- **이미지 생성은 동기 HTTP 금지** — 한 장에 수십 초라 요청을 붙들면 타임아웃에 먼저 걸립니다.
  잡 접수 → 폴링/스트리밍 조회 형태이며, 이 결정은 계약에 먼저 반영됩니다.
- **입력·생성 이미지는 개인정보·저작물일 수 있음** — 보관 기간·접근 범위 없이 디스크에 쌓지 마세요.
  학습 데이터 권리 대장은 `training/data/README.md` — 기록 없는 데이터로는 배포 판단을 못 내립니다.

## 품질 기준

품질은 사람 리뷰가 아니라 **재현 가능한 스크립트**로 증명합니다. 지표 표와 측정 규칙(지표 함수는
순수 함수, 채점 모델 ≠ 생성 모델, 스타일 일치도는 사람 평가와의 상관 확인 후에만 대리 지표):
[개발자_가이드.md](docs/공통_가이드/개발자_가이드.md) 4절 + [eval/README.md](apps/ai-engine/eval/README.md).
목표치는 실측 전까지 전부 **가설**이며, 실측 전에 적은 숫자는 근거가 아니라 희망입니다.

## 명명 규약

- 기획·설계 **문서와 그 폴더는 한글**(다단어는 `A_B`), ADR 파일명은 `NNNN-한글_제목.md`.
- **그 외 전부 영어, 예외 없음** — 코드·설정·에셋·CI 경로는 빌드 도구·import 문·셸이 소비하므로
  비ASCII 경로 세그먼트는 판단 대상이 아니라 결함입니다.
  합의된 영어 예외: `CLAUDE.md` `AGENTS.md` `README` `docs/pr-checklist.md`.
- 다이어그램은 ` ```mermaid ` 코드 블록(diff에 보이게). 디렉토리 트리는 일반 코드 블록 유지.
- **제출물은 경어체 + 키보드로 칠 수 있는 문자만** — 기획서·기술문서·ADR·리뷰 코멘트가 대상이고
  `AGENTS.md`·`README`·가이드류는 대상이 아닙니다(PDF 변환에서 깨지는 문자가 문제이기 때문).
  적용 범위 표와 치환 표, 점검 스크립트: [문서_작성_규약.md](docs/공통_가이드/문서_작성_규약.md).
- **팀 메신저에 보낼 텍스트는 다른 규약을 씁니다** — 첫 줄이 결론, 상세는 링크 뒤, 5줄 이내:
  [메신저_규약.md](docs/공통_가이드/메신저_규약.md). 메신저에서 오간 말은 근거가 아닙니다(위 표).

## 저장소 구조

전체 트리와 설명: [개발자_가이드.md](docs/공통_가이드/개발자_가이드.md) 6절. 헷갈리기 쉬운 배치만:

- `training/`은 `apps/` 밖 — 상시 기동 배포 단위가 아님 ([ADR-0002](docs/adr/0002-학습_파이프라인_배치.md))
- `eval/`은 `apps/ai-engine/` 안 — 채점 대상과 함께 버전이 움직여야 함
- `CODEOWNERS`는 레포 루트 한 곳만 — GitHub이 한 곳만 읽으므로 사본 금지
- 루트 `pyproject.toml`은 툴링 전용(ruff) — 루트에서 `pip install .`은 실수
- `apps/frontend/`는 미스캐폴딩 — 시작 전 그 `AGENTS.md`와 README 필독(루트 `.gitignore` 함정)

## 빌드 / 실행 / 테스트

```bash
bash scripts/setup-dev.sh          # Windows: powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./apps/backend[dev]" -e "./apps/ai-engine[dev]"
pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push

uvicorn api.main:app --reload --port 8000              # backend    → :8000/docs
uvicorn ai_engine.service:app --reload --port 8100     # ai-engine  → :8100/docs

bash scripts/run-tests.sh          # 품질 게이트: ruff + mypy + pytest 전 앱 (= CI)
```

- ai-engine을 꺼도 `/v1/ask`가 **200 + `messageMode: official_fallback`** 을 돌려주면 정상 —
  설계된 열화이지 버그가 아닙니다.
- ⚠️ **레포 루트에서 `pytest`·`mypy` 금지** — 두 앱이 한 세션에 섞여 수집이 깨집니다.
  **앱 디렉토리를 cwd로** 실행하세요. 개별 실행 예시는 각 앱의 `AGENTS.md`.
- import는 `from api import …` / `import backend_core` / `from ai_engine import …` —
  **`src.` 접두어 금지**(런타임에 깨지는데 린트가 못 잡습니다).
- 무거운 의존(LangChain·벡터 DB·지오 라이브러리)은 앱의 optional extra로 — CI는 core+`dev`만 설치.
- **테스트의 외부 API 호출은 반드시 목** — 비용이 들고 CI가 비결정적이 됩니다.

## 아키텍처 경계 (위반은 스타일이 아니라 설계 결함)

의존 방향 다이어그램의 정본: [아키텍처.md](docs/공통_가이드/아키텍처.md) 4절. 규칙:

- **`training/` ↔ `apps/` import 금지(양방향)** · **`backend_core` → `api` import 금지** ·
  **`apps/ai-engine` ↔ `apps/backend` import 금지** — 두 앱의 허용된 결합은
  `packages/contracts`의 HTTP 계약뿐이며, 금지선을 넘는 import 한 줄이 이 레포 구조가 존재하는
  이유("독립 배포 가능한 AI 모듈")를 조용히 없앱니다.
- **라우터는 얇게**: 요청 검증 → 도메인 호출 → 응답 매핑.
- **구현보다 계약이 먼저**: 모듈 간 인터페이스는 `packages/contracts`에 먼저 존재합니다.
  구두 합의는 계약이 아닙니다.

## 새 코드는 어디에

- HTTP/라우팅 → `apps/<app>/src/api/`(backend) 또는 서비스 모듈(ai-engine) /
  도메인 → `backend_core` · `ai_engine`
- 학습 코드·설정 → `training/` / 평가 자산 → `apps/ai-engine/eval/` /
  실험 → `notebooks/`(import 금지, 검증된 로직은 `src/`로 승격)
- 테스트 → `apps/<app>/tests/`(`src/` 구조를 `test_<module>.py`로 미러링) /
  앱을 가로지르는 E2E → **`e2e/`만** — `apps/*/tests/`에 두면 안 되는 이유: [e2e/AGENTS.md](e2e/AGENTS.md)

## 전역 함정 (이유 없는 규칙은 무시당하므로 이유를 함께)

- **파이썬 환경은 이 저장소 전용** — 같은 템플릿에서 파생된 다른 레포와 최상위 모듈명(`api` ·
  `backend_core` · `ai_engine`)이 겹쳐, 공용 env에서는 이 레포의 테스트가 **남의 소스를 import한 채**
  돕니다. 증상이 `ImportError`·`ValidationError`라 코드 결함으로 오진하기 쉽습니다(실측 사고 있음).
  진단·해결: [환경_세팅_가이드.md#e04](docs/공통_가이드/환경_세팅_가이드.md#e04).
- **시크릿은 일방통행 문** — 커밋된 키는 revert가 아니라 폐기·재발급. 키는 `infra/.env`(ignored),
  커밋은 `.env.example`(이름만). gitleaks의 pre-commit 훅과 required CI 스캔은 **한 쌍**입니다 —
  훅은 staged만 보고, CI를 지우면 훅 미설치자를 아무도 못 막습니다.
- **`.gitignore`는 루트 앵커 + 파일 화이트리스트 방식** — git은 무시된 디렉토리 안 파일을 못
  살립니다. 커밋해야 할 데이터 파일을 새로 들이면 `!` 화이트리스트 줄도 함께 — 아니면 조용히 사라집니다.
- **ruff 버전은 네 파일이 한 쌍** — `.pre-commit-config.yaml` rev · 두 앱의 dev extra `ruff==` ·
  reviewdog `RUFF_VERSION`. `scripts/check_ruff_sync.py`가 강제하며, 상향은 네 파일을 **같은 PR**에서.
  배경(실제 드리프트 사고 #2): [저장소_운영.md](docs/공통_가이드/저장소_운영.md) 4-1절.
- **required 체크는 매트릭스 잡 이름이 `scripts/setup-github.sh`와 정확히 일치**해야 하고,
  required 워크플로에 **`paths:` 필터 금지** — 어기면 체크가 생성되지 않아 모든 PR이 "Expected"로
  영구 대기합니다(프론트엔드 CI가 별도 non-required인 이유).
- 노트북은 nbstripout이 출력을 제거 — 출력 포함 커밋은 영구 `modified`로 남으니 발견 즉시 재커밋.
- staged 변경을 둔 채 `git pull` 금지 — autostash 복원 실패로 작업 유실 가능. 유실 시 `git fsck --lost-found`.

## 협업 / Git

- `main` 보호: 피처 브랜치 → PR → **squash merge** → 브랜치 자동 삭제.
  절차: [docs/pr-checklist.md](docs/pr-checklist.md).
- 리뷰 코멘트 서식·처리 등급의 정본: [코드_리뷰_가이드.md](docs/공통_가이드/코드_리뷰_가이드.md).
  **스타일·포맷·타입은 지적 금지** — ruff·mypy·reviewdog가 이미 결정론적으로 판정하며, 겹쳐 말하면
  팀이 리뷰 전체를 무시하기 시작합니다.
- CI와 pre-commit은 **의도적으로 같은 규칙** — 어긋나면 우회하지 말고 드리프트를 고치세요.
- 레포 설정(브랜치 보호·라벨)은 GitHub 쪽에만 존재해 diff에 안 보입니다 — `scripts/setup-github.sh`가
  재적용. 상세: [저장소_운영.md](docs/공통_가이드/저장소_운영.md).
- 아키텍처 결정은 내려지는 즉시 `docs/adr/`에 — 문서화되지 않은 결정은 팀이 잃어버린 결정입니다.
