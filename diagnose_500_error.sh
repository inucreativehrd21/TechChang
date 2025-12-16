#!/bin/bash

# 500 에러 진단 스크립트

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}500 에러 진단${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 1. 최근 Gunicorn/Django 로그 확인
echo -e "${YELLOW}Step 1: 최근 Django 로그 확인${NC}"
echo ""
sudo journalctl -u mysite -n 50 --no-pager
echo ""

# 2. Python Traceback 찾기
echo -e "${YELLOW}Step 2: Python 에러 추적${NC}"
echo ""
sudo journalctl -u mysite | grep -A 30 "Traceback" | tail -50
echo ""

# 3. Nginx 에러 로그 확인
echo -e "${YELLOW}Step 3: Nginx 에러 로그${NC}"
echo ""
sudo tail -30 /var/log/nginx/techchang_error.log
echo ""

# 4. 환경 변수 확인
echo -e "${YELLOW}Step 4: Django 환경 변수 확인${NC}"
echo ""
cd /home/ubuntu/projects/mysite
source venv/bin/activate
echo "DJANGO_SETTINGS_MODULE:"
systemctl show mysite | grep Environment
echo ""

# 5. Django 설정 검증
echo -e "${YELLOW}Step 5: Django 설정 검증${NC}"
echo ""
python manage.py check --deploy
echo ""

# 6. 정적 파일 확인
echo -e "${YELLOW}Step 6: 정적 파일 디렉토리 확인${NC}"
echo ""
ls -la /home/ubuntu/projects/mysite/staticfiles/ | head -20
echo ""

# 7. 데이터베이스 연결 확인
echo -e "${YELLOW}Step 7: 데이터베이스 확인${NC}"
echo ""
sqlite3 /home/ubuntu/projects/mysite/db.sqlite3 "SELECT name FROM sqlite_master WHERE type='table' LIMIT 10;"
echo ""

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}진단 완료${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
