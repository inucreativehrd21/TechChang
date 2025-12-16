#!/bin/bash

# TechChang 서버 자동 업데이트 스크립트
# 서버: 43.203.93.244 (techchang.com)
# 백업 → 교체 → 복원 → 재시작을 한 번에 수행

set -e  # 에러 발생 시 중단

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 설정
PROJECT_DIR="/home/ubuntu/projects/mysite"
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$HOME/backups/$BACKUP_DATE"
TEMP_DIR="$HOME/temp_update"

# 진행률 표시
TOTAL_STEPS=13
CURRENT_STEP=0

show_step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}[$CURRENT_STEP/$TOTAL_STEPS] $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# 서비스 이름 자동 감지
detect_service_name() {
    if systemctl list-units --type=service --all | grep -q "mysite.service"; then
        echo "mysite"
    elif systemctl list-units --type=service --all | grep -q "gunicorn.service"; then
        echo "gunicorn"
    else
        echo "gunicorn"  # 기본값
    fi
}

SERVICE_NAME=$(detect_service_name)

# 에러 핸들러
error_exit() {
    echo -e "${RED}❌ 오류 발생: $1${NC}" >&2
    echo -e "${YELLOW}롤백을 진행하시겠습니까? (y/n)${NC}"
    read -p "선택: " rollback_choice
    if [ "$rollback_choice" = "y" ]; then
        rollback
    fi
    exit 1
}

# 롤백 함수
rollback() {
    echo -e "${YELLOW}🔄 롤백 시작...${NC}"

    # 서비스 중지
    sudo systemctl stop $SERVICE_NAME 2>/dev/null || true

    # 기존 코드로 복원
    if [ -d "$PROJECT_DIR"_old ]; then
        echo "기존 코드로 복원 중..."
        sudo rm -rf $PROJECT_DIR
        sudo mv ${PROJECT_DIR}_old $PROJECT_DIR
    fi

    # 서비스 재시작
    sudo systemctl start $SERVICE_NAME
    sudo systemctl restart nginx

    echo -e "${GREEN}✅ 롤백 완료${NC}"
    echo "서비스 상태:"
    sudo systemctl status $SERVICE_NAME --no-pager -l
}

# 배너
clear
echo -e "${BLUE}"
cat << "EOF"
╔════════════════════════════════════════╗
║   TechChang 서버 자동 업데이트 v2.0   ║
║        techchang.com (43.203.93.244)   ║
╚════════════════════════════════════════╝
EOF
echo -e "${NC}"

# 확인
echo -e "${YELLOW}⚠️  주의사항:${NC}"
echo "  - 서비스가 약 5-10분간 중단됩니다"
echo "  - 자동으로 백업이 생성됩니다"
echo "  - 문제 발생 시 즉시 롤백됩니다"
echo ""
echo -e "${YELLOW}계속하시겠습니까? (y/n)${NC}"
read -p "선택: " confirm

if [ "$confirm" != "y" ]; then
    echo "업데이트가 취소되었습니다."
    exit 0
fi

# ============================================
# Step 1: 사전 확인
# ============================================
show_step "사전 확인"

if [ ! -d "$PROJECT_DIR" ]; then
    error_exit "프로젝트 디렉토리를 찾을 수 없습니다: $PROJECT_DIR"
fi

echo "✓ 프로젝트 디렉토리 확인: $PROJECT_DIR"

# 업데이트 파일 위치 확인
echo ""
echo -e "${YELLOW}업데이트 방법을 선택하세요:${NC}"
echo "  1) Git Pull (추천)"
echo "  2) 업로드된 파일 사용 (~/temp_update/mysite_new)"
read -p "선택 (1 또는 2): " update_method

# ============================================
# Step 2: 백업
# ============================================
show_step "전체 백업 생성"

mkdir -p $BACKUP_DIR
echo "백업 위치: $BACKUP_DIR"

# 전체 프로젝트 백업
echo "프로젝트 전체 백업 중..."
sudo cp -r $PROJECT_DIR $BACKUP_DIR/mysite_backup
echo "✓ 프로젝트 백업 완료"

# 데이터베이스 백업
echo "데이터베이스 백업 중..."
cp $PROJECT_DIR/db.sqlite3 $BACKUP_DIR/db_backup.sqlite3
echo "✓ DB 백업 완료: $(du -h $BACKUP_DIR/db_backup.sqlite3 | cut -f1)"

# 미디어 파일 백업
if [ -d "$PROJECT_DIR/media" ]; then
    echo "미디어 파일 백업 중..."
    tar -czf $BACKUP_DIR/media_backup.tar.gz -C $PROJECT_DIR media/
    echo "✓ 미디어 백업 완료: $(du -h $BACKUP_DIR/media_backup.tar.gz | cut -f1)"
fi

# .env 백업
cp $PROJECT_DIR/.env $BACKUP_DIR/env_backup
echo "✓ 환경변수 백업 완료"

# Nginx 설정 백업
sudo cp /etc/nginx/sites-enabled/* $BACKUP_DIR/ 2>/dev/null || true
echo "✓ Nginx 설정 백업 완료"

echo ""
echo -e "${GREEN}✅ 백업 완료!${NC}"
echo "백업 위치: $BACKUP_DIR"
ls -lh $BACKUP_DIR

# ============================================
# Step 3: 서비스 중지
# ============================================
show_step "서비스 중지"

echo "Django 서비스($SERVICE_NAME) 중지 중..."
sudo systemctl stop $SERVICE_NAME
sleep 2

if sudo systemctl is-active --quiet $SERVICE_NAME; then
    error_exit "서비스 중지 실패"
fi
echo "✓ 서비스 중지 완료"

# ============================================
# Step 4: 코드 준비
# ============================================
show_step "새 코드 준비"

if [ "$update_method" = "1" ]; then
    # Git Pull 방식
    echo "Git에서 최신 코드 가져오는 중..."
    cd $PROJECT_DIR

    # Git 상태 확인
    if [ ! -d ".git" ]; then
        error_exit "Git 저장소가 아닙니다. Git을 초기화하거나 방법 2를 선택하세요."
    fi

    # 변경사항 확인
    if ! git diff-index --quiet HEAD --; then
        echo -e "${YELLOW}⚠️ 로컬 변경사항이 있습니다.${NC}"
        git status --short
        echo ""
        read -p "변경사항을 무시하고 계속하시겠습니까? (y/n): " ignore_changes
        if [ "$ignore_changes" = "y" ]; then
            git reset --hard HEAD
        else
            error_exit "업데이트 취소됨"
        fi
    fi

    # Git pull
    git pull || error_exit "Git pull 실패"
    echo "✓ Git에서 최신 코드 다운로드 완료"

    NEW_CODE_DIR=$PROJECT_DIR

elif [ "$update_method" = "2" ]; then
    # 업로드된 파일 사용
    if [ ! -d "$TEMP_DIR/mysite_new" ]; then
        error_exit "업로드된 파일을 찾을 수 없습니다: $TEMP_DIR/mysite_new"
    fi

    echo "✓ 업로드된 파일 확인: $TEMP_DIR/mysite_new"
    NEW_CODE_DIR="$TEMP_DIR/mysite_new"

else
    error_exit "잘못된 선택입니다"
fi

# ============================================
# Step 5: 코드 교체 (방법 2만 해당)
# ============================================
if [ "$update_method" = "2" ]; then
    show_step "코드 교체"

    cd /home/ubuntu/projects

    # 기존 코드를 _old로 이름 변경
    echo "기존 코드를 mysite_old로 백업 중..."
    sudo mv mysite mysite_old

    # 새 코드를 mysite로 이동
    echo "새 코드를 mysite로 이동 중..."
    sudo mv $TEMP_DIR/mysite_new mysite

    # 소유권 설정
    sudo chown -R ubuntu:www-data mysite

    echo "✓ 코드 교체 완료"
fi

# ============================================
# Step 6: 데이터 복원
# ============================================
show_step "데이터 및 설정 복원"

cd $PROJECT_DIR

if [ "$update_method" = "2" ]; then
    # 데이터베이스 복원
    echo "데이터베이스 복원 중..."
    sudo cp $BACKUP_DIR/db_backup.sqlite3 ./db.sqlite3

    # 미디어 파일 복원
    echo "미디어 파일 복원 중..."
    if [ -f "$BACKUP_DIR/media_backup.tar.gz" ]; then
        tar -xzf $BACKUP_DIR/media_backup.tar.gz
    fi

    # .env 파일 복원
    echo ".env 파일 복원 중..."
    sudo cp $BACKUP_DIR/env_backup ./.env
fi

# 도메인 설정 업데이트
echo "도메인 설정 업데이트 중..."
sed -i 's/tc\.o-r\.kr/techchang.com/g' .env
sed -i 's/www\.tc\.o-r\.kr/www.techchang.com/g' .env

# 권한 설정
echo "권한 설정 중..."
sudo chown ubuntu:www-data db.sqlite3
sudo chmod 664 db.sqlite3
sudo chown -R ubuntu:www-data media/
sudo chmod -R 755 media/

echo "✓ 데이터 복원 완료"

# ============================================
# Step 7: 가상환경 및 패키지
# ============================================
show_step "가상환경 및 패키지 업데이트"

# 가상환경 확인
if [ ! -d "venv" ]; then
    if [ -d "/home/ubuntu/projects/mysite_old/venv" ]; then
        echo "기존 가상환경 복사 중..."
        cp -r /home/ubuntu/projects/mysite_old/venv ./
    else
        echo "새 가상환경 생성 중..."
        python3 -m venv venv
    fi
fi

# 가상환경 활성화
source venv/bin/activate

# 패키지 업데이트
echo "Python 패키지 업데이트 중..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "✓ 패키지 업데이트 완료"

# ============================================
# Step 8: 마이그레이션 파일 수정 (pybo → community)
# ============================================
show_step "마이그레이션 참조 수정"

echo "마이그레이션 파일에서 pybo 참조를 community로 변경 중..."

# community/migrations/ 디렉토리의 모든 마이그레이션 파일 수정
MIGRATION_DIR="$PROJECT_DIR/community/migrations"
if [ -d "$MIGRATION_DIR" ]; then
    COUNT=0
    for file in $MIGRATION_DIR/*.py; do
        if [ "$(basename $file)" != "__init__.py" ]; then
            if grep -q "('pybo'," "$file" 2>/dev/null; then
                sed -i "s/('pybo',/('community',/g" "$file"
                COUNT=$((COUNT + 1))
            fi
        fi
    done
    echo "✓ $COUNT 개의 마이그레이션 파일 수정 완료"
else
    echo "⚠️ 마이그레이션 디렉토리를 찾을 수 없습니다"
fi

# django_migrations 테이블 업데이트
echo "데이터베이스 마이그레이션 히스토리 업데이트 중..."
if [ -f "$PROJECT_DIR/db.sqlite3" ]; then
    sqlite3 "$PROJECT_DIR/db.sqlite3" "UPDATE django_migrations SET app = 'community' WHERE app = 'pybo';" 2>/dev/null || true
    echo "✓ 데이터베이스 마이그레이션 히스토리 업데이트 완료"
fi

# ============================================
# Step 9: 정적 파일 수집
# ============================================
show_step "정적 파일 수집"

python manage.py collectstatic --noinput
echo "✓ 정적 파일 수집 완료"

# ============================================
# Step 10: 마이그레이션 확인
# ============================================
show_step "마이그레이션 확인"

echo "마이그레이션 상태 확인 중..."
python manage.py showmigrations | head -20

echo ""
echo -e "${YELLOW}새로운 마이그레이션이 있습니까? (y/n)${NC}"
read -p "선택: " has_migration

if [ "$has_migration" = "y" ]; then
    echo -e "${RED}⚠️ 경고: 새로운 마이그레이션이 감지되었습니다!${NC}"
    echo "db_table 설정이 올바른지 확인하세요."
    echo ""
    echo "마이그레이션을 적용하시겠습니까? (y/n)"
    read -p "선택: " apply_migration

    if [ "$apply_migration" = "y" ]; then
        python manage.py migrate
    else
        echo "마이그레이션을 건너뜁니다."
    fi
else
    echo "✓ 마이그레이션 변경사항 없음"
fi

# 데이터 확인
echo ""
echo "데이터 무결성 확인 중..."
python manage.py shell << 'PYEOF'
from django.contrib.auth.models import User
from community.models import Question, Answer, Comment

print(f"✓ 사용자 수: {User.objects.count()}")
print(f"✓ 게시글 수: {Question.objects.count()}")
print(f"✓ 답변 수: {Answer.objects.count()}")
print(f"✓ 댓글 수: {Comment.objects.count()}")

# 테이블 이름 확인
print(f"\n테이블 이름 확인:")
print(f"  Question: {Question._meta.db_table}")
print(f"  Answer: {Answer._meta.db_table}")
PYEOF

# ============================================
# Step 10: Nginx 설정 업데이트
# ============================================
show_step "Nginx 설정 업데이트"

# Nginx 설정 파일 복사
echo "Nginx 설정 업데이트 중..."
sudo cp nginx.conf /etc/nginx/sites-available/techchang

# 기본 사이트 비활성화
sudo rm -f /etc/nginx/sites-enabled/default
sudo rm -f /etc/nginx/sites-enabled/mysite

# TechChang 사이트 활성화
sudo ln -sf /etc/nginx/sites-available/techchang /etc/nginx/sites-enabled/

# Nginx 설정 테스트
echo "Nginx 설정 테스트 중..."
if ! sudo nginx -t; then
    error_exit "Nginx 설정 오류"
fi

echo "✓ Nginx 설정 업데이트 완료"

# ============================================
# Step 12: Django 서비스 설정 확인
# ============================================
show_step "Django 서비스($SERVICE_NAME) 설정 확인"

# 서비스 파일 확인
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ -f "$SERVICE_FILE" ]; then
    echo "✓ 서비스 파일 존재: $SERVICE_FILE"

    # WorkingDirectory 확인
    if grep -q "WorkingDirectory=$PROJECT_DIR" $SERVICE_FILE; then
        echo "✓ WorkingDirectory 설정 올바름"
    else
        echo -e "${YELLOW}⚠️ 서비스 파일의 WorkingDirectory를 확인하세요${NC}"
    fi
else
    echo -e "${YELLOW}⚠️ 서비스 파일이 없습니다: $SERVICE_FILE${NC}"
fi

# ============================================
# Step 13: 서비스 재시작
# ============================================
show_step "서비스 재시작"

# systemd 재로드
sudo systemctl daemon-reload

# Django 서비스 시작
echo "Django 서비스($SERVICE_NAME) 시작 중..."
sudo systemctl start $SERVICE_NAME
sudo systemctl enable $SERVICE_NAME
sleep 3

# Nginx 재시작
echo "Nginx 재시작 중..."
sudo systemctl restart nginx

echo "✓ 서비스 재시작 완료"

# ============================================
# 검증
# ============================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}검증 단계${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# 서비스 상태 확인
echo ""
echo "=== Django 서비스($SERVICE_NAME) 상태 ==="
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    echo -e "${GREEN}✓ Django 서비스 실행 중${NC}"
else
    echo -e "${RED}✗ Django 서비스 실행 안됨${NC}"
    sudo systemctl status $SERVICE_NAME --no-pager -l | tail -20
    error_exit "Django 서비스가 실행되지 않았습니다"
fi

echo ""
echo "=== Nginx 상태 ==="
if sudo systemctl is-active --quiet nginx; then
    echo -e "${GREEN}✓ Nginx 실행 중${NC}"
else
    echo -e "${RED}✗ Nginx 실행 안됨${NC}"
    error_exit "Nginx가 실행되지 않았습니다"
fi

# 포트 확인
echo ""
echo "=== 포트 확인 ==="
if sudo netstat -tulpn | grep -q ":8000"; then
    echo -e "${GREEN}✓ 포트 8000 사용 중 (Django)${NC}"
else
    echo -e "${RED}✗ 포트 8000 사용 안됨${NC}"
fi

# HTTP 응답 테스트
echo ""
echo "=== HTTP 응답 테스트 ==="
if curl -s -o /dev/null -w "%{http_code}" http://localhost | grep -q "200\|301\|302"; then
    echo -e "${GREEN}✓ HTTP 응답 정상${NC}"
else
    echo -e "${YELLOW}⚠️ HTTP 응답 확인 필요${NC}"
fi

# 완료 메시지
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}🎉 업데이트 완료!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "백업 위치: $BACKUP_DIR"
echo ""
echo "다음 단계:"
echo "  1. 웹사이트 접속: https://techchang.com"
echo "  2. 모든 기능 테스트 (로그인, 게시글, 게임 등)"
echo "  3. 24-48시간 모니터링"
echo ""
echo "문제 발생 시 롤백:"
echo "  cd /home/ubuntu/projects"
echo "  sudo systemctl stop $SERVICE_NAME"
echo "  sudo rm -rf mysite"
echo "  sudo mv mysite_old mysite"
echo "  sudo systemctl start $SERVICE_NAME"
echo ""
echo "로그 확인:"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo "  sudo tail -f /var/log/nginx/techchang_error.log"
echo ""

# 정리 여부 확인
echo -e "${YELLOW}업데이트가 정상적으로 완료되었습니다.${NC}"
echo "백업 파일(mysite_old)을 지금 삭제하시겠습니까?"
echo -e "${RED}※ 24-48시간 후 삭제를 권장합니다${NC}"
read -p "지금 삭제? (y/n): " cleanup

if [ "$cleanup" = "y" ]; then
    if [ -d "/home/ubuntu/projects/mysite_old" ]; then
        sudo rm -rf /home/ubuntu/projects/mysite_old
        echo "✓ mysite_old 삭제 완료"
    fi

    if [ -d "$TEMP_DIR" ]; then
        rm -rf $TEMP_DIR
        echo "✓ 임시 디렉토리 삭제 완료"
    fi

    echo -e "${GREEN}정리 완료!${NC}"
else
    echo "백업 유지됨: /home/ubuntu/projects/mysite_old"
    echo "나중에 삭제하려면: sudo rm -rf /home/ubuntu/projects/mysite_old"
fi

echo ""
echo -e "${GREEN}✨ 모든 작업이 완료되었습니다! ✨${NC}"
