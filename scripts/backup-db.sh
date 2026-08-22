#!/usr/bin/env bash
# SQLite 정합 백업 — 상태 파일의 사본을 떠서 호스트로 꺼내고, 되돌립니다.
# **VM 안에서** 실행합니다. cron 에 거는 것이 목적이고, 손으로 돌려도 같습니다.
#
#     bash scripts/backup-db.sh              # 기본 위치로 백업하고 오래된 것을 정리
#     bash scripts/backup-db.sh --list       # 가진 백업 목록만 봅니다
#     bash scripts/backup-db.sh --restore <파일>   # 되돌립니다 (스택을 잠깐 내립니다)
#
# ⚠️ **`cp` 로 뜨지 않습니다.** 살아 있는 SQLite 파일을 그대로 복사하면 쓰기가 걸린 순간의
#    찢어진 사본이 나올 수 있습니다. `VACUUM INTO` 는 SQLite 가 스스로 일관된 시점의 사본을
#    쓰는 명령이라, 스택을 내리지 않고도 복원 가능한 파일이 나옵니다 (ADR-0010).
#
# ⚠️ **컨테이너는 `compose run` 으로 띄웁니다. `exec` 도 `docker run` 도 아닙니다.**
#    `exec` 는 스택이 살아 있어야 하는데, 목록을 보고 싶은 때와 복원하고 싶은 때는 대개
#    스택이 정상이 아닌 때입니다 — 크래시 루프에 빠진 backend 는 `--status running` 에도
#    걸리지 않습니다. `docker run` 은 볼륨 이름을 손으로 적게 되는데 **도커는 없는 이름의
#    볼륨을 조용히 새로 만들어서**, 오타가 나면 엉뚱한 빈 볼륨에 복원해 놓고 "완료" 를
#    찍습니다. `compose run` 은 서비스 정의의 볼륨을 그대로 붙이므로 이름이 필요 없습니다
#    (PR #133 리뷰, 신호정).
#
# ⚠️ **방향마다 실행 사용자가 다릅니다. 소유권 때문입니다.**
#    - 뜰 때는 `--user` 로 호스트 사용자가 되어 호스트 디렉토리에 씁니다. 컨테이너 사용자로
#      쓰면 백업 파일이 uid 10001 소유로 남아 정리도 열람도 어려워집니다.
#    - 되돌릴 때는 **파일을 stdin 으로 흘려보냅니다.** 호스트 쪽에서 읽고 컨테이너 쪽에서
#      쓰므로 양쪽 다 자기 파일만 만지고, 볼륨 안 파일의 소유권(uid 10001)이 그대로
#      유지됩니다. bind mount 로 넣으면 좁혀 둔 백업(0640)을 컨테이너가 못 읽고
#      -- 컨테이너 사용자는 그 파일의 소유자도 그룹 구성원도 아닙니다 --,
#      `cp` 로 넣으면 대상이 root 소유가 되어 다음 기동이
#      `attempt to write a readonly database` 로 죽습니다 (2026-08-19 실측).
#    - ⚠️ **예외가 하나 있습니다. 뜨기 직전의 저널 회수 단계는 `--user` 없이 돕니다**
#      (`do_backup` 안). 그 단계는 호스트에 아무것도 쓰지 않고 볼륨 안 DB 를 여는 것이
#      전부이며, 소유자(uid 10001)여야만 롤백이 됩니다. **이 줄과 일관되게 맞추겠다며
#      거기에 `--user` 를 붙이면 N3 가 되살아납니다** (PR #196 리뷰, 정승호).
#
# ⚠️ **이미지 파일은 이 백업에 들어 있지 않습니다.** 상태 파일만입니다. ADR-0010 의 "두 경로의
#    복사" 와 어긋나는 이유는 docs/adr/0018-백업_대상은_상태_파일뿐입니다.md 에 있습니다.
#
# ⚠️ 접속 정보(외부 IP·프로젝트 ID·인스턴스명)를 이 파일에 적지 마세요 — 저장소가 public 입니다.
set -Eeuo pipefail

# 백업 파일에는 `users.password_hash` 와 세션이 통째로 들어갑니다. 기본 위치는 `/srv/adcraft`
# 의 그룹 설정을 상속받지만 `ADCRAFT_BACKUP_DIR` 로 다른 곳을 가리키면 그 보호가 따라가지
# 않으므로, 이 스크립트가 만드는 것은 이 스크립트가 좁힙니다 (PR #133 리뷰, 신호정).
#
# ⚠️ **umask 가 좁히는 것은 아래 `mkdir -p "$BACKUP_DIR"` 하나이고, 백업 파일은 아닙니다.**
#    umask 는 프로세스 속성이라 `compose run` 안에서 새로 시작하는 컨테이너 프로세스가
#    물려받지 않고, 자기 기본값 022 로 0644 를 만듭니다 (PR #133 리뷰에서 신호정 실측).
#    기본 ACL 이 걸린 디렉토리에서는 umask 자체가 무시되므로 기본 위치에서는 디렉토리에도
#    효력이 없습니다. 그래서 이 줄만 믿지 않고 `do_backup` 이 뜬 파일을 곧바로 `chmod` 합니다 —
#    이 줄을 "파일도 좁혀진다" 로 읽으면 나중에 백업을 내려받는 절차가 붙는 날 확인을
#    건너뛰게 됩니다.
umask 077

ROOT="$(cd -P "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="infra/docker-compose.yml"
ENV_FILE="infra/.env"

# 백업이 사는 곳. 배포 체크아웃 **밖**입니다 — 안에 두면 `deploy-vm.sh` 의 "추적 파일에
# 커밋되지 않은 변경" 검사에 걸리거나, 더 나쁘게는 실수로 커밋됩니다.
BACKUP_DIR="${ADCRAFT_BACKUP_DIR:-/srv/adcraft/backups}"

# 몇 개를 남길지. 하루 한 번이면 2주치입니다. VM 디스크가 100GB 상한이고(ADR-0011) 상태
# 파일은 작지만, 무한히 쌓이는 디렉토리는 언젠가 반드시 문제가 됩니다.
KEEP="${ADCRAFT_BACKUP_KEEP:-14}"

MODE="backup"
RESTORE_FROM=""
BACKUP_MADE=""

log()  { echo "==> $*"; }
warn() { echo "  ! $*" >&2; }
die()  { echo "[중단] $*" >&2; exit 1; }

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --list)    MODE="list"; shift ;;
      --restore) MODE="restore"; RESTORE_FROM="${2:?--restore 뒤에 백업 파일 경로가 필요합니다}"; shift 2 ;;
      -h|--help) awk 'NR>1 && /^set -/{exit} NR>1' "$0"; exit 0 ;;
      *)         die "모르는 인자: $1 (사용법은 --help)" ;;
    esac
  done
}

compose() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

# 일회용 backend 컨테이너. 스택이 떠 있든 죽어 있든 같습니다 (2026-08-19 양쪽 확인).
in_backend() {
  compose run --rm --no-deps -T "$@"
}

# 컨테이너 안의 상태 파일 경로. compose 가 backend 에 넘기는 값이 정본이라 거기서 읽습니다 —
# 여기에 다시 적으면 두 곳이 갈라지고, 갈라진 쪽이 백업하는 파일은 아무도 쓰지 않는 파일입니다.
db_path_in_container() {
  in_backend backend printenv ADGEN_DB_PATH 2>/dev/null | tr -d '\r\n'
}

preflight() {
  cd "$ROOT"
  [[ -f "$COMPOSE_FILE" ]] || die "$COMPOSE_FILE 이 없습니다. 레포 루트에서 실행하세요."
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE 이 없습니다."
  command -v docker >/dev/null 2>&1 || die "docker 가 없습니다."

  # ⚠️ **스택이 떠 있는지는 보지 않습니다.** 위의 `compose run` 때문에 백업도 복원도 죽은
  #    스택에서 성립하고, 오히려 그때가 필요한 때입니다. 확인을 넣으면 정작 복원해야 할
  #    상황에서 막힙니다 (PR #133 리뷰, 신호정).
}

# $1: 오래된 백업 정리 여부 (1 이면 정리, 0 이면 건너뜀)
do_backup() {
  local do_rotate="$1" db stamp name
  db="$(db_path_in_container)"
  [[ -n "$db" ]] || die "컨테이너에서 ADGEN_DB_PATH 를 읽지 못했습니다."

  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  name="adgen-${stamp}.sqlite"
  mkdir -p "$BACKUP_DIR"

  # ⚠️ **저널을 먼저 회수합니다. 아래 줄이 `--user` 로 도는 것이 이 단계를 필요하게 만듭니다.**
  #    백업 사용자는 uid 10001 소유의 상태 파일을 **읽기로만** 열 수 있습니다. 롤백 저널이
  #    남아 있으면 SQLite 는 읽기 전에 복구부터 하려 하고, 복구는 쓰기라
  #    `attempt to write a readonly database` 로 끊깁니다 — 권한 문제인데 손상과 구별되지
  #    않는 메시지입니다. `verify` 가 열기 전에 읽기 권한을 먼저 보는 것과 같은 이유이고,
  #    하필 **크래시 루프에서 사전 백업을 뜨려는 상황**이 정확히 저널이 남는 상황입니다
  #    (PR #133 리뷰 N3, 신호정).
  #
  #    `--user` 를 주지 않으면 이미지의 기본 사용자(appuser)로 돌아 쓰기로 열리고, **여는
  #    것만으로** SQLite 가 저널을 회수합니다. 저널이 없으면 컨테이너만 한 번 뜨고 끝납니다.
  #
  #    ⚠️ **파일이 있다는 것만으로는 회수가 필요한지 알 수 없습니다.** 정상 쓰기가 진행 중인
  #    동안에도 같은 이름의 저널이 존재하고, 둘을 가르려면 저널 헤더와 잠금 상태를 읽어야
  #    합니다. 여는 쪽은 어느 경우든 안전하므로(진행 중이면 그냥 읽고 끝납니다) 가르지 않고
  #    열되, 메시지는 단정하지 않습니다 — 이 스크립트가 고치려는 것이 바로 "운영자가 잘못된
  #    단정을 읽는 것" 이기 때문입니다.
  #
  #    ⚠️ 재현 조건이 좁습니다 (2026-08-22, VM `/tmp` 에서 실측). 한 행짜리 트랜잭션 도중에
  #    죽인 경우는 저널이 남아도 백업이 **성공**했고, 캐시를 좁혀 페이지가 실제로 DB 파일로
  #    흘러넘친 뒤 죽여야 실패했습니다. 경계가 어디인지는 재지 않았으므로 "저널만 있으면
  #    항상 실패한다" 로 읽지 마세요.
  in_backend backend python -c "
import os, sqlite3, sys
db = sys.argv[1]
if not os.path.exists(db + '-journal'):
    sys.exit(0)
print('저널 파일이 있어 소유자로 한 번 엽니다 (진행 중인 쓰기일 수도 있습니다)', file=sys.stderr)
conn = sqlite3.connect(db)
conn.execute('SELECT count(*) FROM sqlite_master')
conn.close()
" "$db" || warn "저널 회수에 실패했습니다. 아래 백업이 권한(readonly database)이나 잠금(database is locked)으로 끊기면 그 이유입니다."

  # ⚠️ `VACUUM INTO` 는 **대상 파일이 이미 있으면 실패합니다.** 타임스탬프가 이름에 들어가는
  #    것이 그 대비이며, 초 단위라 같은 초에 두 번 돌리면 실패합니다. 그것이 맞는 동작입니다 —
  #    조용히 덮어쓰면 방금 뜬 백업이 사라집니다.
  log "정합 사본 뜨는 중 ($db)"
  in_backend --user "$(id -u):$(id -g)" -v "$(readlink -f "$BACKUP_DIR")":/backup backend \
    python -c "
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as conn:
    conn.execute('VACUUM INTO ?', (sys.argv[2],))
" "$db" "/backup/$name"

  # ⚠️ **`umask` 가 아니라 여기가 파일 권한을 정하는 자리입니다.** 위 줄을 실행한 것은
  #    컨테이너 프로세스라 호스트 셸의 umask 를 물려받지 않았고, 파일은 0644 로 떨어져
  #    있습니다. 확인보다 먼저 좁히는 것은 노출되는 구간을 줄이기 위해서입니다.
  #
  # ⚠️ **0600 이 아니라 0640 입니다. 그룹 읽기를 남기는 것이 의도입니다.**
  #    cron 은 한 사람의 crontab 에 걸리므로 0600 이면 **그 사람만 복원할 수 있습니다.**
  #    `/srv/adcraft` 는 `adcraft` 그룹과 setgid 로 세운 공용 경로이고(infra/README 의
  #    "배포 체크아웃은 `/srv/adcraft/app`" 절), 배포가 한 사람의 자산이 아니라는 것이 그
  #    경로의 전제입니다. setgid 덕에 파일 그룹이 `adcraft` 로 붙으므로 0640 이면 팀원이
  #    읽고, 그 밖의 사용자는 여전히 못 읽습니다. 기본 ACL 이 없는 다른 경로를 가리켜도
  #    그룹은 만든 사람의 기본 그룹이라 넓어지지 않습니다 (PR #133 리뷰, 신호정).
  chmod 640 "$BACKUP_DIR/$name"

  verify "$BACKUP_DIR/$name"
  [[ "$do_rotate" -eq 1 ]] && rotate
  BACKUP_MADE="$BACKUP_DIR/$name"
}

# 백업이 열리는지 확인합니다. **뜨는 것과 복원 가능한 것은 다른 주장**이고, 확인하지 않은
# 백업은 없는 백업과 같은 값입니다 — 필요할 때 알게 되는 것이 최악입니다.
verify() {
  local file="$1" users
  [[ -s "$file" ]] || die "백업 파일이 비어 있습니다: $file"

  # ⚠️ **읽을 수 있는지를 먼저 봅니다. 아래 `sqlite3` 가 권한과 손상을 구별하지 못하기
  #    때문입니다.** 못 읽는 파일을 열면 `PermissionError` 가 아니라
  #    `OperationalError: unable to open database file` 이 나오는데, 이것은 깨진 백업의
  #    메시지와 같습니다. 장애 중에 그것을 보면 자연스러운 다음 행동이 "그다음으로 오래된
  #    백업을 시도" 이고 전부 같은 이유로 실패하므로 **백업 전체가 깨진 것으로 오진하게
  #    됩니다.** 위 `-s` 는 `stat` 만 쓰므로 걸러 주지 못합니다 (PR #133 리뷰, 신호정).
  if [[ ! -r "$file" ]]; then
    die "백업 파일을 읽을 권한이 없습니다: $(ls -ld "$file" 2>/dev/null || echo "$file")"
  fi

  users="$(python3 -c "
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as conn:
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    print(conn.execute('SELECT count(*) FROM users').fetchone()[0])
" "$file")" || die "백업을 열지 못했습니다: $file"

  log "확인: integrity_check ok, 계정 ${users}건, $(du -h "$file" | cut -f1)"
  [[ "$users" -gt 0 ]] || warn "계정이 0건입니다. 시드되지 않은 스택을 백업한 것일 수 있습니다."
}

rotate() {
  local extra
  mapfile -t extra < <(ls -1t "$BACKUP_DIR"/adgen-*.sqlite 2>/dev/null | tail -n "+$((KEEP + 1))")
  [[ ${#extra[@]} -eq 0 ]] && return 0
  log "오래된 백업 ${#extra[@]}개 삭제 (${KEEP}개 유지)"
  rm -f "${extra[@]}"
}

do_list() {
  [[ -d "$BACKUP_DIR" ]] || die "백업 디렉토리가 없습니다: $BACKUP_DIR"
  ls -1lht "$BACKUP_DIR"/adgen-*.sqlite 2>/dev/null | sed 's/^/    /' \
    || die "백업이 하나도 없습니다: $BACKUP_DIR"
}

# ⚠️ 복원은 스택을 잠깐 내립니다. 살아 있는 프로세스가 열어 둔 파일을 갈아치우면 그 프로세스는
#    옛 파일을 계속 들고 있고, 다음 재기동에 무엇이 남을지는 아무도 모릅니다.
do_restore() {
  local file="$1" db
  [[ -f "$file" ]] || die "그런 파일이 없습니다: $file"
  verify "$file"

  db="$(db_path_in_container)"
  [[ -n "$db" ]] || die "컨테이너에서 ADGEN_DB_PATH 를 읽지 못했습니다."

  # ⚠️ 지금 것을 먼저 뜨되 **정리는 건너뜁니다.** `rotate` 는 최신 KEEP 개만 남기는데, 사전
  #    백업이 하나 늘어난 상태에서 세므로 가장 오래된 하나가 그 자리에서 사라집니다. 그것이
  #    방금 `--restore` 로 지정한 파일일 수 있고, 삭제는 `compose down` 보다 먼저이므로
  #    **복원 원본이 사라진 채로 서비스가 내려갑니다** (PR #133 리뷰에서 신호정 발견, 재현됨).
  #    복원 중에는 아무것도 지우지 않습니다.
  log "복원 전 현재 상태를 먼저 백업합니다 (정리는 건너뜁니다)"
  do_backup 0

  log "스택을 내립니다 (볼륨은 건드리지 않습니다)"
  compose down

  # ⚠️ 여기서부터 스택이 내려가 있습니다. 아래 어느 줄에서 실패하든 **서비스가 죽은 채로
  #    끝나면 안 됩니다.** `set -E` 를 켜 둔 것이 이 트랩을 위해서입니다.
  trap 'warn "복원이 중단됐습니다. 스택을 되돌립니다 - 직전 상태는 ${BACKUP_MADE} 에 있습니다"; compose up -d || true' ERR

  # ⚠️ 파일을 **stdin 으로** 흘려보냅니다. 호스트가 읽고 컨테이너가 쓰므로 양쪽 다 자기 것만
  #    만지고, 볼륨 안 파일의 소유권이 그대로 유지됩니다. 파일 머리말의 "방향마다 실행
  #    사용자가 다릅니다" 참고.
  log "백업을 볼륨에 넣는 중"
  in_backend backend sh -c 'cat > "$1"' _ "$db" < "$file"

  log "스택을 다시 올립니다"
  compose up -d --wait
  trap - ERR

  log "완료. 계정과 세션이 백업 시점으로 돌아갔습니다."
}

main() {
  parse_args "$@"
  preflight

  case "$MODE" in
    list)    do_list ;;
    restore) do_restore "$RESTORE_FROM" ;;
    backup)  do_backup 1; log "완료: $BACKUP_DIR" ;;
  esac
}

main "$@"
