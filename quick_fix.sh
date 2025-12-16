#!/bin/bash

# 빠른 수정 및 재시작 스크립트

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}TechChang 빠른 수정 및 재시작${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

PROJECT_DIR="/home/ubuntu/projects/mysite"
cd $PROJECT_DIR

# 서비스 이름 자동 감지
detect_service_name() {
    if systemctl list-units --type=service --all | grep -q "mysite.service"; then
        echo "mysite"
    elif systemctl list-units --type=service --all | grep -q "gunicorn.service"; then
        echo "gunicorn"
    else
        echo "gunicorn"
    fi
}

SERVICE_NAME=$(detect_service_name)

echo -e "${YELLOW}Step 1: Git 최신 코드 가져오기${NC}"
git pull
echo "✓ Git pull 완료"
echo ""

echo -e "${YELLOW}Step 2: 가상환경 활성화${NC}"
source venv/bin/activate
echo "✓ 가상환경 활성화 완료"
echo ""

echo -e "${YELLOW}Step 3: 정적 파일 재수집${NC}"
python manage.py collectstatic --noinput --clear
echo "✓ 정적 파일 수집 완료"
echo ""

echo -e "${YELLOW}Step 4: Django 서비스($SERVICE_NAME) 재시작${NC}"
sudo systemctl restart $SERVICE_NAME
sleep 2
echo "✓ Django 재시작 완료"
echo ""

echo -e "${YELLOW}Step 5: Nginx 재시작${NC}"
sudo systemctl restart nginx
sleep 1
echo "✓ Nginx 재시작 완료"
echo ""

echo -e "${YELLOW}Step 6: 서비스 상태 확인${NC}"
echo ""
echo "=== Django 서비스 상태 ==="
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    echo -e "${GREEN}✓ Django 서비스 실행 중${NC}"
    sudo systemctl status $SERVICE_NAME --no-pager -l | head -10
else
    echo -e "${RED}✗ Django 서비스 실행 안됨${NC}"
    sudo systemctl status $SERVICE_NAME --no-pager -l | tail -20
fi

echo ""
echo "=== Nginx 상태 ==="
if sudo systemctl is-active --quiet nginx; then
    echo -e "${GREEN}✓ Nginx 실행 중${NC}"
else
    echo -e "${RED}✗ Nginx 실행 안됨${NC}"
fi

echo ""
echo "=== 포트 확인 ==="
sudo ss -tulpn | grep -E ':(80|8000)\s'

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ 완료! 브라우저에서 http://43.203.93.244 접속 테스트${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "문제가 계속되면 로그 확인:"
echo "  sudo journalctl -u $SERVICE_NAME -n 50"
echo ""
