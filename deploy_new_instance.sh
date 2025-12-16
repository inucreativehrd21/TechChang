#!/bin/bash

# TechChang 커뮤니티 사이트 - 새 인스턴스 배포 스크립트
# Ubuntu 22.04 LTS 기준

set -e  # 에러 발생 시 스크립트 중단

echo "======================================"
echo "TechChang 커뮤니티 사이트 배포 시작"
echo "======================================"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 설정 변수
PROJECT_NAME="mysite"
PROJECT_DIR="/home/ubuntu/projects/$PROJECT_NAME"
VENV_DIR="$PROJECT_DIR/venv"
DOMAIN="techchang.com"

# 1. 시스템 업데이트
echo -e "${GREEN}[1/10] 시스템 패키지 업데이트 중...${NC}"
sudo apt update
sudo apt upgrade -y

# 2. 필수 패키지 설치
echo -e "${GREEN}[2/10] 필수 패키지 설치 중...${NC}"
sudo apt install -y python3-pip python3-venv python3-dev \
    nginx postgresql postgresql-contrib \
    git curl wget \
    build-essential libssl-dev libffi-dev \
    certbot python3-certbot-nginx

# 3. 프로젝트 디렉토리 생성
echo -e "${GREEN}[3/10] 프로젝트 디렉토리 생성 중...${NC}"
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR

# 4. Git 저장소 클론 (선택사항 - 수동으로 파일 업로드했다면 스킵)
# echo -e "${GREEN}[4/10] Git 저장소 클론 중...${NC}"
# git clone <your-repo-url> .

echo -e "${YELLOW}[4/10] Git 클론은 스킵합니다. 파일을 수동으로 업로드하세요.${NC}"

# 5. 가상환경 생성 및 활성화
echo -e "${GREEN}[5/10] Python 가상환경 생성 중...${NC}"
python3 -m venv $VENV_DIR
source $VENV_DIR/bin/activate

# 6. Python 패키지 설치
echo -e "${GREEN}[6/10] Python 패키지 설치 중...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# 7. 환경변수 파일 설정
echo -e "${GREEN}[7/10] 환경변수 파일 설정 중...${NC}"
if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${YELLOW}⚠️  .env 파일을 생성했습니다. 반드시 다음 값들을 설정하세요:${NC}"
    echo "  - DJANGO_SECRET_KEY (새로 생성 필요)"
    echo "  - OPENAI_API_KEY"
    echo "  - KAKAO_REST_API_KEY"
    echo "  - KAKAO_CLIENT_SECRET"
    echo "  - 기타 API 키들"
    echo ""
    echo "SECRET_KEY 생성 명령어:"
    python manage.py shell -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
    read -p "환경변수를 설정한 후 Enter를 눌러 계속하세요..."
fi

# 8. Django 설정
echo -e "${GREEN}[8/10] Django 초기 설정 중...${NC}"

# 정적 파일 수집
python manage.py collectstatic --noinput

# 데이터베이스 마이그레이션
python manage.py migrate

# 관리자 계정 생성 (선택사항)
echo -e "${YELLOW}Django 관리자 계정을 생성하시겠습니까? (y/n)${NC}"
read -p "선택: " create_superuser
if [ "$create_superuser" = "y" ]; then
    python manage.py createsuperuser
fi

# 9. Gunicorn 설정 및 서비스 등록
echo -e "${GREEN}[9/10] Gunicorn 서비스 설정 중...${NC}"
sudo tee /etc/systemd/system/gunicorn.service > /dev/null <<EOF
[Unit]
Description=Gunicorn daemon for TechChang Django project
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$VENV_DIR/bin"
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$VENV_DIR/bin/gunicorn \\
    --workers 3 \\
    --bind 127.0.0.1:8000 \\
    --timeout 120 \\
    --access-logfile /var/log/gunicorn/access.log \\
    --error-logfile /var/log/gunicorn/error.log \\
    config.wsgi:application

[Install]
WantedBy=multi-user.target
EOF

# Gunicorn 로그 디렉토리 생성
sudo mkdir -p /var/log/gunicorn
sudo chown ubuntu:www-data /var/log/gunicorn

# Gunicorn 서비스 시작
sudo systemctl daemon-reload
sudo systemctl start gunicorn
sudo systemctl enable gunicorn

# 10. Nginx 설정
echo -e "${GREEN}[10/10] Nginx 설정 중...${NC}"

# Nginx 설정 파일 복사
sudo cp nginx.conf /etc/nginx/sites-available/techchang

# 기본 사이트 비활성화
sudo rm -f /etc/nginx/sites-enabled/default

# TechChang 사이트 활성화
sudo ln -sf /etc/nginx/sites-available/techchang /etc/nginx/sites-enabled/

# Nginx 설정 테스트
sudo nginx -t

# Nginx 재시작
sudo systemctl restart nginx
sudo systemctl enable nginx

# Let's Encrypt SSL 인증서 발급
echo -e "${YELLOW}SSL 인증서를 발급하시겠습니까? (y/n)${NC}"
echo "도메인이 이미 이 서버를 가리키고 있어야 합니다!"
read -p "선택: " setup_ssl

if [ "$setup_ssl" = "y" ]; then
    sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN
    sudo systemctl reload nginx
fi

# 완료 메시지
echo -e "${GREEN}======================================"
echo "배포가 완료되었습니다!"
echo "======================================${NC}"
echo ""
echo "다음 단계:"
echo "1. .env 파일의 환경변수가 올바르게 설정되었는지 확인"
echo "2. https://$DOMAIN 에서 사이트 접속 확인"
echo "3. Django 관리자 페이지 접속: https://$DOMAIN/admin"
echo ""
echo "유용한 명령어:"
echo "  - Gunicorn 상태 확인: sudo systemctl status gunicorn"
echo "  - Nginx 상태 확인: sudo systemctl status nginx"
echo "  - 로그 확인: sudo tail -f /var/log/gunicorn/error.log"
echo "  - Nginx 로그: sudo tail -f /var/log/nginx/techchang_error.log"
echo ""
