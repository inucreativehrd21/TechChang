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
(crontab -l 2>/dev/null | grep -v 'send_log_report' | grep -v 'send_visitor_report' | grep -v 'backup_db' | grep -v 'auto_write_columns'; echo "") | crontab -

# ─── cron 항목 ──────────────────────────────────────────────────────
# 매일 새벽 3시: DB 로컬 백업 (최근 7개 보관)
CRON_BACKUP="0 3 * * * cd $SITE_DIR && $VENV_PYTHON $MANAGE backup_db --keep 7 --dest $BACKUP_DIR >> $LOG_FILE 2>&1"

# 매주 월요일 새벽 3시 30분: DB 주간 백업 + 이메일 전송 (최근 4개 보관)
CRON_WEEKLY_BACKUP="30 3 * * 1 cd $SITE_DIR && $VENV_PYTHON $MANAGE backup_db --keep 4 --dest $BACKUP_DIR --email $ADMIN_EMAIL >> $LOG_FILE 2>&1"

# 매일 오전 8시: 일간 리포트 이메일
CRON_DAILY="0 8 * * * cd $SITE_DIR && $VENV_PYTHON $MANAGE send_log_report --hours 24 --to $ADMIN_EMAIL >> $LOG_FILE 2>&1"

# 매주 월요일 오전 8시: 주간 리포트 이메일
CRON_WEEKLY="0 8 * * 1 cd $SITE_DIR && $VENV_PYTHON $MANAGE send_log_report --hours 168 --to $ADMIN_EMAIL >> $LOG_FILE 2>&1"

# 매주 월요일 오전 8시 30분: 방문자 주간 리포트 이메일 (서버 리포트와 분리)
CRON_VISITOR_WEEKLY="30 8 * * 1 cd $SITE_DIR && $VENV_PYTHON $MANAGE send_visitor_report --period weekly --to $ADMIN_EMAIL >> $LOG_FILE 2>&1"

# 매월 1일 오전 9시: 방문자 월간 리포트 이메일 (지난달 총합·일평균·월별 추이)
CRON_VISITOR_MONTHLY="0 9 1 * * cd $SITE_DIR && $VENV_PYTHON $MANAGE send_visitor_report --period monthly --to $ADMIN_EMAIL >> $LOG_FILE 2>&1"

# 트렌드 칼럼 자동 작성 (주제별 별도 실행 - 각 1개씩)
# 매주 화요일 오전 10시: HRD 칼럼
# 매주 목요일 오전 10시: 데이터분석 칼럼
# 매주 토요일 오전 10시: 프로그래밍 칼럼
COLUMN_LOG="/var/log/techchang_columns.log"
CRON_COLUMN_TUE="0 10 * * 2 cd $SITE_DIR && $VENV_PYTHON $MANAGE auto_write_columns --topic hrd >> $COLUMN_LOG 2>&1"
CRON_COLUMN_THU="0 10 * * 4 cd $SITE_DIR && $VENV_PYTHON $MANAGE auto_write_columns --topic data >> $COLUMN_LOG 2>&1"
CRON_COLUMN_SAT="0 10 * * 6 cd $SITE_DIR && $VENV_PYTHON $MANAGE auto_write_columns --topic coding >> $COLUMN_LOG 2>&1"
# ────────────────────────────────────────────────────────────────────

(crontab -l 2>/dev/null; echo "$CRON_BACKUP"; echo "$CRON_WEEKLY_BACKUP"; echo "$CRON_DAILY"; echo "$CRON_WEEKLY"; echo "$CRON_VISITOR_WEEKLY"; echo "$CRON_VISITOR_MONTHLY"; echo "$CRON_COLUMN_TUE"; echo "$CRON_COLUMN_THU"; echo "$CRON_COLUMN_SAT") | crontab -

echo "✅ cron 등록 완료!"
echo ""
echo "현재 crontab:"
crontab -l | grep -E 'backup_db|send_log_report|send_visitor_report|auto_write_columns'
echo ""
echo "📝 서버 로그: $LOG_FILE"
echo "📝 칼럼 로그: $COLUMN_LOG"
echo "💾 백업 경로: $BACKUP_DIR"
echo ""
echo "🧪 지금 바로 테스트:"
echo "   $VENV_PYTHON $MANAGE backup_db --keep 7 --dest $BACKUP_DIR"
echo "   $VENV_PYTHON $MANAGE send_log_report --hours 24 --to $ADMIN_EMAIL --dry-run"
echo "   $VENV_PYTHON $MANAGE send_visitor_report --period weekly --dry-run   # 방문자 리포트 미리보기"
echo "   $VENV_PYTHON $MANAGE auto_write_columns --dry-run          # 칼럼 미리보기 (ANTHROPIC_API_KEY 필요)"
echo "   $VENV_PYTHON $MANAGE auto_write_columns --topic hrd        # HRD 칼럼 1개 즉시 게시"
