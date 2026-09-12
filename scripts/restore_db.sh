#!/usr/bin/env bash
# =============================================================================
# scripts/restore_db.sh — MySQL 덤프(backups/db_YYYYMMDD_HHMMSS.sql.gz) 복원
#
#   bash scripts/restore_db.sh                                # backups/ 의 최신 db_*.sql.gz
#   bash scripts/restore_db.sh backups/db_20260912_030001.sql.gz
#   bash scripts/restore_db.sh <파일> --yes                   # 확인 프롬프트 생략 (비대화형)
#   bash scripts/restore_db.sh <파일> --no-service            # 서비스 stop/start 생략 (첫 구축 등 서비스 없을 때)
#
# 순서: 복원 전 자동 백업(backups/pre_restore_<ts>.sql.gz) → 서비스 중지 → 복원 → migrate → 서비스 시작
#   - 덤프는 manage.py backup_db 가 만든 mysqldump 출력(DROP TABLE IF EXISTS 포함)이라
#     같은 DB 에 그대로 흘려 넣으면 테이블 단위로 교체된다. DB 자체는 드롭하지 않는다.
#   - pre_restore_*.sql.gz 는 backup_db --keep 의 정리 대상(db_*.sql.gz)이 아니므로 수동으로 지운다.
#   - 접속 정보는 .env(DJANGO_DB_*) 에서 읽는다. 비밀번호는 명령행에 노출하지 않는다(defaults-extra-file).
# =============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VENV_DIR="${VENV_DIR:-$HOME/venvs/mysite}"
SERVICE_NAME="${SERVICE_NAME:-mysite}"
SETTINGS="config.settings.prod"

c_info() { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
c_ok()   { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
c_warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
c_fail() { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

envval() {
  local v
  v="$(grep -E "^[[:space:]]*$1=" "$APP_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  v="${v%%$'\r'}"; v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}

# ----------------------------------------------------------------------------- 인자
DUMP=""; YES=0; NO_SERVICE=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)     YES=1 ;;
    --no-service) NO_SERVICE=1 ;;
    -h|--help)    sed -n '2,16p' "$0"; exit 0 ;;
    -*)           c_fail "알 수 없는 옵션: $arg" ;;
    *)            DUMP="$arg" ;;
  esac
done

cd "$APP_DIR"
[ -f .env ] || c_fail ".env 가 없습니다: $APP_DIR/.env"
[ "$(envval DJANGO_DB_ENGINE)" = "mysql" ] || c_fail ".env DJANGO_DB_ENGINE 이 mysql 이 아닙니다."
DB_NAME="$(envval DJANGO_DB_NAME)"; DB_USER="$(envval DJANGO_DB_USER)"; DB_PASS="$(envval DJANGO_DB_PASSWORD)"
DB_HOST="$(envval DJANGO_DB_HOST)"; DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="$(envval DJANGO_DB_PORT)"; DB_PORT="${DB_PORT:-3306}"
[ -n "$DB_NAME" ] && [ -n "$DB_USER" ] && [ -n "$DB_PASS" ] || c_fail ".env 에 DJANGO_DB_NAME/USER/PASSWORD 가 필요합니다."
command -v mysql >/dev/null && command -v mysqldump >/dev/null || c_fail "mysql/mysqldump 가 없습니다 (apt install mysql-client)"

if [ -z "$DUMP" ]; then
  DUMP="$(ls -1t backups/db_*.sql.gz 2>/dev/null | head -n1 || true)"
  [ -n "$DUMP" ] || c_fail "backups/db_*.sql.gz 가 없습니다. 복원할 파일을 인자로 지정하세요."
fi
[ -s "$DUMP" ] || c_fail "덤프 파일이 없거나 비어 있습니다: $DUMP"
case "$DUMP" in
  *.sql.gz) READER="gunzip -c" ;;
  *.sql)    READER="cat" ;;
  *)        c_fail "지원하지 않는 형식 (.sql.gz 또는 .sql): $DUMP" ;;
esac
# 덤프 무결성: gzip 이면 압축 검사, 그리고 mysqldump 완료 마커
if [ "$READER" = "gunzip -c" ]; then gzip -t "$DUMP" || c_fail "gzip 손상: $DUMP"; fi
$READER "$DUMP" | tail -n 5 | grep -q "Dump completed" || c_warn "'Dump completed' 마커가 없습니다 — 덤프가 중간에 끊겼을 수 있음"

# ----------------------------------------------------------------------------- 자격 파일 (비밀번호 미노출)
CNF="$(mktemp)"; chmod 600 "$CNF"
trap 'rm -f "$CNF"' EXIT
printf '[client]\nhost=%s\nport=%s\nuser=%s\npassword=%s\n' "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_PASS" >"$CNF"
mysql --defaults-extra-file="$CNF" -Nse 'SELECT 1' "$DB_NAME" >/dev/null || c_fail "MySQL 접속 실패 (.env DJANGO_DB_* 확인)"

cur_tables="$(mysql --defaults-extra-file="$CNF" -Nse "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DB_NAME}'")"
dump_size="$(du -h "$DUMP" | cut -f1)"

printf '\n'
c_info "복원 대상 DB : $DB_NAME@$DB_HOST (현재 테이블 $cur_tables 개)"
c_info "복원 파일    : $DUMP ($dump_size)"
c_info "서비스       : $SERVICE_NAME $([ "$NO_SERVICE" -eq 1 ] && echo '(stop/start 생략)' || echo '(복원 중 중지)')"
if [ "$YES" -ne 1 ]; then
  read -r -p "현재 DB 내용이 덤프로 교체됩니다. 진행할까요? [y/N] " ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { c_info "취소"; exit 0; }
fi

# ----------------------------------------------------------------------------- 1. 복원 전 백업
mkdir -p backups
PRE="backups/pre_restore_$(date +%Y%m%d_%H%M%S).sql.gz"
c_info "1/4 복원 전 자동 백업 → $PRE"
mysqldump --defaults-extra-file="$CNF" --single-transaction --routines --triggers "$DB_NAME" | gzip >"$PRE"
[ -s "$PRE" ] && gzip -t "$PRE" || c_fail "복원 전 백업 실패 — 중단"
c_ok "복원 전 백업 완료 ($(du -h "$PRE" | cut -f1))"

# ----------------------------------------------------------------------------- 2. 서비스 중지
svc_was_active=0
if [ "$NO_SERVICE" -eq 0 ] && systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  svc_was_active=1
  c_info "2/4 $SERVICE_NAME 중지 (복원 중 쓰기 방지)"
  sudo systemctl stop "$SERVICE_NAME"
else
  c_info "2/4 서비스 중지 생략"
fi

# ----------------------------------------------------------------------------- 3. 복원
c_info "3/4 복원 실행 (${DUMP} → ${DB_NAME})"
if ! $READER "$DUMP" | mysql --defaults-extra-file="$CNF" "$DB_NAME"; then
  c_warn "복원 중 오류. 직전 상태로 되돌리려면:"
  c_warn "  gunzip -c $PRE | mysql --defaults-extra-file=<cnf> $DB_NAME   (또는 bash scripts/restore_db.sh $PRE)"
  [ "$svc_was_active" -eq 1 ] && sudo systemctl start "$SERVICE_NAME" || true
  c_fail "복원 실패"
fi
new_tables="$(mysql --defaults-extra-file="$CNF" -Nse "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DB_NAME}'")"
c_ok "복원 완료 (테이블 $new_tables 개)"

# ----------------------------------------------------------------------------- 4. migrate + 서비스 시작
c_info "4/4 migrate ($SETTINGS) + 서비스 시작"
if [ -x "$VENV_DIR/bin/python3" ]; then
  DJANGO_SETTINGS_MODULE="$SETTINGS" "$VENV_DIR/bin/python3" manage.py migrate --noinput \
    || c_warn "migrate 실패 — 코드/덤프 버전 확인 (showmigrations)"
else
  c_warn "venv 없음($VENV_DIR) — migrate 생략"
fi
if [ "$svc_was_active" -eq 1 ]; then
  sudo systemctl start "$SERVICE_NAME"
  sleep 2
  systemctl is-active --quiet "$SERVICE_NAME" && c_ok "$SERVICE_NAME 기동" || c_fail "$SERVICE_NAME 기동 실패: sudo journalctl -u $SERVICE_NAME -n 50"
fi

# 요약 (사용자·게시글 수로 데이터가 들어왔는지 눈으로 확인)
# (community 앱의 테이블은 db_table='pybo_*' 로 유지되어 있음)
mysql --defaults-extra-file="$CNF" -e "SELECT (SELECT COUNT(*) FROM auth_user) AS users, (SELECT COUNT(*) FROM pybo_question) AS questions;" "$DB_NAME" 2>/dev/null || true
c_ok "완료. 복원 전 백업: $PRE (불필요해지면 수동 삭제)"
