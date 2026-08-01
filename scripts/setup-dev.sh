#!/usr/bin/env bash
# 개발 환경 점검·복구 진입점 (macOS · Linux · WSL · Git Bash).
# Windows PowerShell 사용자는 scripts/setup-dev.ps1 을 쓰세요 — 두 래퍼는 같은 코어를 호출합니다.
#
# ⚠️ 검사 로직은 여기 두지 마세요. 레지스트리는 scripts/dev_env.py 한 곳에만 있습니다
#    (셸/PowerShell 두 벌로 나뉘는 순간 반드시 드리프트가 납니다).
#
# 사용: bash scripts/setup-dev.sh                 점검 → 항목별 확인 후 복구 → 로컬 CI
#       bash scripts/setup-dev.sh --check         진단만 (변경 없음)
#       bash scripts/setup-dev.sh --yes           확인 프롬프트 없이 복구
#       bash scripts/setup-dev.sh --skip-tests    마지막 run-tests.sh 생략
#       bash scripts/setup-dev.sh --mode docker   컨테이너로 개발 (파이썬 항목을 경고로 강등)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PY=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [[ -z "$PY" ]]; then
  echo "[E02] Python을 찾을 수 없습니다. 3.12 이상을 설치한 뒤 다시 실행하세요."
  echo "      대처: docs/공통_가이드/환경_세팅_가이드.md#e02"
  exit 2
fi

exec "$PY" "$ROOT/scripts/dev_env.py" "$@"
