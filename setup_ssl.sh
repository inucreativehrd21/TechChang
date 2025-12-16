#!/bin/bash

# SSL 인증서 발급 및 HTTPS 설정 스크립트
# 서비스가 HTTP로 정상 작동한 후 실행하세요

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}TechChang SSL 인증서 발급 및 HTTPS 설정${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 1. Certbot 설치 확인
echo -e "${YELLOW}Step 1: Certbot 설치 확인${NC}"
if ! command -v certbot &> /dev/null; then
    echo "Certbot 설치 중..."
    sudo apt update
    sudo apt install -y certbot python3-certbot-nginx
    echo "✓ Certbot 설치 완료"
else
    echo "✓ Certbot 이미 설치됨"
fi
echo ""

# 2. 도메인 확인
echo -e "${YELLOW}Step 2: 도메인 DNS 확인${NC}"
echo "techchang.com의 A 레코드가 43.203.93.244를 가리키는지 확인 중..."
DOMAIN_IP=$(dig +short techchang.com @8.8.8.8 | tail -n1)
echo "techchang.com → $DOMAIN_IP"

if [ "$DOMAIN_IP" != "43.203.93.244" ]; then
    echo -e "${RED}⚠️ 도메인이 올바른 IP를 가리키지 않습니다!${NC}"
    echo "계속하시겠습니까? (y/n)"
    read -p "선택: " continue_anyway
    if [ "$continue_anyway" != "y" ]; then
        exit 1
    fi
else
    echo "✓ 도메인 DNS 설정 올바름"
fi
echo ""

# 3. SSL 인증서 발급
echo -e "${YELLOW}Step 3: Let's Encrypt SSL 인증서 발급${NC}"
echo "도메인: techchang.com, www.techchang.com"
echo ""

sudo certbot certonly --nginx \
    -d techchang.com \
    -d www.techchang.com \
    --non-interactive \
    --agree-tos \
    --email noreply@techchang.com \
    || {
        echo -e "${RED}SSL 인증서 발급 실패${NC}"
        echo "수동으로 발급을 시도하려면:"
        echo "  sudo certbot --nginx -d techchang.com -d www.techchang.com"
        exit 1
    }

echo ""
echo "✓ SSL 인증서 발급 완료"
echo ""

# 4. Nginx 설정을 HTTPS 버전으로 교체
echo -e "${YELLOW}Step 4: Nginx HTTPS 설정 적용${NC}"

sudo cp /home/ubuntu/projects/mysite/nginx.conf /etc/nginx/sites-available/techchang
sudo ln -sf /etc/nginx/sites-available/techchang /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Nginx 설정 테스트
if sudo nginx -t; then
    echo "✓ Nginx 설정 테스트 통과"
else
    echo -e "${RED}Nginx 설정 오류${NC}"
    exit 1
fi
echo ""

# 5. Nginx 재시작
echo -e "${YELLOW}Step 5: Nginx 재시작${NC}"
sudo systemctl reload nginx
echo "✓ Nginx 재시작 완료"
echo ""

# 6. 자동 갱신 설정
echo -e "${YELLOW}Step 6: SSL 인증서 자동 갱신 설정${NC}"
sudo certbot renew --dry-run
echo "✓ 자동 갱신 테스트 완료"
echo ""

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}🎉 HTTPS 설정 완료!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "웹사이트 접속: https://techchang.com"
echo ""
echo "SSL 인증서 정보:"
sudo certbot certificates
echo ""
