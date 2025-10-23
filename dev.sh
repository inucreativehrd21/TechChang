#!/bin/bash

# Django mysite 개발 서버 실행 스크립트
# 사용법: ./dev.sh [command]

set -e

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_action() {
    echo -e "${BLUE}[ACTION]${NC} $1"
}

# 명령어 처리
COMMAND=${1:-run}

case $COMMAND in
    "setup")
        log_info "개발 환경 설정 중..."
        
        # 가상환경 생성 (Windows의 경우)
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
            if [[ ! -d "venv" ]]; then
                log_action "가상환경 생성 중..."
                python -m venv venv
            fi
            source venv/Scripts/activate
        else
            if [[ ! -d "venv" ]]; then
                log_action "가상환경 생성 중..."
                python3 -m venv venv
            fi
            source venv/bin/activate
        fi
        
        # 의존성 설치
        log_action "의존성 설치 중..."
        pip install --upgrade pip
        pip install -r requirements.txt
        
        # 환경 변수 설정
        if [[ ! -f ".env" ]]; then
            log_action ".env 파일 생성 중..."
            cp .env.example .env
            log_warn "⚠️ .env 파일을 수정하여 환경에 맞게 설정하세요."
        fi
        
        # 데이터베이스 마이그레이션
        log_action "데이터베이스 초기화 중..."
        python manage.py makemigrations
        python manage.py migrate
        
        # 카테고리 초기화
        log_action "기본 카테고리 생성 중..."
        python manage.py initialize_categories --force
        
        # 슈퍼유저 생성 (선택사항)
        log_warn "슈퍼유저를 생성하시겠습니까? (y/n)"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            python manage.py createsuperuser
        fi
        
        log_info "✅ 개발 환경 설정 완료!"
        ;;
        
    "run")
        log_info "Django 개발 서버 실행 중..."
        
        # 가상환경 활성화
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
            source venv/Scripts/activate 2>/dev/null || {
                log_warn "가상환경을 찾을 수 없습니다. './dev.sh setup'을 먼저 실행하세요."
                exit 1
            }
        else
            source venv/bin/activate 2>/dev/null || {
                log_warn "가상환경을 찾을 수 없습니다. './dev.sh setup'을 먼저 실행하세요."
                exit 1
            }
        fi
        
        # 마이그레이션 확인
        log_action "마이그레이션 확인 중..."
        python manage.py makemigrations --check --dry-run || {
            log_warn "새로운 마이그레이션을 적용합니다..."
            python manage.py makemigrations
            python manage.py migrate
        }
        
        # 정적 파일 수집 (개발용)
        python manage.py collectstatic --noinput --clear
        
        # 개발 서버 실행
    local access_url="${DEV_ACCESS_URL:-https://tc.o-r.kr}"
    log_info "🚀 개발 서버가 ${access_url} 에서 실행됩니다..."
        python manage.py runserver 0.0.0.0:8000
        ;;
        
    "test")
        log_info "테스트 실행 중..."
        
        # 가상환경 활성화
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
            source venv/Scripts/activate
        else
            source venv/bin/activate
        fi
        
        # 테스트 실행
        python manage.py test --verbosity=2
        ;;
        
    "shell")
        log_info "Django 쉘 실행 중..."
        
        # 가상환경 활성화
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
            source venv/Scripts/activate
        else
            source venv/bin/activate
        fi
        
        python manage.py shell
        ;;
        
    "clean")
        log_info "개발 환경 정리 중..."
        
        # 캐시 파일 삭제
        find . -name "*.pyc" -delete 2>/dev/null || true
        find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
        
        # 정적 파일 정리
        rm -rf staticfiles/ 2>/dev/null || true
        
        log_info "✅ 정리 완료!"
        ;;
        
    "help"|*)
        echo "Django mysite 개발 도구"
        echo ""
        echo "사용법: ./dev.sh [command]"
        echo ""
        echo "Commands:"
        echo "  setup    - 개발 환경 초기 설정"
        echo "  run      - 개발 서버 실행 (기본값)"
        echo "  test     - 테스트 실행"
        echo "  shell    - Django 쉘 실행"
        echo "  clean    - 캐시 파일 정리"
        echo "  help     - 도움말 출력"
        echo ""
        echo "예시:"
        echo "  ./dev.sh setup   # 최초 환경 설정"
        echo "  ./dev.sh         # 개발 서버 실행"
        echo "  ./dev.sh test    # 테스트 실행"
        ;;
esac