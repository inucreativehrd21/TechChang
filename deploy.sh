#!/bin/bash

# Django mysite 배포 스크립트
# 사용법: ./deploy.sh [production|staging]

set -e  # 오류 시 즉시 중단

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 로그 함수
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 환경 설정
ENVIRONMENT=${1:-production}
PROJECT_ROOT="/srv/mysite"
VENV_PATH="$PROJECT_ROOT/venv"
BACKUP_DIR="/srv/backups/mysite"

log_info "Django mysite 배포 시작 (환경: $ENVIRONMENT)"

# 환경 확인
if [[ "$ENVIRONMENT" != "production" && "$ENVIRONMENT" != "staging" ]]; then
    log_error "지원되지 않는 환경입니다: $ENVIRONMENT"
    log_info "사용법: ./deploy.sh [production|staging]"
    exit 1
fi

# 권한 확인
if [[ $EUID -ne 0 ]]; then
    log_error "이 스크립트는 root 권한으로 실행해야 합니다."
    exit 1
fi

# 백업 디렉토리 생성
mkdir -p "$BACKUP_DIR"

# 1. 데이터베이스 백업
log_info "데이터베이스 백업 중..."
BACKUP_FILE="$BACKUP_DIR/db_$(date +%Y%m%d_%H%M%S).sqlite3"
if [[ -f "$PROJECT_ROOT/db.sqlite3" ]]; then
    cp "$PROJECT_ROOT/db.sqlite3" "$BACKUP_FILE"
    log_info "데이터베이스 백업 완료: $BACKUP_FILE"
fi

# 2. 정적 파일 백업
log_info "기존 정적 파일 백업 중..."
if [[ -d "$PROJECT_ROOT/staticfiles" ]]; then
    tar -czf "$BACKUP_DIR/staticfiles_$(date +%Y%m%d_%H%M%S).tar.gz" -C "$PROJECT_ROOT" staticfiles/
fi

# 3. 가상환경 활성화
log_info "가상환경 활성화 중..."
source "$VENV_PATH/bin/activate"

# 4. 의존성 설치
log_info "의존성 설치/업데이트 중..."
cd "$PROJECT_ROOT"
pip install --upgrade pip
pip install -r requirements.txt

# 5. 환경 변수 설정
export DJANGO_SETTINGS_MODULE="config.settings.$ENVIRONMENT"

# 6. 데이터베이스 마이그레이션
log_info "데이터베이스 마이그레이션 실행 중..."
python manage.py makemigrations --check --dry-run || {
    log_warn "새로운 마이그레이션이 필요합니다."
    python manage.py makemigrations
}
python manage.py migrate --noinput

# 7. 정적 파일 수집
log_info "정적 파일 수집 중..."
python manage.py collectstatic --noinput --clear

# 8. 로그 디렉토리 생성
log_info "로그 디렉토리 설정 중..."
mkdir -p "$PROJECT_ROOT/logs"
chown -R www-data:www-data "$PROJECT_ROOT/logs"
chmod 755 "$PROJECT_ROOT/logs"

# 9. 권한 설정
log_info "파일 권한 설정 중..."
chown -R www-data:www-data "$PROJECT_ROOT"
chmod -R 755 "$PROJECT_ROOT"
chmod -R 644 "$PROJECT_ROOT/staticfiles"
chmod -R 755 "$PROJECT_ROOT/media"

# 10. Gunicorn 서비스 재시작
log_info "Gunicorn 서비스 재시작 중..."
systemctl daemon-reload
systemctl restart mysite
systemctl enable mysite

# 11. Nginx 설정 확인 및 재시작
log_info "Nginx 설정 확인 및 재시작 중..."
nginx -t && systemctl reload nginx

# 12. 서비스 상태 확인
log_info "서비스 상태 확인 중..."
sleep 5
systemctl is-active --quiet mysite && log_info "✅ Gunicorn 서비스 정상 동작" || log_error "❌ Gunicorn 서비스 오류"
systemctl is-active --quiet nginx && log_info "✅ Nginx 서비스 정상 동작" || log_error "❌ Nginx 서비스 오류"

# 13. 헬스 체크
log_info "애플리케이션 헬스 체크 중..."
PROD_HEALTH_URL="https://tc.o-r.kr/"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$PROD_HEALTH_URL" || echo "000")
if [[ "$HTTP_STATUS" == "200" ]]; then
    log_info "✅ 애플리케이션 헬스 체크 성공"
else
    log_warn "⚠️  애플리케이션 헬스 체크 실패 (HTTP: $HTTP_STATUS)"
fi

# 14. 배포 완료
log_info "🚀 배포 완료!"
log_info "백업 위치: $BACKUP_DIR"
log_info "로그 확인: journalctl -u mysite -f"
log_info "Nginx 로그: tail -f /var/log/nginx/mysite_*.log"

# 15. 정리 작업 (7일 이전 백업 삭제)
log_info "오래된 백업 정리 중..."
find "$BACKUP_DIR" -name "*.sqlite3" -mtime +7 -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +7 -delete

log_info "배포 스크립트 완료 ✨"