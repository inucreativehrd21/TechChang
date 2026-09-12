#!/usr/bin/env bash
# =============================================================================
# deploy_oci.sh — TechChang(techchang.com) OCI 서버 초기 구성 + 재배포 (멱등)
#
#   처음 1회 (서버 구성 + 배포):   bash deploy_oci.sh
#   코드 재배포만:                  bash deploy_oci.sh --skip-system
#   nginx 를 HTTP 템플릿으로 강제:  bash deploy_oci.sh --force-nginx   (certbot 적용 후엔 쓰지 말 것)
#
# 전제
#   - Ubuntu 22.04/24.04, sudo 가능한 일반 사용자(ubuntu)로 실행. root 로 직접 실행하지 않는다.
#   - 레포가 $APP_DIR(기본 /home/ubuntu/projects/mysite) 에 clone 되어 있고 이 스크립트가 그 안에 있다.
#   - $APP_DIR/.env 가 준비되어 있다 (Lightsail 의 .env 를 복사한 뒤 IP/호스트만 수정).
#
# 하는 일 (순서대로, 각 단계는 다시 실행해도 안전)
#   1. .env 필수 키 검사
#   2. [system] 타임존, apt 패키지(빌드 도구 포함: mysqlclient/Pillow 소스 빌드 대비), 그룹, 홈 디렉터리 권한
#   3. [system] iptables 80/443 개방 + netfilter-persistent save   (OCI 는 VCN 보안목록과 별개로 필요)
#   4. [system] MySQL 설치, 타임존 테이블 적재, .env 값으로 DB/사용자 생성
#   5. venv(/home/ubuntu/venvs/mysite, Lightsail 과 동일 경로) + requirements-prod.txt
#   6. migrate → collectstatic(ManifestStaticFilesStorage: 실패 시 여기서 중단, 서비스는 건드리지 않음)
#   7. systemd 유닛(mysite.service, EnvironmentFile=.env) 설치/갱신
#   8. nginx HTTP 설정 — 이미 443/certbot 블록이 있으면 절대 덮어쓰지 않음
#   9. 서비스 재시작 + 로컬 헬스체크
#
# 경로/사용자를 바꾸려면 환경변수로 덮어쓴다:
#   APP_DIR VENV_DIR SERVICE_USER SERVICE_NAME DOMAIN SERVER_IP TIMEZONE DB_COLLATION PYTHON_BIN
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------------------------- 설정
APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
VENV_DIR="${VENV_DIR:-$HOME/venvs/mysite}"
SERVICE_USER="${SERVICE_USER:-$USER}"          # gunicorn 실행 계정. cron(ubuntu)과 같은 계정이어야 logs/ 공유가 안전
SERVICE_NAME="${SERVICE_NAME:-mysite}"         # send_log_report 가 `journalctl -u mysite` 를 읽으므로 이름 유지
DOMAIN="${DOMAIN:-techchang.com}"
TIMEZONE="${TIMEZONE:-Asia/Seoul}"             # crontab 시각 기준. Lightsail 과 같게
DB_COLLATION="${DB_COLLATION:-utf8mb4_unicode_ci}"   # Lightsail 값과 맞출 것 (런북 0단계에서 확인)
PYTHON_BIN="${PYTHON_BIN:-python3}"
SETTINGS="config.settings.prod"

NGINX_SITE="/etc/nginx/sites-available/techchang"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
REPORT_LOG="/var/log/techchang_report.log"     # Lightsail crontab 이 이 경로에 로그를 남김

SKIP_SYSTEM=0; FORCE_NGINX=0; NO_RESTART=0
for arg in "$@"; do
  case "$arg" in
    --skip-system) SKIP_SYSTEM=1 ;;
    --force-nginx) FORCE_NGINX=1 ;;
    --no-restart)  NO_RESTART=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $arg" >&2; exit 2 ;;
  esac
done

# ----------------------------------------------------------------------------- 유틸
c_info()  { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
c_ok()    { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
c_warn()  { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
c_fail()  { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }
step()    { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

# .env 에서 KEY 값 읽기 (마지막 정의 우선, 따옴표 제거). 없으면 빈 문자열
envval() {
  local v
  v="$(grep -E "^[[:space:]]*$1=" "$APP_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  v="${v%%$'\r'}"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}

# ----------------------------------------------------------------------------- 사전 점검
[ "$(id -u)" -eq 0 ] && c_fail "root 로 실행하지 마세요. sudo 가능한 일반 사용자(ubuntu)로 실행합니다."
sudo -n true 2>/dev/null || sudo -v || c_fail "sudo 권한이 필요합니다."
[ -f "$APP_DIR/manage.py" ] || c_fail "manage.py 가 없습니다: $APP_DIR (레포 루트에서 실행하세요)"
cd "$APP_DIR"

# ----------------------------------------------------------------------------- 1. .env 검사
step "1. .env 필수 키 검사 ($APP_DIR/.env)"
[ -f .env ] || c_fail ".env 가 없습니다. Lightsail 의 .env 를 복사한 뒤 다시 실행하세요. (참고: .env.example)"

missing=()
for k in DJANGO_SECRET_KEY DJANGO_DB_ENGINE DJANGO_DB_NAME DJANGO_DB_USER DJANGO_DB_PASSWORD DJANGO_ALLOWED_HOSTS; do
  [ -n "$(envval "$k")" ] || missing+=("$k")
done
[ ${#missing[@]} -eq 0 ] || c_fail ".env 에 필수 키가 없습니다: ${missing[*]}"
[ "$(envval DJANGO_DB_ENGINE)" = "mysql" ] || c_fail ".env DJANGO_DB_ENGINE 이 'mysql' 이 아닙니다 (현재: '$(envval DJANGO_DB_ENGINE)'). SQLite 로 뜨면 빈 사이트가 됩니다."
case "$(envval DJANGO_SECRET_KEY)" in
  your-secret-key-here|django-insecure*) c_fail "DJANGO_SECRET_KEY 가 예시/개발용 값입니다." ;;
esac

# 권장 키 — 없으면 경고만 (해당 기능만 동작 안 함)
for k in ANTHROPIC_API_KEY DJANGO_EMAIL_HOST_USER DJANGO_EMAIL_HOST_PASSWORD DJANGO_ADMIN_EMAIL KAKAO_REST_API_KEY KAKAO_CLIENT_SECRET; do
  [ -n "$(envval "$k")" ] || c_warn ".env 에 $k 가 없습니다 (이메일/AI 칼럼/카카오 로그인 중 해당 기능 비활성)"
done
if [ "$(envval DEBUG)" != "False" ] && [ "$(envval DEBUG)" != "false" ]; then
  c_warn ".env DEBUG='$(envval DEBUG)' — 라이브(prod.py)는 무시하지만 cron/manage.py 는 base.py 를 쓰므로 False 권장"
fi
if [ "$(envval DJANGO_SECURE_SSL_REDIRECT)" = "false" ]; then
  c_warn "DJANGO_SECURE_SSL_REDIRECT=false 상태 — IP 검증용. certbot 적용 후 반드시 .env 에서 제거/true 로!"
fi

DB_NAME="$(envval DJANGO_DB_NAME)"; DB_USER="$(envval DJANGO_DB_USER)"; DB_PASS="$(envval DJANGO_DB_PASSWORD)"
DB_HOST="$(envval DJANGO_DB_HOST)"; DB_HOST="${DB_HOST:-127.0.0.1}"

# 공인 IP (nginx server_name / 안내용). OCI 는 NIC 에 사설 IP 만 있어 외부 조회
if [ -z "${SERVER_IP:-}" ]; then
  SERVER_IP="$(curl -fsS -m 5 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]' || true)"
fi
[ -n "$SERVER_IP" ] || c_warn "공인 IP 자동 조회 실패 — SERVER_IP=1.2.3.4 로 지정하면 nginx server_name 에 포함됩니다."
if [ -n "$SERVER_IP" ] && ! grep -q "$SERVER_IP" <<<"$(envval DJANGO_ALLOWED_HOSTS)"; then
  c_warn "DJANGO_ALLOWED_HOSTS 에 이 서버 IP($SERVER_IP) 가 없습니다 → IP 로 접속하면 400. 예: DJANGO_ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN,$SERVER_IP"
fi
chmod 600 .env 2>/dev/null || true        # 비밀 파일: 소유자(ubuntu)만. systemd 는 root 로 읽으므로 무관
c_ok ".env 검사 통과 (DB=$DB_NAME/$DB_USER@$DB_HOST, 호스트=$(envval DJANGO_ALLOWED_HOSTS))"

# ----------------------------------------------------------------------------- 2~4. 시스템
if [ "$SKIP_SYSTEM" -eq 0 ]; then
  step "2. 시스템 패키지 / 타임존 / 권한"
  if [ "$(timedatectl show -p Timezone --value 2>/dev/null)" != "$TIMEZONE" ]; then
    sudo timedatectl set-timezone "$TIMEZONE"; c_ok "타임존 → $TIMEZONE (crontab 시각 기준)"
  fi
  export DEBIAN_FRONTEND=noninteractive
  sudo apt-get update -qq
  # build-essential/python3-dev/pkg-config/default-libmysqlclient-dev : mysqlclient 소스 빌드 (aarch64 휠 부재 대비)
  # libjpeg-dev/zlib1g-dev : Pillow 소스 빌드 대비, libmagic1 : python-magic (MIME 검증), certbot : 9단계
  sudo apt-get install -y -qq \
    git curl ca-certificates rsync \
    python3 python3-venv python3-dev build-essential pkg-config \
    default-libmysqlclient-dev libjpeg-dev zlib1g-dev libffi-dev libssl-dev libmagic1 \
    mysql-server mysql-client \
    nginx certbot python3-certbot-nginx \
    iptables-persistent netfilter-persistent
  c_ok "apt 패키지 설치 완료 ($($PYTHON_BIN --version 2>&1))"

  # send_log_report: journalctl -u mysite (systemd-journal), /var/log/nginx/*.log (adm)
  for g in adm systemd-journal; do
    id -nG "$SERVICE_USER" | grep -qw "$g" || { sudo usermod -aG "$g" "$SERVICE_USER"; c_ok "$SERVICE_USER → 그룹 $g 추가 (재로그인 후 적용)"; }
  done
  # Ubuntu 24.04 는 홈이 750 → nginx(www-data) 가 staticfiles/, media/ 를 못 읽어 403. 통과(x) 권한만 준다.
  home_dir="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
  if [ -n "$home_dir" ] && [ "$(stat -c '%A' "$home_dir" | cut -c10)" != "x" ]; then
    sudo chmod o+x "$home_dir"; c_ok "chmod o+x $home_dir (nginx 정적/미디어 접근)"
  fi
  sudo mkdir -p /var/www/certbot
  # Lightsail crontab 과 동일 경로에 리포트 로그를 남길 수 있도록 미리 생성 (ubuntu 소유 → root crontab 불필요)
  [ -f "$REPORT_LOG" ] || { sudo touch "$REPORT_LOG"; sudo chown "$SERVICE_USER:$SERVICE_USER" "$REPORT_LOG"; }

  # gunicorn 은 access/error 로그를 자체 회전하지 않는다 (Lightsail 에서 75MB 까지 자람) → logrotate.
  # django.log/security.log 는 Django RotatingFileHandler 가 회전하므로 제외.
  tmp_lr="$(mktemp)"
  cat >"$tmp_lr" <<LR
${APP_DIR}/logs/gunicorn_*.log ${REPORT_LOG} ${APP_DIR}/logs/techchang_*.log {
    weekly
    maxsize 20M
    rotate 8
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    su ${SERVICE_USER} ${SERVICE_USER}
}
LR
  if ! sudo cmp -s "$tmp_lr" /etc/logrotate.d/techchang 2>/dev/null; then
    sudo install -m 644 "$tmp_lr" /etc/logrotate.d/techchang; c_ok "logrotate 등록 (/etc/logrotate.d/techchang)"
  fi
  rm -f "$tmp_lr"

  step "3. iptables 80/443 개방 (OCI: VCN 보안목록과 별개로 인스턴스 내부 방화벽)"
  for port in 80 443; do
    if sudo iptables -C INPUT -p tcp -m state --state NEW -m tcp --dport "$port" -j ACCEPT 2>/dev/null; then
      c_ok "iptables: $port/tcp 이미 허용"
    else
      # OCI 기본 규칙은 마지막에 REJECT 가 있으므로 그 앞(보통 6번째)에 삽입
      pos="$(sudo iptables -L INPUT -n --line-numbers | awk '/REJECT/{print $1; exit}')"
      if [ -n "$pos" ]; then sudo iptables -I INPUT "$pos" -p tcp -m state --state NEW -m tcp --dport "$port" -j ACCEPT
      else sudo iptables -A INPUT -p tcp -m state --state NEW -m tcp --dport "$port" -j ACCEPT; fi
      c_ok "iptables: $port/tcp 허용 규칙 삽입"
    fi
  done
  sudo netfilter-persistent save >/dev/null && c_ok "netfilter-persistent save (재부팅 후 유지)"

  step "4. MySQL: 서비스 / 타임존 테이블 / DB·사용자"
  sudo systemctl enable --now mysql >/dev/null
  # Django USE_TZ=True + MySQL 은 __date 조회 등에 CONVERT_TZ 를 쓰므로 타임존 테이블이 비어 있으면 결과가 빈다
  if [ "$(sudo mysql -Nse 'SELECT COUNT(*) FROM mysql.time_zone_name')" = "0" ]; then
    mysql_tzinfo_to_sql /usr/share/zoneinfo 2>/dev/null | sudo mysql -D mysql
    c_ok "MySQL 타임존 테이블 적재"
  else
    c_ok "MySQL 타임존 테이블 있음"
  fi
  # 비밀번호의 \ 와 ' 를 SQL 리터럴용으로 이스케이프
  pw_sql="${DB_PASS//\\/\\\\}"; pw_sql="${pw_sql//\'/\\\'}"
  sudo mysql <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE ${DB_COLLATION};
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${pw_sql}';
CREATE USER IF NOT EXISTS '${DB_USER}'@'127.0.0.1' IDENTIFIED BY '${pw_sql}';
ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${pw_sql}';
ALTER USER '${DB_USER}'@'127.0.0.1' IDENTIFIED BY '${pw_sql}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
  c_ok "DB '$DB_NAME' / 사용자 '$DB_USER' 준비 (비밀번호는 .env 값으로 동기화)"
  # .env 자격으로 실제 접속 확인
  MYSQL_PWD="$DB_PASS" mysql -h "$DB_HOST" -u "$DB_USER" -Nse 'SELECT 1' "$DB_NAME" >/dev/null \
    || c_fail ".env 의 DB 자격으로 접속 실패 (DJANGO_DB_HOST=$DB_HOST). 값을 확인하세요."
  c_ok "앱 자격으로 MySQL 접속 확인"
else
  c_info "--skip-system: 시스템/방화벽/MySQL 단계 건너뜀"
fi

# ----------------------------------------------------------------------------- 5. venv
step "5. venv ($VENV_DIR) + requirements-prod.txt"
if [ ! -x "$VENV_DIR/bin/python3" ]; then
  mkdir -p "$(dirname "$VENV_DIR")"
  "$PYTHON_BIN" -m venv "$VENV_DIR"; c_ok "venv 생성"
fi
"$VENV_DIR/bin/pip" install -q --upgrade pip wheel
"$VENV_DIR/bin/pip" install -q -r requirements-prod.txt
"$VENV_DIR/bin/python3" -c 'import MySQLdb, django; print("mysqlclient", MySQLdb.__version__, "/ Django", django.get_version())' \
  || c_fail "mysqlclient import 실패 — apt: default-libmysqlclient-dev pkg-config build-essential python3-dev 확인"
c_ok "의존성 설치 완료"

# ----------------------------------------------------------------------------- 6. Django
step "6. Django check / migrate / collectstatic ($SETTINGS)"
mkdir -p logs media backups staticfiles
if [ "$SERVICE_USER" != "$USER" ]; then
  # gunicorn 을 다른 계정(예: www-data)으로 돌리면 logs/media 를 두 주체가 쓴다.
  # 그룹 쓰기 + setgid 로 최대한 맞추지만, RotatingFileHandler 가 새로 만드는 회전 파일은 644 라
  # 다른 쪽이 못 쓰는 상황이 생길 수 있다 → SERVICE_USER=ubuntu(단일 계정) 권장.
  c_warn "SERVICE_USER=$SERVICE_USER ≠ 실행 계정 $USER — logs/media/staticfiles 를 그룹 $SERVICE_USER 쓰기 가능으로 맞춥니다"
  sudo chgrp -R "$SERVICE_USER" logs media staticfiles
  sudo chmod -R g+rwX logs media staticfiles
  sudo find logs media -type d -exec chmod g+s {} +
  sudo chmod 640 .env && sudo chgrp "$SERVICE_USER" .env
fi
export DJANGO_SETTINGS_MODULE="$SETTINGS"
"$VENV_DIR/bin/python3" manage.py check || c_fail "manage.py check 실패"
"$VENV_DIR/bin/python3" manage.py migrate --noinput || c_fail "migrate 실패"
# ManifestStaticFilesStorage: 여기서 실패하면 staticfiles.json 이 깨져 전 페이지 500 → 서비스 재시작 전에 중단
"$VENV_DIR/bin/python3" manage.py collectstatic --noinput | tail -n1 || c_fail "collectstatic 실패 — 서비스는 재시작하지 않았습니다"
[ -f staticfiles/staticfiles.json ] || c_fail "staticfiles/staticfiles.json 이 없습니다 (Manifest 생성 실패)"
c_ok "migrate / collectstatic 완료"

# ----------------------------------------------------------------------------- 7. systemd
step "7. systemd 유닛 $UNIT_FILE"
tmp_unit="$(mktemp)"
cat >"$tmp_unit" <<UNIT
# 생성: deploy_oci.sh (수정은 스크립트에서). 레포의 mysite.service 는 구 경로 기준의 참고용.
[Unit]
Description=TechChang Django Gunicorn (${SERVICE_NAME})
Documentation=https://docs.gunicorn.org/
After=network.target mysql.service
Wants=mysql.service
StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
Type=exec
Restart=on-failure
RestartSec=5
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
# .env 를 systemd 가 직접 주입 (settings 의 python-dotenv 로드와 이중 안전)
EnvironmentFile=${APP_DIR}/.env
Environment=DJANGO_SETTINGS_MODULE=${SETTINGS}
Environment=PYTHONPATH=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_DIR}/bin/gunicorn --config ${APP_DIR}/gunicorn.conf.py config.wsgi:application
ExecReload=/bin/kill -s HUP \$MAINPID
LimitNOFILE=65536
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT
if [ -f "$UNIT_FILE" ] && sudo cmp -s "$tmp_unit" "$UNIT_FILE"; then
  c_ok "유닛 변경 없음"
else
  sudo install -m 644 "$tmp_unit" "$UNIT_FILE"
  sudo systemctl daemon-reload
  c_ok "유닛 설치/갱신"
fi
rm -f "$tmp_unit"
sudo systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true

# ----------------------------------------------------------------------------- 8. nginx
step "8. nginx $NGINX_SITE"
if [ "$FORCE_NGINX" -eq 0 ] && [ -f "$NGINX_SITE" ] && sudo grep -qE 'listen[[:space:]]+443|managed by Certbot|ssl_certificate' "$NGINX_SITE"; then
  c_ok "기존 설정에 443/certbot 블록이 있어 덮어쓰지 않음 (강제: --force-nginx)"
else
  tmp_nginx="$(mktemp)"
  cat >"$tmp_nginx" <<NGINX
# 생성: deploy_oci.sh — HTTP 전용 초기 설정.
# certbot --nginx 가 이 파일에 443 블록을 추가하면 deploy_oci.sh 는 더 이상 덮어쓰지 않는다.
# 최종 강화 설정(444 default_server, HSTS 헤더, 캐시 세부)은 레포 nginx.conf 참고.

# 미등록 Host(스캐너·봇) 는 응답 없이 종료 — DisallowedHost 로그 노이즈 방지
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 444;
}

server {
    listen 80;
    listen [::]:80;
    # 서버 IP 는 DNS 전환 전 검증용 — 전환 후 제거해도 됨
    server_name ${DOMAIN} www.${DOMAIN}${SERVER_IP:+ $SERVER_IP};

    # Django FILE_UPLOAD_MAX_MEMORY_SIZE(20MB) 와 일치
    client_max_body_size 20M;
    client_body_timeout 60s;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        location ~ /\\. { deny all; }
    }

    location /media/ {
        alias ${APP_DIR}/media/;
        expires 7d;
        add_header Cache-Control "public";
        location ~* \\.(php|pl|py|jsp|asp|sh|cgi)\$ { deny all; }
    }

    location /robots.txt  { alias ${APP_DIR}/static/robots.txt; }
    location /favicon.ico { alias ${APP_DIR}/static/favicon.ico; log_not_found off; }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    access_log /var/log/nginx/techchang_access.log;
    error_log  /var/log/nginx/techchang_error.log;
}
NGINX
  sudo install -m 644 "$tmp_nginx" "$NGINX_SITE"; rm -f "$tmp_nginx"
  c_ok "HTTP 설정 작성"
fi
sudo ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/techchang
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t || c_fail "nginx -t 실패"
sudo systemctl enable nginx >/dev/null 2>&1 || true
sudo systemctl reload nginx || sudo systemctl restart nginx
c_ok "nginx 적용"

# ----------------------------------------------------------------------------- 9. 재시작 + 헬스체크
if [ "$NO_RESTART" -eq 1 ]; then
  c_info "--no-restart: 서비스 재시작 생략"; exit 0
fi
step "9. $SERVICE_NAME 재시작 + 헬스체크"
sudo systemctl restart "$SERVICE_NAME"
sleep 3
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  sudo journalctl -u "$SERVICE_NAME" -n 40 --no-pager >&2
  c_fail "$SERVICE_NAME 이 기동되지 않았습니다 (위 로그 확인)"
fi
code="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $DOMAIN" http://127.0.0.1:8000/ || true)"
case "$code" in
  200)      c_ok "gunicorn 응답 200" ;;
  301|302)  c_ok "gunicorn 응답 $code (SECURE_SSL_REDIRECT=True → HTTPS 리다이렉트, 정상. IP 검증은 런북 6단계 참고)" ;;
  *)        c_warn "gunicorn 응답 코드 $code — journalctl -u $SERVICE_NAME -n 50 확인" ;;
esac
code="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $DOMAIN" http://127.0.0.1/static/style.css || true)"
[ "$code" = "200" ] && c_ok "nginx 정적 파일 200" || c_warn "nginx /static/style.css → $code (홈 디렉터리 권한/collectstatic 확인)"

printf '\n'
c_ok "배포 완료. 다음: 런북 docs/MIGRATION_OCI.md 의 다음 단계 진행"
c_info "상태: sudo systemctl status $SERVICE_NAME nginx --no-pager | 로그: sudo journalctl -u $SERVICE_NAME -n 50"
