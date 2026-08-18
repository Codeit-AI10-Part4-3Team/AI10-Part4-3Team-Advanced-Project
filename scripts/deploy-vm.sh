#!/usr/bin/env bash
# GCP VM 배포 — 체크아웃을 목표 ref 로 올리고 compose 스택을 교체한 뒤 관통 확인까지 합니다.
# **VM 안에서** 실행합니다. 로컬에서 원격으로 돌릴 때는 SSH 로 감싸세요:
#
#     ssh "$ADCRAFT_VM" 'cd ~/adcraft && bash scripts/deploy-vm.sh'
#
# ⚠️ 접속 정보(외부 IP·프로젝트 ID·인스턴스명)를 이 파일에 적지 마세요 — 저장소가 public 입니다.
#    접속 경로는 docs/공통_가이드/GCP_VM_사용_가이드.md, 권한 경계는 ADR-0011 에 있습니다.
#
# ⚠️ 볼륨은 어떤 경우에도 건드리지 않습니다. `down -v` 도 `up -v` 도 없습니다 — `adgen-state`
#    에 계정과 세션이 들어 있고(ADR-0014), 지우면 되돌리는 방법은 백업뿐입니다. 이 스크립트가
#    컨테이너를 재생성해도 볼륨은 그대로 살아남습니다.
#
# ⚠️ 배포 자동화(GitHub Actions)는 성립하지 않습니다 — SA 키 발급이 조직 정책으로 막혀 있어
#    수동 SSH 경로가 유일합니다(ADR-0011). 이 스크립트는 그 수동 절차를 고정한 것입니다.
#
# 사용: bash scripts/deploy-vm.sh                 origin/main 으로 배포 (재빌드 포함)
#       bash scripts/deploy-vm.sh --ref <ref>     다른 브랜치·태그·커밋으로 배포
#       bash scripts/deploy-vm.sh --check         점검만 (fetch·빌드·기동 없음)
#       bash scripts/deploy-vm.sh --no-build      코드 갱신 없이 재기동만 (.env 변경 반영 등)
#       bash scripts/deploy-vm.sh --skip-verify   배포 후 관통 확인 생략
# ⚠️ -E(errtrace) 가 있어야 ERR 트랩이 함수 안까지 따라갑니다. 없으면 실패한 배포가 로그도
#    롤백 안내도 없이 조용히 끝납니다 — 이 스크립트의 실패 처리는 전부 함수 안에서 납니다.
set -Eeuo pipefail

# ⚠️ 전체를 함수로 감싸고 마지막 줄에서 호출합니다. 이 스크립트는 **자기 자신이 들어 있는
#    체크아웃을 갱신**하므로, 실행 도중 `git merge` 가 이 파일을 바꿉니다. bash 는 스크립트를
#    파일 오프셋 기준으로 이어 읽기 때문에, 평범하게 위에서 아래로 쓴 스크립트는 그 순간
#    엉뚱한 지점을 실행합니다. 마지막 줄까지 파싱을 끝낸 뒤 실행에 들어가면 그 창이 닫힙니다.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="infra/docker-compose.yml"
ENV_FILE="infra/.env"

# compose 의 포트 매핑과 같아야 합니다. 바꿀 일이 생기면 compose 쪽이 정본입니다.
FRONTEND_PORT="${ADCRAFT_FRONTEND_PORT:-80}"
BACKEND_PORT="${ADCRAFT_BACKEND_PORT:-8000}"

# 이 아래로 여유가 없으면 빌드 도중 죽습니다. 이미지 3종 재빌드에 수 GB 가 듭니다.
DISK_WARN_GB=10

REF="main"
MODE="deploy"
DO_BUILD=1
DO_VERIFY=1

log()  { echo "==> $*"; }
warn() { echo "  ! $*" >&2; }
die()  { echo "[중단] $*" >&2; exit 1; }

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ref)         REF="${2:?--ref 뒤에 브랜치·태그·커밋이 필요합니다}"; shift 2 ;;
      --check)       MODE="check"; shift ;;
      --no-build)    DO_BUILD=0; shift ;;
      --skip-verify) DO_VERIFY=0; shift ;;
      -h|--help)     sed -n '1,25p' "$0"; exit 0 ;;
      *)             die "모르는 인자: $1 (사용법은 --help)" ;;
    esac
  done
}

compose() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

preflight() {
  log "사전 점검"

  [[ -f "$COMPOSE_FILE" ]] || die "$COMPOSE_FILE 이 없습니다. 레포 루트에서 실행하세요."
  command -v docker >/dev/null 2>&1 || die "docker 가 없습니다."
  docker compose version >/dev/null 2>&1 || die "docker compose v2 가 없습니다."

  # ⚠️ .env 없이 뜨는 것을 막습니다. compose 가 `${ADGEN_ACCOUNTS:-}` 를 빈 문자열로 넘기면
  #    시드가 0건이 되는데, seed([]) 는 아무것도 지우지 않아 **기존 계정은 남고 기동은
  #    성공**합니다. 증상은 배포 실패가 아니라 "로그인만 이상함"으로 나옵니다
  #    (apps/backend/tests/api/test_startup.py 의 회귀 테스트가 이 시나리오입니다).
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE 이 없습니다. 이 파일 없이 배포하면 인증이 조용히 어긋납니다."
  grep -q '^ADGEN_ACCOUNTS=' "$ENV_FILE" || warn "$ENV_FILE 에 ADGEN_ACCOUNTS 가 없습니다 — 로그인이 성립하지 않습니다."
  grep -q '^ADGEN_SESSION_SECRET=' "$ENV_FILE" || warn "$ENV_FILE 에 ADGEN_SESSION_SECRET 이 없습니다 — 계정이 있으면 기동이 거부됩니다."

  # 추적 파일이 수정돼 있으면 중단합니다. "VM 에 뭐가 떠 있나"의 답이 SHA 로 성립하지 않게
  # 되고, 뒤이어 부를 `merge --ff-only` 도 그 변경을 덮거나 실패합니다.
  # (.env 처럼 ignore 된 파일은 애초에 여기 잡히지 않습니다.)
  if ! git diff --quiet HEAD --; then
    git --no-pager diff --stat HEAD -- >&2
    die "추적 파일에 커밋되지 않은 변경이 있습니다. 배포 체크아웃은 origin 과 같아야 합니다."
  fi

  # 추적되지 않는 파일은 배포를 막지 않습니다 — 손으로 올려둔 스크립트나 덤프가 흔하고,
  # 어느 커밋이 떠 있는지에는 영향을 주지 않습니다. 다만 보이게는 해 둡니다.
  local untracked
  untracked="$(git ls-files --others --exclude-standard | head -5)"
  [[ -n "$untracked" ]] && warn "추적되지 않는 파일이 있습니다: $(tr '\n' ' ' <<<"$untracked")"

  local free_gb
  free_gb="$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc '0-9' || true)"
  if [[ -n "$free_gb" && "$free_gb" -lt "$DISK_WARN_GB" ]]; then
    warn "디스크 여유 ${free_gb}GB. 재빌드 도중 실패할 수 있습니다 — 'docker image prune -f' 를 먼저 검토하세요."
  fi

  log "현재: $(git rev-parse --abbrev-ref HEAD) $(git rev-parse --short HEAD)"
}

# 체크아웃을 목표 ref 로 올립니다. 브랜치면 fast-forward 만 허용하고, 태그·커밋이면 분리 HEAD.
update_checkout() {
  log "origin 에서 가져오기"
  git fetch origin --prune --tags

  if git rev-parse --verify --quiet "origin/$REF" >/dev/null; then
    git checkout "$REF"
    # ⚠️ --ff-only. 배포 체크아웃에서 머지 커밋이 생기면 그 커밋은 어디에도 없는 코드가 되고,
    #    "VM 에 뭐가 떠 있나"를 SHA 로 답할 수 없게 됩니다.
    git merge --ff-only "origin/$REF"
  else
    git rev-parse --verify --quiet "$REF^{commit}" >/dev/null \
      || die "ref 를 찾을 수 없습니다: $REF"
    warn "origin/$REF 가 없어 분리 HEAD 로 체크아웃합니다 (롤백 용도로는 정상)."
    git checkout --detach "$REF"
  fi
}

show_changes() {
  local prev="$1"
  local now
  now="$(git rev-parse HEAD)"

  if [[ "$prev" == "$now" ]]; then
    log "코드 변경 없음 ($(git rev-parse --short HEAD)) — 재빌드·재기동만 합니다."
    return
  fi

  log "반영되는 커밋 ($(git rev-parse --short "$prev") -> $(git rev-parse --short "$now"))"
  git --no-pager log --oneline "$prev..$now" | sed 's/^/    /'

  # 계약·의존성·인프라가 바뀌었으면 확인할 것이 늘어납니다.
  local touched
  touched="$(git --no-pager diff --name-only "$prev..$now")"
  grep -q '^packages/contracts/' <<<"$touched" && warn "계약(openapi.yaml)이 바뀌었습니다 — 프론트가 같은 판을 보고 있는지 확인하세요."
  grep -q '^infra/\.env\.example$' <<<"$touched" && warn ".env.example 이 바뀌었습니다 — VM 의 infra/.env 에 새 키를 반영했는지 확인하세요."
}

bring_up() {
  local build_args=()
  [[ "$DO_BUILD" -eq 1 ]] && build_args+=(--build)

  log "스택 교체 ($([[ "$DO_BUILD" -eq 1 ]] && echo "재빌드 포함" || echo "재빌드 없음"))"
  # ⚠️ `-v` 가 없습니다. 그리고 넣지 마세요 — 계정·세션이 든 adgen-state 볼륨이 사라집니다.
  # ⚠️ `--wait` 는 헬스체크가 healthy 가 될 때까지 기다리고, 안 되면 0이 아닌 값으로 끝납니다.
  #    이것이 "배포됐는데 안 뜬 상태"를 성공으로 보고하지 않게 막는 유일한 장치입니다.
  compose up -d "${build_args[@]}" --wait
}

http_code() {
  curl -s -o /dev/null -m 10 -w '%{http_code}' "$1" 2>/dev/null || echo "000"
}

expect_code() {
  local url="$1" want="$2" label="$3" got
  got="$(http_code "$url")"
  if [[ "$got" == "$want" ]]; then
    echo "    OK   $label ($got)"
  else
    echo "    실패 $label (기대 $want, 실제 $got)"
    return 1
  fi
}

verify() {
  log "관통 확인"
  compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}" | sed 's/^/    /'

  # 상태 파일이 볼륨에 그대로 있는지. 여기서 없다고 나오면 볼륨이 갈렸다는 뜻입니다.
  if compose exec -T backend test -f /data/adgen.sqlite; then
    echo "    OK   상태 파일 /data/adgen.sqlite 보존"
  else
    warn "상태 파일이 없습니다 — 볼륨이 새로 만들어졌을 수 있습니다. 계정·세션을 확인하세요."
  fi

  # 계정이 실제로 몇 개 있는지. 0이면 로그인은 무조건 401 입니다(위 .env 함정의 최종 증상).
  local accounts
  accounts="$(compose exec -T backend python -c \
    'import sqlite3;print(sqlite3.connect("/data/adgen.sqlite").execute("select count(*) from users").fetchone()[0])' \
    2>/dev/null | tr -dc '0-9')"
  if [[ "${accounts:-0}" -gt 0 ]]; then
    echo "    OK   계정 ${accounts}건 시드됨"
  else
    warn "계정이 0건입니다 — infra/.env 의 ADGEN_ACCOUNTS 를 확인하세요."
  fi

  # 스텁인지 실물인지. 스텁의 출력은 측정값이 아닙니다(AGENTS.md '현재 상태').
  local mode
  mode="$(compose exec -T ai-engine printenv ADGEN_GENERATION_MODE 2>/dev/null | tr -d '\r\n')"
  echo "    INFO 생성 모드: ${mode:-미설정}"

  if ! command -v curl >/dev/null 2>&1; then
    warn "curl 이 없어 HTTP 확인을 건너뜁니다."
    return 0
  fi

  local ok=0
  expect_code "http://127.0.0.1:${BACKEND_PORT}/health" 200 "backend /health" || ok=1
  expect_code "http://127.0.0.1:${FRONTEND_PORT}/" 200 "frontend /" || ok=1
  # 프론트(80)를 거쳐 backend 로 넘어가는 프록시 경로까지 한 번에 봅니다. 401 이 정답입니다 —
  # 라우팅·인증·에러 계약이 셋 다 살아 있어야 이 코드가 나옵니다.
  expect_code "http://127.0.0.1:${FRONTEND_PORT}/v1/sessions" 401 "프록시 /v1/sessions (미인증)" || ok=1
  return "$ok"
}

on_failure() {
  local prev="$1"
  echo >&2
  warn "배포 실패. 최근 로그 40줄:"
  compose logs --tail 40 2>&1 | sed 's/^/    /' >&2 || true
  echo >&2
  warn "직전 상태로 되돌리려면:"
  echo "    git -C \"$ROOT\" checkout --detach $prev && bash \"$ROOT/scripts/deploy-vm.sh\" --ref $prev" >&2
}

main() {
  parse_args "$@"
  cd "$ROOT"

  preflight

  if [[ "$MODE" == "check" ]]; then
    log "점검 모드 — 아무것도 바꾸지 않습니다."
    verify || warn "확인 항목 일부가 실패했습니다."
    return 0
  fi

  local prev_sha
  prev_sha="$(git rev-parse HEAD)"
  trap 'on_failure "$prev_sha"' ERR

  update_checkout
  show_changes "$prev_sha"
  bring_up

  if [[ "$DO_VERIFY" -eq 1 ]]; then
    verify
  fi

  trap - ERR
  log "완료: $(git rev-parse --abbrev-ref HEAD) $(git rev-parse --short HEAD)"
  echo "    롤백이 필요하면: bash scripts/deploy-vm.sh --ref $(git rev-parse --short "$prev_sha")"

  # ⚠️ 브라우저 로그인은 HTTPS 종단이 붙기 전까지 성립하지 않습니다 — 세션 쿠키가 `Secure`
  #    고정인데(apps/backend/src/api/routes/auth.py) 평문 HTTP 응답의 쿠키는 브라우저가
  #    저장하지 않습니다. 이 배포의 검증 수단은 curl 입니다 (API_계약.md 8.3절).
  echo "    참고: HTTPS 종단 전까지 브라우저 로그인은 성립하지 않습니다 (curl 검증용)."
}

main "$@"
