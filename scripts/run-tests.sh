#!/usr/bin/env bash
# 모든 파이썬 앱의 품질 게이트를 CI와 동일한 순서/기준으로 실행합니다.
# pre-commit의 pre-push 훅이 이 스크립트를 호출하므로, CI와 어긋나지 않게 함께 수정하세요.
#
# ⚠️ e2e/는 의도적으로 제외합니다 — 스택 기동과 외부 API 키가 필요해 push마다 돌릴 수 없습니다.
#    관통 테스트는 별도 워크플로(.github/workflows/e2e.yml, non-required)와
#    `cd e2e && pytest`로 실행하세요.
#
# ⚠️ CI의 required 체크는 다섯 개이고 잡 정의는 셋입니다
#    (`Pre-commit hooks` / `Lint & Type Check` x2 / `Unit tests` x2).
#    아래 앱 순회는 뒤의 둘만 재현하므로, 전체 모드는 마지막에 pre-commit 훅 전량을 함께
#    돌립니다 — 그것 없이는 scripts·e2e(현재) 와 training·packages(예정) 의 파이썬,
#    문서 위생, ruff 핀 동기화가 로컬에서 아예 검사되지 않아 "로컬 초록 + CI 빨강"이 남습니다.
#
# ⚠️ 로컬에서 재현되지 않는 CI 검사는 gitleaks 전체 트리 스캔 하나입니다 — 훅의 gitleaks는
#    entry가 `--staged` 고정이라 `--all-files`에서 아무것도 보지 않고, ci.yml의 별도 스텝이
#    트리 전체를 훑습니다. 둘은 한 쌍입니다.
#
# 사용: bash scripts/run-tests.sh          (lint + type + test + pre-commit 훅 전량)
#       bash scripts/run-tests.sh --tests  (pytest만 — pre-push 훅이 쓰는 모드)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPS=(backend ai-engine)
MODE="${1:-}"

cd "$ROOT"

for app in "${APPS[@]}"; do
  echo "==> apps/$app"
  if [[ "$MODE" != "--tests" ]]; then
    # ruff는 루트 pyproject.toml의 [tool.ruff]를 상위 탐색으로 자동 채택한다.
    ruff check "apps/$app"
    ruff format --check "apps/$app"
    # ⚠️ mypy는 앱 디렉토리를 cwd로 실행해야 해당 앱의 [tool.mypy]를 집는다.
    (cd "apps/$app" && mypy)
  fi
  (cd "apps/$app" && pytest -q)
done

if [[ "$MODE" != "--tests" ]]; then
  echo "==> pre-commit (전 파일 — CI의 'Pre-commit hooks' 잡과 같은 검사)"
  # 인터프리터 모듈을 PATH보다 먼저 본다: conda + venv가 함께 있는 PC에서 `which pre-commit`이
  # 다른 환경의 사본을 집는 일이 잦고, 그 사본은 이 체크아웃의 훅 환경을 쓰지 않는다.
  if python3 -c "import pre_commit" >/dev/null 2>&1; then
    python3 -m pre_commit run --all-files --show-diff-on-failure
  elif command -v pre-commit >/dev/null 2>&1; then
    pre-commit run --all-files --show-diff-on-failure
  else
    echo "    pre-commit 미설치 — 건너뜁니다. CI는 이 검사를 required로 돌립니다:"
    echo "    bash scripts/setup-dev.sh   (E06·E07·E08·E10 복구)"
  fi
fi

echo "완료: ${APPS[*]}"
