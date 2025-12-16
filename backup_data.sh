#!/bin/bash

# 기존 서버 데이터 백업 스크립트
# 사용법: ./backup_data.sh

set -e

echo "======================================"
echo "TechChang 데이터 백업 시작"
echo "======================================"

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 설정
PROJECT_DIR="/home/ubuntu/projects/mysite"
BACKUP_DIR="$HOME/backups"
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)

# 백업 디렉토리 생성
echo -e "${GREEN}[1/6] 백업 디렉토리 생성 중...${NC}"
mkdir -p $BACKUP_DIR

# Gunicorn 중지 여부 확인
echo -e "${YELLOW}[2/6] 서비스 중지 여부 확인...${NC}"
read -p "데이터 일관성을 위해 Gunicorn을 중지하시겠습니까? (y/n): " STOP_SERVICE

if [ "$STOP_SERVICE" = "y" ]; then
    echo "Gunicorn 중지 중..."
    sudo systemctl stop gunicorn
    RESTART_NEEDED=true
else
    echo "서비스를 계속 실행합니다."
    RESTART_NEEDED=false
fi

# 데이터베이스 백업
echo -e "${GREEN}[3/6] 데이터베이스 백업 중...${NC}"
if [ -f "$PROJECT_DIR/db.sqlite3" ]; then
    cp $PROJECT_DIR/db.sqlite3 $BACKUP_DIR/db_${BACKUP_DATE}.sqlite3
    echo "✓ 데이터베이스 백업 완료: db_${BACKUP_DATE}.sqlite3"
    ls -lh $BACKUP_DIR/db_${BACKUP_DATE}.sqlite3
else
    echo "⚠ 경고: db.sqlite3 파일을 찾을 수 없습니다!"
fi

# 미디어 파일 백업
echo -e "${GREEN}[4/6] 미디어 파일 백업 중...${NC}"
if [ -d "$PROJECT_DIR/media" ]; then
    cd $PROJECT_DIR
    tar -czf $BACKUP_DIR/media_${BACKUP_DATE}.tar.gz media/
    echo "✓ 미디어 파일 백업 완료: media_${BACKUP_DATE}.tar.gz"
    ls -lh $BACKUP_DIR/media_${BACKUP_DATE}.tar.gz
else
    echo "⚠ 경고: media 디렉토리를 찾을 수 없습니다!"
fi

# .env 파일 백업
echo -e "${GREEN}[5/6] 환경변수 파일 백업 중...${NC}"
if [ -f "$PROJECT_DIR/.env" ]; then
    cp $PROJECT_DIR/.env $BACKUP_DIR/.env_backup
    echo "✓ .env 파일 백업 완료: .env_backup"
else
    echo "⚠ 경고: .env 파일을 찾을 수 없습니다!"
fi

# 서비스 재시작
if [ "$RESTART_NEEDED" = true ]; then
    echo -e "${GREEN}[6/6] Gunicorn 재시작 중...${NC}"
    sudo systemctl start gunicorn
    echo "✓ Gunicorn 재시작 완료"
else
    echo -e "${GREEN}[6/6] 서비스 재시작 스킵${NC}"
fi

# 백업 결과 요약
echo ""
echo "======================================"
echo "백업 완료!"
echo "======================================"
echo "백업 위치: $BACKUP_DIR"
echo ""
echo "백업된 파일 목록:"
ls -lh $BACKUP_DIR/*${BACKUP_DATE}* $BACKUP_DIR/.env_backup 2>/dev/null || true
echo ""
echo "다음 단계:"
echo "1. 로컬로 다운로드:"
echo "   scp -i your-key.pem ubuntu@$(curl -s ifconfig.me):$BACKUP_DIR/db_${BACKUP_DATE}.sqlite3 ./"
echo "   scp -i your-key.pem ubuntu@$(curl -s ifconfig.me):$BACKUP_DIR/media_${BACKUP_DATE}.tar.gz ./"
echo "   scp -i your-key.pem ubuntu@$(curl -s ifconfig.me):$BACKUP_DIR/.env_backup ./"
echo ""
echo "2. 또는 한 번에:"
echo "   scp -i your-key.pem 'ubuntu@$(curl -s ifconfig.me):$BACKUP_DIR/{db_${BACKUP_DATE}.sqlite3,media_${BACKUP_DATE}.tar.gz,.env_backup}' ./"
echo ""
