#!/bin/bash

echo "=========================================="
echo "전체 게임 통합 검증 및 수정 스크립트"
echo "All Games Verification & Fix Script"
echo "=========================================="
echo ""

PROJECT_DIR=~/projects/mysite
cd $PROJECT_DIR

# 색상 코드
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 게임 목록
declare -A GAMES=(
    ["wordchain"]="끝말잇기"
    ["tictactoe"]="틱택토"
    ["baseball"]="숫자야구"
    ["guestbook"]="방명록"
    ["2048"]="2048 게임"
)

echo -e "${BLUE}=========================================="
echo "Step 1: 필수 파일 검증"
echo "==========================================${NC}"
echo ""

# pybo/views/__init__.py 검증 및 수정
echo -e "${YELLOW}[1-1] pybo/views/__init__.py 검증...${NC}"

if [ ! -f "pybo/views/__init__.py" ]; then
    echo -e "${RED}✗${NC} __init__.py 파일이 없습니다. 생성합니다..."

    cat > pybo/views/__init__.py << 'EOF'
"""
pybo views package
"""

from . import base_views
from . import question_views
from . import answer_views
from . import comment_views
from . import profile_views
from . import wordchain_views
from . import tictactoe_views
from . import baseball_views
from . import guestbook_views
from . import game2048_views

__all__ = [
    'base_views',
    'question_views',
    'answer_views',
    'comment_views',
    'profile_views',
    'wordchain_views',
    'tictactoe_views',
    'baseball_views',
    'guestbook_views',
    'game2048_views',
]
EOF
    echo -e "${GREEN}✓${NC} __init__.py 파일 생성 완료"
else
    echo -e "${GREEN}✓${NC} __init__.py 파일 존재"

    # 각 게임 뷰가 import되어 있는지 확인
    declare -a view_modules=("wordchain_views" "tictactoe_views" "baseball_views" "guestbook_views" "game2048_views")

    for module in "${view_modules[@]}"; do
        if grep -q "$module" pybo/views/__init__.py; then
            echo -e "   ${GREEN}✓${NC} $module import 확인"
        else
            echo -e "   ${YELLOW}⚠${NC}  $module import 누락 - 추가합니다..."

            # import 추가
            if ! grep -q "from . import $module" pybo/views/__init__.py; then
                sed -i "/from . import guestbook_views/a from . import $module" pybo/views/__init__.py
            fi

            # __all__ 에 추가
            if ! grep -q "'$module'," pybo/views/__init__.py; then
                sed -i "/'guestbook_views',/a \ \ \ \ '$module'," pybo/views/__init__.py
            fi
        fi
    done
fi

echo ""

# 각 게임 뷰 파일 검증
echo -e "${YELLOW}[1-2] 게임 뷰 파일 검증...${NC}"

declare -a required_view_files=(
    "pybo/views/wordchain_views.py"
    "pybo/views/tictactoe_views.py"
    "pybo/views/baseball_views.py"
    "pybo/views/guestbook_views.py"
    "pybo/views/game2048_views.py"
)

all_views_ok=true

for file in "${required_view_files[@]}"; do
    if [ -f "$file" ]; then
        size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null)
        echo -e "${GREEN}✓${NC} $file ($size bytes)"
    else
        echo -e "${RED}✗${NC} $file - 파일 없음!"
        all_views_ok=false
    fi
done

echo ""

if [ "$all_views_ok" = false ]; then
    echo -e "${RED}경고: 일부 뷰 파일이 누락되었습니다!${NC}"
    echo "Windows에서 Ubuntu로 파일을 동기화해야 합니다."
    echo ""
fi

# 템플릿 파일 검증
echo -e "${YELLOW}[1-3] 템플릿 파일 검증...${NC}"

declare -a required_templates=(
    "templates/pybo/wordchain_list.html"
    "templates/pybo/wordchain_detail.html"
    "templates/pybo/tictactoe_list.html"
    "templates/pybo/tictactoe_detail.html"
    "templates/pybo/baseball_play.html"
    "templates/pybo/guestbook_list.html"
    "templates/pybo/game2048_play.html"
)

all_templates_ok=true

for file in "${required_templates[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file"
    else
        echo -e "${RED}✗${NC} $file - 파일 없음!"
        all_templates_ok=false
    fi
done

echo ""

echo -e "${BLUE}=========================================="
echo "Step 2: Python Import 테스트"
echo "==========================================${NC}"
echo ""

python << 'PYEOF'
import sys
import os

sys.path.insert(0, os.getcwd())

view_modules = ['wordchain_views', 'tictactoe_views', 'baseball_views', 'guestbook_views', 'game2048_views']

all_ok = True

for module_name in view_modules:
    try:
        module = __import__(f'pybo.views.{module_name}', fromlist=[module_name])
        print(f"✓ {module_name} import 성공")
    except ImportError as e:
        print(f"✗ {module_name} import 실패: {e}")
        all_ok = False

if not all_ok:
    sys.exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}Import 테스트 실패!${NC}"
    echo "일부 모듈을 import할 수 없습니다."
    echo ""
else
    echo ""
    echo -e "${GREEN}✓ 모든 뷰 모듈 import 성공${NC}"
    echo ""
fi

echo -e "${BLUE}=========================================="
echo "Step 3: URL 패턴 검증"
echo "==========================================${NC}"
echo ""

python manage.py shell << 'PYEOF'
from django.urls import reverse
from django.core.exceptions import NoReverseMatch

url_patterns = {
    'wordchain_list': '끝말잇기 목록',
    'tictactoe_list': '틱택토 목록',
    'baseball_start': '숫자야구 시작',
    'guestbook_list': '방명록',
    'game2048_start': '2048 게임',
}

all_ok = True

for pattern, description in url_patterns.items():
    try:
        url = reverse(f'pybo:{pattern}')
        print(f"✓ {description}: {url}")
    except NoReverseMatch as e:
        print(f"✗ {description}: URL 패턴 없음")
        all_ok = False

if not all_ok:
    exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}URL 패턴 테스트 실패!${NC}"
    echo ""
else
    echo ""
    echo -e "${GREEN}✓ 모든 URL 패턴 정상${NC}"
    echo ""
fi

echo -e "${BLUE}=========================================="
echo "Step 4: 캐시 정리 및 정적 파일 수집"
echo "==========================================${NC}"
echo ""

echo -e "${YELLOW}Python 바이트코드 캐시 삭제...${NC}"
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
echo -e "${GREEN}✓${NC} 캐시 정리 완료"
echo ""

echo -e "${YELLOW}Django 체크 실행...${NC}"
python manage.py check

if [ $? -ne 0 ]; then
    echo -e "${RED}Django 체크 실패!${NC}"
    exit 1
fi

echo ""

echo -e "${YELLOW}정적 파일 수집...${NC}"
echo "yes" | python manage.py collectstatic > /dev/null 2>&1
echo -e "${GREEN}✓${NC} 정적 파일 수집 완료"
echo ""

echo -e "${BLUE}=========================================="
echo "Step 5: 서비스 재시작"
echo "==========================================${NC}"
echo ""

echo -e "${YELLOW}서비스 중지 중...${NC}"
sudo systemctl stop mysite.service
sleep 2
sudo systemctl stop nginx
sleep 2

echo -e "${YELLOW}남은 프로세스 정리...${NC}"
pkill -f gunicorn
pkill -f daphne
sleep 2

echo -e "${YELLOW}서비스 시작 중...${NC}"
sudo systemctl start mysite.service
sleep 3
sudo systemctl start nginx
sleep 2

echo -e "${GREEN}✓${NC} 서비스 재시작 완료"
echo ""

# 서비스 상태 확인
echo -e "${YELLOW}서비스 상태 확인:${NC}"
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

echo -e "${BLUE}=========================================="
echo "Step 6: 게임 접근성 테스트"
echo "==========================================${NC}"
echo ""

sleep 3

declare -A game_urls=(
    ["끝말잇기"]="/pybo/wordchain/"
    ["틱택토"]="/pybo/tictactoe/"
    ["숫자야구"]="/pybo/baseball/"
    ["방명록"]="/pybo/guestbook/"
    ["2048"]="/pybo/2048/"
)

all_games_ok=true

for game_name in "${!game_urls[@]}"; do
    url="${game_urls[$game_name]}"

    echo -e "${CYAN}테스트: $game_name ($url)${NC}"

    response=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost$url")

    if [ "$response" -eq 200 ] || [ "$response" -eq 302 ]; then
        echo -e "${GREEN}✓${NC} HTTP $response - 접근 가능"
    else
        echo -e "${RED}✗${NC} HTTP $response - 접근 불가"
        all_games_ok=false
    fi

    echo ""
done

echo -e "${BLUE}=========================================="
echo "검증 결과 요약"
echo "==========================================${NC}"
echo ""

if [ "$all_views_ok" = true ] && [ "$all_templates_ok" = true ] && [ "$all_games_ok" = true ]; then
    echo -e "${GREEN}██████████████████████████████████████${NC}"
    echo -e "${GREEN}✓ 모든 게임이 정상 작동합니다!${NC}"
    echo -e "${GREEN}██████████████████████████████████████${NC}"
    echo ""
    echo "게임 URL:"
    echo "  • 끝말잇기: http://your-server-ip/pybo/wordchain/"
    echo "  • 틱택토: http://your-server-ip/pybo/tictactoe/"
    echo "  • 숫자야구: http://your-server-ip/pybo/baseball/"
    echo "  • 방명록: http://your-server-ip/pybo/guestbook/"
    echo "  • 2048: http://your-server-ip/pybo/2048/"
else
    echo -e "${YELLOW}⚠ 일부 문제가 발견되었습니다.${NC}"
    echo ""

    if [ "$all_views_ok" = false ]; then
        echo -e "${RED}✗${NC} 뷰 파일 누락"
    fi

    if [ "$all_templates_ok" = false ]; then
        echo -e "${RED}✗${NC} 템플릿 파일 누락"
    fi

    if [ "$all_games_ok" = false ]; then
        echo -e "${RED}✗${NC} 일부 게임 접근 불가"
    fi

    echo ""
    echo "해결 방법:"
    echo "1. Windows에서 누락된 파일을 Ubuntu로 업로드"
    echo "2. 이 스크립트를 다시 실행"
    echo ""
    echo "로그 확인:"
    echo "  sudo journalctl -u mysite.service -n 50"
fi

echo ""
echo "=========================================="
