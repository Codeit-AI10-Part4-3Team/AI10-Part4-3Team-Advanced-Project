#!/usr/bin/env bash
# GitHub 레포 하드닝: 브랜치 보호 + Merge 전략 + 라벨.
# ── 템플릿으로 리포를 생성해도 이 설정들은 복사되지 않으므로, 리포마다 1회 실행해야 합니다.
#
# 사전조건: gh auth login (해당 레포 admin 권한)
# 사용법:   bash scripts/setup-github.sh <owner>/<repo> [--solo]
#           --solo : 1인 프로젝트용 — PR 승인 요구를 끕니다 (승인자 없이는 머지 불가 방지)
# 주의:     무료 플랜의 private 리포는 브랜치 보호를 지원하지 않습니다(403).
#           이 경우 보호 단계만 건너뛰고 머지 전략·라벨은 계속 적용합니다.
#           GitHub Pro(개인)/Team(조직) 또는 public 전환 시 전부 사용 가능하며,
#           이 저장소는 public이므로 해당되지 않습니다 (전환 시 이 스크립트를 재실행).
set -euo pipefail

REPO="${1:?사용법: bash scripts/setup-github.sh <owner>/<repo> [--solo]}"
MODE="${2:-}"
SCRIPT_DIR="$(dirname "$0")"

# required_status_checks.contexts 는 ci.yml의 "잡 이름(name:)"과 정확히 일치해야 한다.
# ⚠️ paths 필터가 걸린 워크플로(notebook-check 등)는 required로 지정하지 말 것 —
#    해당 경로 변경이 없는 PR에서는 체크가 생성되지 않아 머지가 영원히 블록된다.
# ⚠️ 보조 리뷰 도구(reviewdog / SonarQube Cloud / AI 리뷰)도 같은 이유로 여기 넣지 않는다 —
#    fork PR, SONAR_TOKEN·ANTHROPIC_API_KEY 미설정, 외부 서비스 장애에서
#    체크가 생성되지 않거나 실패한다.
#    상세: docs/공통_가이드/저장소_운영.md §8.
if [[ "$MODE" == "--solo" ]]; then
  REVIEWS='null'
  echo "==> --solo: PR 승인 요구 없음 (보호 규칙의 나머지는 동일)"
else
  # require_code_owner_reviews: 루트 CODEOWNERS의 오너 배정이 끝나 true로 전환됨.
  # ⚠️ CODEOWNERS의 모든 경로에 오너가 2명 이상이어야 한다 — 단독 오너 경로는 그 오너 자신의
  #    PR을 승인할 사람이 없어 영구 블록된다(작성자 승인은 카운트되지 않음).
  REVIEWS='{ "required_approving_review_count": 1, "require_code_owner_reviews": true }'
fi

# 코드오너 리뷰 필수화 전 안전장치 — GitHub은 **기본 브랜치**의 CODEOWNERS만 읽는다.
# 파일이 아직 머지 전이거나 @핸들에 오타/write 권한 누락이 있으면 승인 가능한 오너가 0명이 되어
# 모든 PR이 영구 블록된다. 그래서 검증 실패 시 코드오너 요구만 끄고 나머지 보호는 그대로 적용한다.
if [[ "$REVIEWS" == *'"require_code_owner_reviews": true'* ]]; then
  echo "==> CODEOWNERS 검증 (기본 브랜치)"
  CODEOWNERS_OK=true
  if ! CO_ERRORS="$(gh api "repos/$REPO/codeowners/errors" -q '.errors | length' 2>/dev/null)"; then
    echo "⚠️  기본 브랜치에서 CODEOWNERS를 읽지 못했습니다 — 아직 머지되지 않았을 수 있습니다."
    CODEOWNERS_OK=false
  elif [[ "$CO_ERRORS" != "0" ]]; then
    echo "⚠️  CODEOWNERS 오류 ${CO_ERRORS}건 — 해당 규칙은 조용히 무시됩니다:"
    gh api "repos/$REPO/codeowners/errors" -q '.errors[] | "     \(.line)행: \(.message)"' 2>/dev/null || true
    echo "    대개 원인은 오타난 @핸들이거나 write 권한이 없는 계정입니다."
    CODEOWNERS_OK=false
  else
    echo "    OK — 오류 없음."
  fi

  if [[ "$CODEOWNERS_OK" != true ]]; then
    echo "    → 이대로 코드오너 리뷰를 필수화하면 승인 가능한 오너가 0명이 되어 모든 PR이 막힙니다."
    echo "      이번 실행은 코드오너 요구를 끈 채로 진행합니다. 해결 후 다시 실행하세요."
    REVIEWS='{ "required_approving_review_count": 1, "require_code_owner_reviews": false }'
  fi
fi

echo "==> main 브랜치 보호 규칙 적용"
PROTECTION_OK=true
if ! gh api -X PUT "repos/$REPO/branches/main/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - > /dev/null <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Pre-commit hooks",
      "Lint & Type Check (backend)",
      "Lint & Type Check (ai-engine)",
      "Unit tests (backend)",
      "Unit tests (ai-engine)"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": $REVIEWS,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true
}
JSON
then
  PROTECTION_OK=false
  echo "⚠️  브랜치 보호 적용 실패 — 위 오류가 HTTP 403이면 무료 플랜 private 리포 제약입니다."
  echo "    그동안은 로컬 방어선(pre-commit + pre-push pytest)이 품질 게이트를 대신합니다."
  echo "    나머지 설정(머지 전략·라벨)은 계속 적용합니다."
fi

echo "==> Merge 전략: Squash 전용 + 머지 후 브랜치 자동 삭제"
gh repo edit "$REPO" \
  --enable-squash-merge=true \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge=true

echo "==> 라벨 적용"
bash "$SCRIPT_DIR/apply-labels.sh" "$REPO"

if [[ "$PROTECTION_OK" == true ]]; then
  echo "완료: 브랜치 보호 + 머지 전략 + 라벨 적용됨."
else
  echo "완료(부분): 머지 전략 + 라벨만 적용됨 — 브랜치 보호는 미적용."
  echo "  (GitHub Pro 전환 또는 public 전환 후 이 스크립트를 다시 실행하면 적용됩니다.)"
fi
# ⚠️ 이 스크립트가 못 하는 설정이 남아 있습니다 (Discussions 카테고리 `CollaborationLog` 등).
#    남은 항목: docs/공통_가이드/착수_체크리스트.md §4 / 배경: docs/공통_가이드/저장소_운영.md §3
