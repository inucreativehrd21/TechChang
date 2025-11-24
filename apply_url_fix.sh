#!/bin/bash

echo "=========================================="
echo "2048 게임 URL 패턴 순서 수정"
echo "URL Pattern Order Fix for 2048 Game"
echo "=========================================="
echo ""

PROJECT_DIR=~/projects/mysite
cd $PROJECT_DIR

# 색상 코드
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}문제: URL 패턴 순서 때문에 2048 게임이 404 에러${NC}"
echo "해결: pybo/urls.py에서 <int:question_id>/ 패턴을 맨 끝으로 이동"
echo ""

# 백업 생성
echo -e "${YELLOW}[1/5] 백업 생성 중...${NC}"
cp pybo/urls.py pybo/urls.py.backup.$(date +%Y%m%d_%H%M%S)
echo -e "${GREEN}✓${NC} 백업 완료: pybo/urls.py.backup.*"
echo ""

# urls.py 수정
echo -e "${YELLOW}[2/5] pybo/urls.py 수정 중...${NC}"

# Python 스크립트로 정확하게 수정
python << 'PYEOF'
import re

urls_file = 'pybo/urls.py'

with open(urls_file, 'r', encoding='utf-8') as f:
    content = f.read()

# <int:question_id>/ 패턴을 찾아서 제거
pattern_to_move = r"    path\('<int:question_id>/',\s*\n\s*base_views\.detail, name='detail'\),\n"

# 패턴이 이미 있는지 확인
if re.search(pattern_to_move, content):
    # 패턴 제거
    content_without_pattern = re.sub(pattern_to_move, '', content)

    # urlpatterns의 마지막에 추가 (닫는 괄호 앞에)
    # 먼저 마지막 ] 찾기
    last_bracket_pos = content_without_pattern.rfind(']')

    # 새로운 패턴 (주석 포함)
    new_pattern = '''
    # *** IMPORTANT: 이 패턴은 맨 마지막에 위치해야 합니다! ***
    # <int:question_id>/ 패턴이 숫자로 시작하는 다른 URL들(2048 등)을 가로채지 않도록
    # 모든 구체적인 URL 패턴을 먼저 정의한 후, 마지막에 이 일반적인 패턴을 배치합니다.
    path('<int:question_id>/', base_views.detail, name='detail'),
]'''

    # 내용 재구성
    new_content = content_without_pattern[:last_bracket_pos] + new_pattern

    # 파일 저장
    with open(urls_file, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print("✓ urls.py 수정 완료")
else:
    print("⚠ <int:question_id>/ 패턴을 찾을 수 없습니다. 이미 수정되었을 수 있습니다.")
PYEOF

echo ""

# Django 검증
echo -e "${YELLOW}[3/5] Django 설정 검증 중...${NC}"
python manage.py check

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Django 검증 실패!${NC}"
    echo "백업에서 복구하시겠습니까?"
    exit 1
fi

echo -e "${GREEN}✓${NC} Django 설정 정상"
echo ""

# URL 해석 테스트
echo -e "${YELLOW}[4/5] URL 해석 테스트 중...${NC}"

python manage.py shell << 'PYEOF'
from django.urls import resolve

try:
    # 2048 테스트
    r1 = resolve('/pybo/2048/')
    if r1.view_name == 'pybo:game2048_start':
        print("✓ /pybo/2048/ → game2048_start (정상)")
    else:
        print(f"✗ /pybo/2048/ → {r1.view_name} (오류!)")
        exit(1)

    # 일반 질문 테스트
    r2 = resolve('/pybo/1/')
    if r2.view_name == 'pybo:detail':
        print("✓ /pybo/1/ → detail (정상)")
    else:
        print(f"✗ /pybo/1/ → {r2.view_name} (오류!)")
        exit(1)

except Exception as e:
    print(f"✗ URL 해석 오류: {e}")
    exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ URL 테스트 실패!${NC}"
    exit 1
fi

echo ""

# 서비스 재시작
echo -e "${YELLOW}[5/5] 서비스 재시작 중...${NC}"

# 캐시 정리
find . -name "*.pyc" -delete 2>/dev/null
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# 서비스 재시작
sudo systemctl restart mysite.service
sleep 2
sudo systemctl restart nginx
sleep 2

echo -e "${GREEN}✓${NC} 서비스 재시작 완료"
echo ""

# 최종 HTTP 테스트
echo -e "${YELLOW}최종 HTTP 테스트...${NC}"
sleep 2

response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/pybo/2048/)

if [ "$response" -eq 200 ] || [ "$response" -eq 302 ]; then
    echo -e "${GREEN}✓${NC} HTTP $response - 2048 게임 접근 가능!"
else
    echo -e "${RED}✗${NC} HTTP $response - 여전히 문제가 있습니다."
    echo ""
    echo "로그 확인:"
    sudo journalctl -u mysite.service -n 20 --no-pager
    exit 1
fi

echo ""
echo -e "${GREEN}=========================================="
echo "✓✓✓ 수정 완료! ✓✓✓"
echo "==========================================${NC}"
echo ""
echo "브라우저에서 테스트하세요:"
echo "  http://your-server-ip/pybo/2048/"
echo ""
echo "백업 파일 위치:"
ls -lh pybo/urls.py.backup.* 2>/dev/null | tail -1
echo ""
echo "문제 원인: URL 패턴 순서"
echo "해결 방법: <int:question_id>/ 패턴을 맨 끝으로 이동"
echo ""
