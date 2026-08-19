#!/usr/bin/env bash
# SQLite 정합 백업 — 살아 있는 스택에서 상태 파일의 사본을 떠서 호스트로 꺼냅니다.
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
# ⚠️ **임시 사본을 `/data` 에 만들지 마세요.** `/data` 는 `adgen-state` 볼륨이고 그것이 바로
#    백업 대상입니다. 거기에 사본을 두면 다음 백업이 지난 백업을 품고, 그다음은 그것을 품습니다.
#    컨테이너의 `/tmp` 를 거치는 이유가 그것입니다 — 볼륨 밖이고, 컨테이너가 죽으면 함께
#    사라져 뒤처리가 필요 없습니다.
#
# ⚠️ **이미지 파일은 이 백업에 들어 있지 않습니다.** 상태 파일만입니다. 업로드 사진은 24시간,
#    결과는 7일이면 어차피 사라지고(세션_보관_정책 2절), 수 GB 를 매일 복사하면 디스크가 먼저
#    찹니다. 시연에 쓸 산출물은 보존 기간과 무관하게 따로 내려받으라는 그 문서의 지시가 이
#    자리를 대신합니다.
#
# ⚠️ 접속 정보(외부 IP·프로젝트 ID·인스턴스명)를 이 파일에 적지 마세요 — 저장소가 public 입니다.
set -Eeuo pipefail

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

# 컨테이너 안의 상태 파일 경로. compose 가 backend 에 넘기는 값이 정본이라 거기서 읽습니다 —
# 여기에 다시 적으면 두 곳이 갈라지고, 갈라진 쪽이 백업하는 파일은 아무도 쓰지 않는 파일입니다.
db_path_in_container() {
  compose exec -T backend printenv ADGEN_DB_PATH 2>/dev/null | tr -d '\r\n'
}

preflight() {
  cd "$ROOT"
  [[ -f "$COMPOSE_FILE" ]] || die "$COMPOSE_FILE 이 없습니다. 레포 루트에서 실행하세요."
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE 이 없습니다."
  command -v docker >/dev/null 2>&1 || die "docker 가 없습니다."

  # ⚠️ 컨테이너가 떠 있어야 합니다. `VACUUM INTO` 를 실행하는 주체가 backend 이기 때문입니다.
  #    내려간 스택에서 백업을 시도하면 여기서 멈춥니다 — cron 이 조용히 실패해 백업이 없는
  #    채로 몇 주가 지나는 것보다, 메일함에 실패가 쌓이는 편이 낫습니다.
  compose ps --status running --format '{{.Service}}' | grep -qx backend \
    || die "backend 컨테이너가 떠 있지 않습니다. 백업은 살아 있는 스택에서만 뜹니다."
}

do_backup() {
  local db stamp name in_container
  db="$(db_path_in_container)"
  [[ -n "$db" ]] || die "컨테이너에서 ADGEN_DB_PATH 를 읽지 못했습니다."

  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  name="adgen-${stamp}.sqlite"
  in_container="/tmp/${name}"

  mkdir -p "$BACKUP_DIR"

  # ⚠️ `VACUUM INTO` 는 **대상 파일이 이미 있으면 실패합니다.** 타임스탬프가 이름에 들어가는
  #    것이 그 대비이며, 초 단위라 같은 초에 두 번 돌리면 실패합니다. 그것이 맞는 동작입니다 —
  #    조용히 덮어쓰면 방금 뜬 백업이 사라집니다.
  log "정합 사본 뜨는 중 ($db -> $in_container)"
  compose exec -T backend python -c "
import sqlite3, sys
source, target = sys.argv[1], sys.argv[2]
with sqlite3.connect(source) as conn:
    conn.execute('VACUUM INTO ?', (target,))
" "$db" "$in_container"

  log "호스트로 꺼내는 중 -> $BACKUP_DIR/$name"
  compose cp "backend:${in_container}" "$BACKUP_DIR/$name"

  # 볼륨 밖이라 남겨 둬도 컨테이너와 함께 사라지지만, 재기동 전까지는 메모리 위의 tmpfs 나
  # 이미지 레이어를 차지합니다. 뜬 즉시 치웁니다.
  compose exec -T backend rm -f "$in_container"

  verify "$BACKUP_DIR/$name"
  rotate
}

# 백업이 열리는지 확인합니다. **뜨는 것과 복원 가능한 것은 다른 주장**이고, 확인하지 않은
# 백업은 없는 백업과 같은 값입니다 — 필요할 때 알게 되는 것이 최악입니다.
verify() {
  local file="$1" users
  [[ -s "$file" ]] || die "백업 파일이 비어 있습니다: $file"

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

  # 지금 것을 먼저 뜹니다. 복원이 틀린 선택이었을 때 돌아올 자리가 없으면 안 됩니다.
  log "복원 전 현재 상태를 먼저 백업합니다"
  do_backup

  log "스택을 내립니다 (볼륨은 건드리지 않습니다)"
  compose down

  # ⚠️ `-v` 없이 내렸으므로 볼륨은 그대로입니다. 그 볼륨에 파일을 넣으려면 컨테이너가 하나
  #    필요한데, 스택을 다시 올리면 backend 가 옛 파일을 연 채로 뜹니다. 그래서 볼륨만 붙인
  #    일회용 컨테이너로 넣습니다.
  #
  # ⚠️ **`cp` 로 덮어쓰면 안 됩니다.** busybox 의 `cp` 는 대상을 지우고 새로 만들어서 결과
  #    파일이 그 컨테이너의 root 소유가 됩니다. 앱은 비루트(appuser)로 돌기 때문에 다음
  #    기동이 `attempt to write a readonly database` 로 죽습니다 - 복원은 성공한 것처럼
  #    보이고 스택만 안 뜹니다 (2026-08-19 실측).
  #    `cat >` 는 기존 파일에 그대로 써서 inode 와 소유권을 지킵니다. 파일이 아예 없던
  #    경우를 위해 `/data` 의 소유자로 한 번 더 맞추는데, uid 를 여기 적지 않는 것은
  #    Dockerfile 과 두 곳이 되면 갈라지는 날 같은 증상이 돌아오기 때문입니다.
  log "백업을 볼륨에 넣는 중"
  docker run --rm -v "adgen_adgen-state:/data" -v "$(dirname "$(readlink -f "$file")"):/restore:ro" \
    alpine:3 sh -c 'set -e; owner=$(stat -c %u:%g /data); cat "/restore/$1" > "$2"; chown "$owner" "$2"' \
    _ "$(basename "$file")" "$db"

  log "스택을 다시 올립니다"
  compose up -d --wait

  log "완료. 계정과 세션이 백업 시점으로 돌아갔습니다."
}

main() {
  parse_args "$@"
  preflight

  case "$MODE" in
    list)    do_list ;;
    restore) do_restore "$RESTORE_FROM" ;;
    backup)  do_backup; log "완료: $BACKUP_DIR" ;;
  esac
}

main "$@"
