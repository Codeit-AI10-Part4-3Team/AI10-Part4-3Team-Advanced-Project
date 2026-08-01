#!/usr/bin/env bash
# 모든 파이썬 앱의 품질 게이트를 CI와 동일한 순서/기준으로 실행합니다.
# pre-commit의 pre-push 훅이 이 스크립트를 호출하므로, CI와 어긋나지 않게 함께 수정하세요.
#
# ⚠️ e2e/는 의도적으로 제외합니다 — 스택 기동과 외부 API 키가 필요해 push마다 돌릴 수 없습니다.
#    관통 테스트는 별도 워크플로(.github/workflows/e2e.yml, non-required)와
#    `cd e2e && pytest`로 실행하세요.
#
# 사용: bash scripts/run-tests.sh          (lint + type + test 전부)
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

echo "완료: ${APPS[*]}"
