#!/bin/bash

# 새 서버 데이터 복원 스크립트
# 사용법: ./restore_data.sh

set -e

echo "======================================"
echo "TechChang 데이터 복원 시작"
echo "======================================"

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 설정
PROJECT_DIR="/home/ubuntu/projects/mysite"
cd $PROJECT_DIR

# 1. 백업 파일 확인
echo -e "${GREEN}[1/6] 백업 파일 확인 중...${NC}"

DB_FILE=$(ls -t db_*.sqlite3 2>/dev/null | head -1)
MEDIA_FILE=$(ls -t media_*.tar.gz 2>/dev/null | head -1)

if [ -z "$DB_FILE" ]; then
    echo -e "${RED}⚠ 오류: 데이터베이스 백업 파일을 찾을 수 없습니다!${NC}"
    echo "파일을 먼저 업로드하세요:"
    echo "  scp -i your-key.pem db_*.sqlite3 ubuntu@$(curl -s ifconfig.me):$PROJECT_DIR/"
    exit 1
fi

if [ -z "$MEDIA_FILE" ]; then
    echo -e "${YELLOW}⚠ 경고: 미디어 백업 파일을 찾을 수 없습니다.${NC}"
    read -p "계속하시겠습니까? (y/n): " CONTINUE
    if [ "$CONTINUE" != "y" ]; then
        exit 1
    fi
fi

echo "✓ 발견된 데이터베이스 백업: $DB_FILE"
if [ -n "$MEDIA_FILE" ]; then
    echo "✓ 발견된 미디어 백업: $MEDIA_FILE"
fi

# 2. .env 파일 확인
echo -e "${GREEN}[2/6] 환경변수 파일 확인 중...${NC}"

if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠ .env 파일이 없습니다.${NC}"

    if [ -f ".env_backup" ]; then
        echo "백업된 .env_backup을 복원합니다..."
        cp .env_backup .env
    elif [ -f ".env.example" ]; then
        echo ".env.example을 복사합니다..."
        cp .env.example .env
        echo -e "${RED}⚠ 중요: .env 파일을 수정해야 합니다!${NC}"
        read -p "지금 편집하시겠습니까? (y/n): " EDIT_ENV
        if [ "$EDIT_ENV" = "y" ]; then
            nano .env
        fi
    else
        echo -e "${RED}⚠ 오류: .env 파일이 필요합니다!${NC}"
        exit 1
    fi
fi

# 도메인 업데이트
echo "도메인 설정 업데이트 중..."
sed -i 's/tc\.o-r\.kr/techchang.com/g' .env
sed -i 's/www\.tc\.o-r\.kr/www.techchang.com/g' .env
echo "✓ .env 파일 준비 완료"

# 3. 서비스 중지
echo -e "${GREEN}[3/6] 서비스 중지 중...${NC}"
sudo systemctl stop gunicorn 2>/dev/null || echo "Gunicorn이 아직 설정되지 않았습니다."

# 4. 데이터베이스 복원
echo -e "${GREEN}[4/6] 데이터베이스 복원 중...${NC}"

# 기존 db.sqlite3 백업 (있다면)
if [ -f "db.sqlite3" ]; then
    echo "기존 db.sqlite3를 db.sqlite3.old로 백업합니다..."
    mv db.sqlite3 db.sqlite3.old
fi

# 백업 데이터베이스 복원
echo "백업 데이터베이스를 복원합니다: $DB_FILE → db.sqlite3"
cp $DB_FILE db.sqlite3

# 권한 설정
chmod 664 db.sqlite3
chown ubuntu:www-data db.sqlite3 2>/dev/null || chown ubuntu:ubuntu db.sqlite3

echo "✓ 데이터베이스 복원 완료"
ls -lh db.sqlite3

# 5. 미디어 파일 복원
echo -e "${GREEN}[5/6] 미디어 파일 복원 중...${NC}"

if [ -n "$MEDIA_FILE" ]; then
    # 기존 media 디렉토리 백업
    if [ -d "media" ]; then
        echo "기존 media 디렉토리를 media_old로 백업합니다..."
        mv media media_old
    fi

    # 미디어 파일 압축 해제
    echo "미디어 파일 압축 해제 중: $MEDIA_FILE"
    tar -xzf $MEDIA_FILE

    # 권한 설정
    chown -R ubuntu:www-data media/ 2>/dev/null || chown -R ubuntu:ubuntu media/
    chmod -R 755 media/

    echo "✓ 미디어 파일 복원 완료"
    du -sh media/
else
    echo "⚠ 미디어 파일 복원 스킵"
fi

# 6. 마이그레이션 및 서비스 재시작
echo -e "${GREEN}[6/6] 마이그레이션 및 서비스 시작 중...${NC}"

# 가상환경 활성화
if [ -d "venv" ]; then
    source venv/bin/activate

    # 마이그레이션 상태 확인
    echo "마이그레이션 상태 확인 중..."
    python manage.py showmigrations

    # 마이그레이션 적용 (필요시)
    read -p "마이그레이션을 적용하시겠습니까? (y/n): " RUN_MIGRATE
    if [ "$RUN_MIGRATE" = "y" ]; then
        python manage.py migrate
    fi

    # 정적 파일 수집
    echo "정적 파일 수집 중..."
    python manage.py collectstatic --noinput

    deactivate
else
    echo -e "${YELLOW}⚠ 가상환경이 없습니다. 수동으로 마이그레이션을 실행하세요.${NC}"
fi

# Gunicorn 시작
echo "Gunicorn 시작 중..."
sudo systemctl start gunicorn
sudo systemctl enable gunicorn

# Nginx 재시작
echo "Nginx 재시작 중..."
sudo systemctl restart nginx

# 완료
echo ""
echo "======================================"
echo "데이터 복원 완료!"
echo "======================================"
echo ""
echo "복원된 내용:"
echo "  - 데이터베이스: $DB_FILE"
if [ -n "$MEDIA_FILE" ]; then
    echo "  - 미디어 파일: $MEDIA_FILE"
fi
echo ""
echo "서비스 상태 확인:"
sudo systemctl status gunicorn --no-pager -l
echo ""
echo "다음 단계:"
echo "1. 데이터 확인:"
echo "   source venv/bin/activate"
echo "   python manage.py shell"
echo ""
echo "2. 웹사이트 테스트:"
echo "   http://$(curl -s ifconfig.me)"
echo ""
echo "3. 로그 확인:"
echo "   sudo tail -f /var/log/gunicorn/error.log"
echo ""
