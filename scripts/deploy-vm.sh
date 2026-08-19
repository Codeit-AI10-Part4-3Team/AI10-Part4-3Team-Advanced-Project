#!/usr/bin/env bash
# GCP VM 배포 — 체크아웃을 목표 ref 로 올리고 compose 스택을 교체한 뒤 관통 확인까지 합니다.
# **VM 안에서** 실행합니다. 로컬에서 원격으로 돌릴 때는 SSH 로 감싸세요:
#
#     ssh "$ADCRAFT_VM" 'cd /srv/adcraft/app && bash scripts/deploy-vm.sh'
#
# ⚠️ 배포 체크아웃은 `/srv/adcraft/app` 하나입니다 — 개인 홈이 아닙니다. 홈에 두면 그 계정이
#    빠질 때 배포 경로가 함께 사라지고, 다른 사람은 남의 홈을 들여다볼 수도 고칠 수도 없습니다.
#    `/srv/adcraft` 는 `adcraft` 그룹 소유의 공용 경로이고(GCP_VM_사용_가이드.md 6절),
#    `exp` 와 형제로 `app` 을 둡니다. 이 스크립트는 그 경로 밖에서 실행되면 중단합니다 —
#    아래 check_deploy_root 참고.
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
#       bash scripts/deploy-vm.sh --no-build      체크아웃·이미지 그대로 재기동 (.env 변경 반영)
#       bash scripts/deploy-vm.sh --skip-verify   배포 후 관통 확인 생략
#       bash scripts/deploy-vm.sh --allow-any-root  배포 경로 검사를 끕니다 (아래 참고)
#
# ⚠️ --no-build 는 체크아웃을 갱신하지 않습니다(--ref 와 함께 쓸 수 없습니다). 코드를 옮기면서
#    이미지를 그대로 두면 도는 코드와 `git rev-parse HEAD` 가 어긋납니다.
# ⚠️ -E(errtrace) 가 있어야 ERR 트랩이 함수 안까지 따라갑니다. 없으면 실패한 배포가 로그도
#    롤백 안내도 없이 조용히 끝납니다 — 이 스크립트의 실패 처리는 전부 함수 안에서 납니다.
set -Eeuo pipefail

# ⚠️ 전체를 함수로 감싸고 마지막 줄에서 호출합니다. 이 스크립트는 **자기 자신이 들어 있는
#    체크아웃을 갱신**하므로, 실행 도중 `git merge` 가 이 파일을 바꿉니다. bash 는 스크립트를
#    파일 오프셋 기준으로 이어 읽기 때문에, 평범하게 위에서 아래로 쓴 스크립트는 그 순간
#    엉뚱한 지점을 실행합니다. 마지막 줄까지 파싱을 끝낸 뒤 실행에 들어가면 그 창이 닫힙니다.

# ⚠️ `-P` 로 심볼릭 링크를 풀어 실제 경로를 씁니다. 아래 배포 경로 검사는 문자열 비교인데,
#    링크를 안 풀면 같은 트리가 들어온 문으로 통과했다 막혔다 합니다. 특히 배포 경로가
#    누군가의 홈을 가리키는 링크로 바뀌어 있으면, 링크를 안 푼 검사는 그것을 통과시킵니다.
ROOT="$(cd -P "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="infra/docker-compose.yml"
ENV_FILE="infra/.env"

# 배포 체크아웃의 정본 경로. 개인 홈이 아니라 `adcraft` 그룹 소유의 공용 경로이며
# `/srv/adcraft/exp` 와 형제입니다 (GCP_VM_사용_가이드.md 6절). 다른 곳에 체크아웃해 두고
# 시험 배포를 돌리려면 이 변수를 넘기거나 --allow-any-root 를 쓰세요.
DEPLOY_ROOT="${ADCRAFT_DEPLOY_ROOT:-/srv/adcraft/app}"

# compose 의 포트 매핑과 같아야 합니다. 바꿀 일이 생기면 compose 쪽이 정본입니다.
# ⚠️ 2026-08-19 부터 호스트에 열리는 것은 **앞단 프록시의 둘뿐**입니다 (ADR-0016).
#    backend 8000 과 frontend 80 은 발행되지 않으므로 직접 두드릴 수 없습니다 - 확인은
#    전부 프록시를 거칩니다. 그편이 실제 사용자 경로와 같아서 검증으로서도 낫습니다.
PROXY_HTTP_PORT="${ADCRAFT_HTTP_PORT:-80}"
PROXY_HTTPS_PORT="${ADCRAFT_HTTPS_PORT:-443}"

# 이 아래로 여유가 없으면 빌드 도중 죽습니다. 이미지 3종 재빌드에 수 GB 가 듭니다.
DISK_WARN_GB=10

REF="main"
REF_GIVEN=0
MODE="deploy"
DO_BUILD=1
DO_VERIFY=1
ALLOW_ANY_ROOT=0

log()  { echo "==> $*"; }
warn() { echo "  ! $*" >&2; }
die()  { echo "[중단] $*" >&2; exit 1; }

parse_args() {
  local arg
  while [[ $# -gt 0 ]]; do
    arg="$1"
    case "$arg" in
      --ref)         REF="${2:?--ref 뒤에 브랜치·태그·커밋이 필요합니다}"; REF_GIVEN=1; shift 2 ;;
      --check)       MODE="check"; shift ;;
      --no-build)    DO_BUILD=0; shift ;;
      --skip-verify) DO_VERIFY=0; shift ;;
      --allow-any-root) ALLOW_ANY_ROOT=1; shift ;;
      # 헤더 주석 전체를 그대로 씁니다. 줄 번호로 자르면 주석을 한 줄 고칠 때마다 --help 가
      # 조용히 어긋납니다 (실제로 어긋났습니다).
      -h|--help)     awk 'NR>1 && /^set -/{exit} NR>1' "$0"; exit 0 ;;
      *)             die "모르는 인자: $arg (사용법은 --help)" ;;
    esac
  done

  # ⚠️ 둘을 같이 받으면 "체크아웃은 옮기고 이미지는 그대로"가 되어, 체크아웃의 커밋 SHA 가
  #    실제로 도는 코드를 가리키지 않게 됩니다. --ff-only 로 지키려는 성질이 바로 그것이라
  #    조합 자체를 거부합니다 (PR #117 리뷰, Eastar0102).
  if [[ "$DO_BUILD" -eq 0 && "$REF_GIVEN" -eq 1 ]]; then
    die "--no-build 와 --ref 는 같이 쓸 수 없습니다. 코드를 옮기려면 재빌드가 필요합니다."
  fi
}

compose() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

# ⚠️ 이 검사가 막는 것은 "옛 체크아웃에서 돌린 배포"입니다. compose 프로젝트 이름이
#    `adgen` 으로 고정돼 있어(infra/docker-compose.yml 의 `name:`) 어느 체크아웃에서 올리든
#    같은 컨테이너·같은 볼륨을 갈아끼웁니다. 즉 홈에 남은 옛 체크아웃에서 실행해도 **아무
#    에러 없이 성공**하고, 그때부터 배포된 코드는 아무도 보고 있지 않은 트리가 됩니다.
#    실패로 드러나지 않는 것이 이 함정의 전부라 경고가 아니라 중단으로 둡니다.
check_deploy_root() {
  [[ "$ROOT" == "$DEPLOY_ROOT" ]] && return 0

  if [[ "$ALLOW_ANY_ROOT" -eq 1 ]]; then
    warn "배포 경로 검사를 껐습니다: $ROOT (정본은 $DEPLOY_ROOT)"
    return 0
  fi

  echo "[중단] 배포 체크아웃이 아닙니다." >&2
  echo "       지금 위치: $ROOT" >&2
  echo "       정본 경로: $DEPLOY_ROOT" >&2
  if [[ "$ROOT" == "$HOME"/* || "$ROOT" == /home/* ]]; then
    echo "       개인 홈의 체크아웃입니다. 배포는 /srv/adcraft/app 에서만 합니다 —" >&2
    echo "       이관 절차는 infra/README.md '배포 체크아웃은 /srv/adcraft/app' 절." >&2
  fi
  echo "       시험 목적이면: --allow-any-root, 또는 ADCRAFT_DEPLOY_ROOT=$ROOT" >&2
  exit 1
}

# `/srv/adcraft` 는 여러 사람이 같은 체크아웃을 만지는 그룹 공유 경로입니다. 여기서 나는
# 두 가지 실패는 증상만 보면 코드 문제로 보이므로 먼저 진단해 둡니다.
check_shared_checkout() {
  # git 2.35.2+ 는 소유자가 다른 저장소를 거부합니다("dubious ownership"). A 가 클론하고
  # B 가 배포하는 순간 첫 git 명령에서 터지는데, 메시지가 배포와 무관해 보입니다.
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "[중단] git 이 이 체크아웃을 거부했습니다 (소유자가 다를 때 나는 증상입니다)." >&2
    echo "       한 번만: sudo git config --system --add safe.directory $ROOT" >&2
    echo "       ('--global' 은 실행한 사람에게만 걸립니다. 배포는 누가 돌릴지 모릅니다.)" >&2
    exit 1
  fi

  # 그룹 쓰기가 빠져 있으면 fetch 는 되는데 다음 사람의 fetch 가 권한 오류로 죽습니다.
  # setgid + 기본 ACL 이 걸린 경로에서는 나지 않아야 하는 상태입니다(infra/README.md).
  [[ -w "$ROOT/.git" ]] || warn "$ROOT/.git 에 쓸 수 없습니다 — 그룹 퍼미션을 확인하세요 (infra/README.md)."
}

# infra/.env 의 ADGEN_PUBLIC_HOST. **이 값 하나가 평문과 HTTPS 를 가릅니다** (ADR-0016).
# 값이 비면 compose 가 Caddy 에 `:80` 을 넘기므로, 콜론으로 시작하는 값은 "호스트명 없음"
# 으로 읽습니다. 따옴표와 CRLF 를 털어내는 것은 .env 를 편집기로 만든 경우 대비입니다.
public_host() {
  local v
  v="$(sed -n 's/^ADGEN_PUBLIC_HOST=//p' "$ENV_FILE" | tail -1 | tr -d '[:space:]' | tr -d "'" | tr -d '"')"
  [[ "$v" == :* ]] && v=""
  printf '%s' "$v"
}

preflight() {
  log "사전 점검"

  check_deploy_root
  check_shared_checkout

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

  # ⚠️ 비어 있으면 프록시가 평문 HTTP 로 뜹니다. 기동은 성공하고 curl 도 전부 통과하는데
  #    **브라우저 로그인만 성립하지 않습니다** - 세션 쿠키가 `Secure` 고정이라 브라우저가
  #    평문 응답의 쿠키를 저장하지 않기 때문입니다 (ADR-0016, API_계약.md 8.3절).
  #    ADGEN_ACCOUNTS 와 같은 종류의 함정입니다: 배포 실패로 보이지 않습니다.
  [[ -n "$(public_host)" ]] || warn "$ENV_FILE 의 ADGEN_PUBLIC_HOST 가 비어 있습니다 — 평문 HTTP 로 뜨고 브라우저 로그인이 성립하지 않습니다."

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

# HTTPS 확인에서 --resolve 를 실어야 하므로 배열로 받습니다. 비어 있을 때 set -u 에 걸리지
# 않도록 `${arr[@]+...}` 형태로 펼칩니다.
CURL_RESOLVE=()

http_code() {
  # ⚠️ curl 은 연결에 실패해도 `%{http_code}` 로 이미 `000` 을 씁니다. 그 상태에서 `|| echo`
  #    를 붙이면 코드가 두 번 찍혀 `000000` 이라는 없는 상태 코드가 보고됩니다 (실측).
  #    출력을 받아 두었다가 비었을 때만 채웁니다.
  local url="$1" code
  code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' ${CURL_RESOLVE[@]+"${CURL_RESOLVE[@]}"} "$url" 2>/dev/null || true)"
  printf '%s' "${code:-000}"
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

  local ok=0 host base
  host="$(public_host)"

  if [[ -n "$host" ]]; then
    echo "    INFO 공개 호스트: ${host} (HTTPS)"

    # 80 이 리다이렉트로 살아 있는지 **먼저** 봅니다. 닫으면 인증서 갱신 검증이 못
    # 들어옵니다 (ADR-0016). Caddy 는 Host 와 무관하게 308 입니다 (2026-08-19 실측).
    # 아래에서 CURL_RESOLVE 를 채우기 전에 두는 것은 이 확인만 평문이기 때문입니다.
    expect_code "http://127.0.0.1:${PROXY_HTTP_PORT}/" 308 "80 -> HTTPS 리다이렉트" || ok=1

    base="https://${host}"
    # ⚠️ **--resolve 로 loopback 에 붙입니다.** GCP VM 은 자기 외부 IP 로 되돌아오지 못하므로
    #    이름을 그대로 쓰면 배포는 멀쩡한데 이 확인만 실패합니다. SNI 와 Host 에는 진짜
    #    이름이 그대로 실리므로 **인증서 검증을 건너뛰는 것이 아닙니다** - 발급이 실패했으면
    #    여기서 걸립니다. 그것이 이 확인의 목적입니다.
    CURL_RESOLVE=(--resolve "${host}:${PROXY_HTTPS_PORT}:127.0.0.1")
  else
    base="http://127.0.0.1:${PROXY_HTTP_PORT}"
    warn "평문 HTTP 로 떠 있습니다 (ADGEN_PUBLIC_HOST 미설정) — 아래 확인은 통과해도 브라우저 로그인은 성립하지 않습니다."
  fi

  # 셋 다 프록시를 거칩니다. backend 8000 은 발행되지 않으므로 직접 두드릴 수 없고,
  # 프록시를 거치는 편이 실제 사용자 경로와 같습니다 (ADR-0016).
  expect_code "${base}/health" 200 "프록시 -> backend /health" || ok=1
  expect_code "${base}/" 200 "화면 진입" || ok=1
  # 라우팅·인증·에러 계약이 셋 다 살아 있어야 401 이 나옵니다.
  expect_code "${base}/v1/sessions" 401 "프록시 /v1/sessions (미인증)" || ok=1

  # HTTPS 인데 전부 `000` 이면 TLS 가 서지 않은 것이고, 그 원인은 대개 인증서 발급입니다.
  # 컨테이너는 healthy 로 남아 있어(80 은 살아 있으므로) 증상만 보고는 알기 어렵습니다.
  if [[ "$ok" -ne 0 && -n "$host" ]]; then
    warn "HTTPS 확인이 실패했습니다. 인증서 발급부터 보세요: docker compose -f $COMPOSE_FILE logs caddy | tail -50"
    warn "발급 한도로 막힌 경우의 대응은 ADR-0016 '재검토 신호' 에 있습니다."
  fi
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

  # ⚠️ --no-build 은 체크아웃을 건드리지 않습니다. 갱신만 하고 이미지를 그대로 두면 도는 코드는
  #    옛것인데 `git rev-parse HEAD` 는 새 커밋을 답해, "VM 에 뭐가 떠 있나"가 조용히 거짓이
  #    됩니다. 코드를 옮기는 경로는 재빌드하는 쪽 하나뿐입니다 (PR #117 리뷰, Eastar0102).
  if [[ "$DO_BUILD" -eq 1 ]]; then
    update_checkout
    show_changes "$prev_sha"
  else
    log "체크아웃 유지 ($(git rev-parse --short HEAD)) — 설정만 다시 읽어 재기동합니다."
  fi

  bring_up

  if [[ "$DO_VERIFY" -eq 1 ]]; then
    verify
  fi

  trap - ERR
  log "완료: $(git rev-parse --abbrev-ref HEAD) $(git rev-parse --short HEAD)"
  echo "    롤백이 필요하면: bash scripts/deploy-vm.sh --ref $(git rev-parse --short "$prev_sha")"

  # ⚠️ 브라우저 로그인의 전제가 HTTPS 입니다 — 세션 쿠키가 `Secure` 고정인데
  #    (apps/backend/src/api/routes/auth.py) 평문 HTTP 응답의 쿠키는 브라우저가 저장하지
  #    않습니다 (ADR-0016, API_계약.md 8.3절). 종단은 붙었으므로 남은 변수는 설정값입니다.
  if [[ -n "$(public_host)" ]]; then
    echo "    참고: 인증서 발급 결과는 'docker compose logs caddy' 에서 확인하세요."
  else
    echo "    참고: ADGEN_PUBLIC_HOST 가 비어 평문입니다 — 브라우저 로그인은 성립하지 않습니다."
  fi
}

main "$@"
