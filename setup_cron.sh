#!/bin/bash
# =====================================================
# 서버 자동화 cron 설정 스크립트
# 서버에서 실행: bash setup_cron.sh
# =====================================================

SITE_DIR="$(cd "$(dirname "$0")" && pwd)"  # 스크립트 위치 자동 감지

# venv 경로 자동 감지: 서버(venvs/mysite) 우선, 없으면 프로젝트 내 venv
if [ -f "/home/ubuntu/venvs/mysite/bin/python3" ]; then
    VENV_PYTHON="/home/ubuntu/venvs/mysite/bin/python3"
elif [ -f "$SITE_DIR/venv/bin/python" ]; then
    VENV_PYTHON="$SITE_DIR/venv/bin/python"
else
    echo "오류: Python 가상환경을 찾을 수 없습니다."
    exit 1
fi
echo "Python 경로: $VENV_PYTHON"
MANAGE="$SITE_DIR/manage.py"
LOG_FILE="/var/log/techchang_report.log"
BACKUP_DIR="$SITE_DIR/backups"

# 수신 이메일 (.env에서 읽어오기)
ADMIN_EMAIL=$(grep DJANGO_ADMIN_EMAIL "$SITE_DIR/.env" 2>/dev/null | cut -d '=' -f2 | tr -d '"' | tr -d "'")
if [ -z "$ADMIN_EMAIL" ]; then
    echo "❌ DJANGO_ADMIN_EMAIL이 .env에 없습니다. 직접 입력하세요:"
    read -r ADMIN_EMAIL
fi

echo "📧 리포트 수신 이메일: $ADMIN_EMAIL"
echo ""

# 기존 cron에서 techchang 관련 항목 제거 후 재등록
(crontab -l 2>/dev/null | grep -v 'send_log_report' | grep -v 'backup_db'; echo "") | crontab -

# ─── cron 항목 ──────────────────────────────────────────────────────
# 매일 새벽 3시: DB 로컬 백업 (최근 7개 보관)
CRON_BACKUP="0 3 * * * cd $SITE_DIR && $VENV_PYTHON $MANAGE backup_db --keep 7 --dest $BACKUP_DIR >> $LOG_FILE 2>&1"

# 매주 월요일 새벽 3시 30분: DB 주간 백업 + 이메일 전송 (최근 4개 보관)
CRON_WEEKLY_BACKUP="30 3 * * 1 cd $SITE_DIR && $VENV_PYTHON $MANAGE backup_db --keep 4 --dest $BACKUP_DIR --email $ADMIN_EMAIL >> $LOG_FILE 2>&1"

# 매일 오전 8시: 일간 리포트 이메일
CRON_DAILY="0 8 * * * cd $SITE_DIR && $VENV_PYTHON $MANAGE send_log_report --hours 24 --to $ADMIN_EMAIL >> $LOG_FILE 2>&1"

# 매주 월요일 오전 8시: 주간 리포트 이메일
CRON_WEEKLY="0 8 * * 1 cd $SITE_DIR && $VENV_PYTHON $MANAGE send_log_report --hours 168 --to $ADMIN_EMAIL >> $LOG_FILE 2>&1"
# ────────────────────────────────────────────────────────────────────

(crontab -l 2>/dev/null; echo "$CRON_BACKUP"; echo "$CRON_WEEKLY_BACKUP"; echo "$CRON_DAILY"; echo "$CRON_WEEKLY") | crontab -

echo "✅ cron 등록 완료!"
echo ""
echo "현재 crontab:"
crontab -l | grep -E 'backup_db|send_log_report'
echo ""
echo "📝 로그 파일: $LOG_FILE"
echo "💾 백업 경로: $BACKUP_DIR"
echo ""
echo "🧪 지금 바로 테스트:"
echo "   $VENV_PYTHON $MANAGE backup_db --keep 7 --dest $BACKUP_DIR"
echo "   $VENV_PYTHON $MANAGE backup_db --keep 4 --dest $BACKUP_DIR --email $ADMIN_EMAIL"
echo "   $VENV_PYTHON $MANAGE send_log_report --hours 24 --to $ADMIN_EMAIL --dry-run"
