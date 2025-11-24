#!/bin/bash

echo "=========================================="
echo "게임 센터 새 디자인 적용"
echo "Apply New Premium Design"
echo "=========================================="
echo ""

PROJECT_DIR=~/projects/mysite
cd $PROJECT_DIR

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}1. 템플릿 백업${NC}"
cp templates/pybo/games_index.html templates/pybo/games_index.html.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null
echo -e "${GREEN}✓${NC} 백업 완료"
echo ""

echo -e "${CYAN}2. Django 캐시 클리어${NC}"
# Python 캐시
find . -name "*.pyc" -delete
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
echo -e "${GREEN}✓${NC} Python 캐시 삭제"

# Django 캐시
python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Django cache cleared')"
echo -e "${GREEN}✓${NC} Django 캐시 클리어"
echo ""

echo -e "${CYAN}3. 정적 파일 수집${NC}"
echo "yes" | python manage.py collectstatic > /dev/null 2>&1
echo -e "${GREEN}✓${NC} 정적 파일 수집 완료"
echo ""

echo -e "${CYAN}4. 서비스 재시작${NC}"
sudo systemctl stop mysite.service
sleep 2
sudo systemctl stop nginx
sleep 2

# 프로세스 정리
pkill -f gunicorn
pkill -f daphne
sleep 1

sudo systemctl start mysite.service
sleep 3
sudo systemctl start nginx
sleep 2

echo -e "${GREEN}✓${NC} 서비스 재시작 완료"
echo ""

echo -e "${CYAN}5. 서비스 상태 확인${NC}"
if sudo systemctl is-active --quiet mysite.service; then
    echo -e "${GREEN}✓${NC} mysite.service: active"
else
    echo -e "${RED}✗${NC} mysite.service: inactive"
fi

if sudo systemctl is-active --quiet nginx; then
    echo -e "${GREEN}✓${NC} nginx: active"
else
    echo -e "${RED}✗${NC} nginx: inactive"
fi
echo ""

echo -e "${GREEN}=========================================="
echo "✓ 새 디자인 적용 완료!"
echo "==========================================${NC}"
echo ""
echo "브라우저에서 확인하세요:"
echo "  1. Ctrl + Shift + R (강제 새로고침)"
echo "  2. 또는 시크릿 모드에서 접속"
echo ""
echo "URL: http://your-server-ip/pybo/games/"
echo ""
