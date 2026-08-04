# CLAUDE.md

**Claude Code**(claude.ai/code)가 이 저장소에서 작업할 때 참고하는 파일입니다.

프로젝트 맥락(무엇을 만드는가, 아키텍처, 기술 스택, 하드 제약, 품질 기준, 팀 소유, 모노레포 구조)은
도구 중립 브리프에 있습니다. 모든 에이전트 — Claude Code, Codex, Antigravity — 가 같은 원천을
읽도록 하기 위함입니다:

@AGENTS.md

`AGENTS.md`를 먼저 읽고, 그것을 정본으로 취급하세요. 아래는 **Claude Code 전용** 사항이며 공용
브리프에 넣을 내용이 아닙니다.

## Claude Code 전용 노트

- **응답 계약.** 전역 `~/.claude/CLAUDE.md`를 따르되, 이 저장소에서는 특히: 코딩 작업은 최소 출력
  (결과 + 짧은 변경 요약), 코드 주석은 영어, 문서는 한글, 불확실한 기술 주장에는 신뢰도 표기,
  승인 없는 범위 확장 금지.
- **브리프 동기화.** 프로젝트 전역 사실(아키텍처·제약·지표·팀·레포 구조)이 바뀌면 이 파일이 아니라
  `AGENTS.md`를 고치세요. 여기에는 Claude Code에만 의미 있는 내용만 추가합니다.
- **스텁을 실물로 착각하지 말 것.** 이 레포의 외부 의존은 대부분 오프라인 스텁입니다. 코드를 읽고
  "이미 동작한다"고 보고하기 전에 `AGENTS.md`의 "현재 상태" 절을 확인하세요.

## 이 레포에서 조심할 도구 사용 패턴

- **인터프리터를 먼저 확인하세요 (실측 확인된 함정).** 로컬 conda `ai` 환경에는 **다른 레포**
  (`/mnt/wsl_data/savers-project`, 같은 템플릿에서 파생)의 `ai_engine` · `backend_core`가 editable로
  설치돼 있습니다. 그 상태로 pytest를 돌리면 이 레포의 테스트가 **남의 소스**를 import해
  `ImportError` · `ValidationError`로 깨지며, 코드 결함으로 오진하기 딱 좋습니다. 테스트 실패를
  보고하기 전에 한 줄로 확인하세요:

  ```bash
  python3 -c "import ai_engine; print(ai_engine.__file__)"   # 이 레포 경로여야 정상
  ```

  이 레포는 `AGENTS.md`가 지시하는 대로 **레포 루트의 `.venv`**에서 작업합니다 (conda `ai` 아님).

- **루트에서 `pytest`·`mypy`를 실행하지 마세요.** 두 앱이 한 세션에 섞여 수집 단계에서 깨집니다.
  개별 테스트 실행법과 `eval/` 수집 규칙은 `AGENTS.md`의 "빌드 / 실행 / 테스트 > 개별 테스트 실행".

- **`e2e/`는 `run-tests.sh` 대상이 아닙니다.** 스택 기동과 외부 키가 필요하므로 별도 워크플로와
  `cd e2e && pytest`로만 실행합니다. 게이트가 통과했다고 관통 경로가 검증된 것은 아닙니다.

- **버전 상향 요청을 받으면 ruff부터 확인하세요.** ruff 버전은 네 파일이 한 쌍이고
  `scripts/check_ruff_sync.py`가 강제합니다 — 근거는 `AGENTS.md`의 "프로젝트 함정".
  Dependabot이 한 곳만 올린 PR을 다룰 때 특히 해당합니다.

## 리뷰 코멘트를 쓸 때

Claude Code가 리뷰 코멘트를 작성하는 경로는 두 가지이고 **둘 다 같은 규약**을 따릅니다:
CI의 `.github/workflows/ai-review.yml`, 그리고 이 세션에서 직접 쓰는 리뷰.

- 서식과 처리 등급(`머지 전 필수` / `이 PR에서 권장` / `후속 과제` / `참고, 조치 불필요`)의 정본:
  [docs/공통_가이드/코드_리뷰_가이드.md](docs/공통_가이드/코드_리뷰_가이드.md).
- **스타일 · 포맷 · import 정렬 · 타입은 지적하지 마세요.** ruff · mypy · reviewdog가 이미
  결정론적으로 판정합니다. 겹쳐 말하면 조언이 충돌하고 팀이 리뷰 전체를 무시하기 시작합니다.
- `ai-review.yml`은 **non-required**입니다(fork PR · 키 미등록 시 스킵). required로 승격하자는
  제안을 코드로 옮기지 마세요 — 모든 PR이 영구히 "Expected"로 막힙니다.

## 템플릿 잔재

`docs/TEMPLATE_GUIDE.md` · `docs/DESIGN_DECISIONS.md`는 **이 프로젝트가 아니라 원본 템플릿**을
설명하는 문서입니다(초기화 후 삭제 가능). 프로젝트 사실의 근거로 인용하지 말고, 판단 근거는
`AGENTS.md`와 `docs/adr/`에서 찾으세요.
