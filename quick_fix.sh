#!/bin/bash
#
# 원클릭 수정 스크립트 - Quick Fix Script
# 사용법: ./quick_fix.sh
#

clear

cat << "EOF"
╔════════════════════════════════════════════════════╗
║                                                    ║
║     Django 게임 사이트 원클릭 수정 스크립트        ║
║     Quick Fix Script for All Games                ║
║                                                    ║
╚════════════════════════════════════════════════════╝
EOF

echo ""
echo "이 스크립트는 다음 작업을 자동으로 수행합니다:"
echo "  1. pybo/views/__init__.py 생성/수정"
echo "  2. Python import 검증"
echo "  3. URL 패턴 검증"
echo "  4. 캐시 정리"
echo "  5. 정적 파일 수집"
echo "  6. 서비스 재시작"
echo "  7. 모든 게임 접근성 테스트"
echo ""

read -p "계속하시겠습니까? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "취소되었습니다."
    exit 0
fi

echo ""
echo "시작합니다..."
echo ""

PROJECT_DIR=~/projects/mysite
cd $PROJECT_DIR || exit 1

# pybo/views/__init__.py 강제 생성
echo "[1/7] pybo/views/__init__.py 생성 중..."

cat > pybo/views/__init__.py << 'INITEOF'
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
INITEOF

echo "   ✓ 완료"

# Import 검증
echo "[2/7] Python import 검증 중..."

if python -c "from pybo.views import game2048_views" 2>/dev/null; then
    echo "   ✓ 완료"
else
    echo "   ✗ 실패 - game2048_views.py 파일이 없습니다!"
    echo "   Windows에서 해당 파일을 업로드해야 합니다."
fi

# URL 검증
echo "[3/7] URL 패턴 검증 중..."

if python manage.py shell -c "from django.urls import reverse; reverse('pybo:game2048_start')" 2>/dev/null >/dev/null; then
    echo "   ✓ 완료"
else
    echo "   ✗ 실패 - URL 패턴에 문제가 있습니다."
fi

# 캐시 정리
echo "[4/7] 캐시 정리 중..."

find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

echo "   ✓ 완료"

# 정적 파일 수집
echo "[5/7] 정적 파일 수집 중..."

echo "yes" | python manage.py collectstatic > /dev/null 2>&1

echo "   ✓ 완료"

# 서비스 재시작
echo "[6/7] 서비스 재시작 중..."

sudo systemctl stop mysite.service 2>/dev/null
sudo systemctl stop nginx 2>/dev/null
sleep 2

pkill -f gunicorn 2>/dev/null
pkill -f daphne 2>/dev/null
sleep 1

sudo systemctl start mysite.service
sleep 3
sudo systemctl start nginx
sleep 2

echo "   ✓ 완료"

# 게임 테스트
echo "[7/7] 게임 접근성 테스트 중..."
echo ""

sleep 2

declare -A games=(
    ["끝말잇기"]="/pybo/wordchain/"
    ["틱택토"]="/pybo/tictactoe/"
    ["숫자야구"]="/pybo/baseball/"
    ["방명록"]="/pybo/guestbook/"
    ["2048"]="/pybo/2048/"
)

success_count=0
fail_count=0

for game in "${!games[@]}"; do
    url="${games[$game]}"
    response=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost$url")

    if [ "$response" -eq 200 ] || [ "$response" -eq 302 ]; then
        echo "   ✓ $game: OK (HTTP $response)"
        ((success_count++))
    else
        echo "   ✗ $game: FAIL (HTTP $response)"
        ((fail_count++))
    fi
done

echo ""
echo "══════════════════════════════════════════════════"
echo "결과 요약"
echo "══════════════════════════════════════════════════"
echo "  성공: $success_count개 게임"
echo "  실패: $fail_count개 게임"
echo ""

if [ $fail_count -eq 0 ]; then
    echo "🎉 모든 게임이 정상 작동합니다!"
    echo ""
    echo "브라우저에서 접속해보세요:"
    echo "  http://your-server-ip/pybo/wordchain/"
    echo "  http://your-server-ip/pybo/tictactoe/"
    echo "  http://your-server-ip/pybo/baseball/"
    echo "  http://your-server-ip/pybo/guestbook/"
    echo "  http://your-server-ip/pybo/2048/"
else
    echo "⚠ 일부 게임에 문제가 있습니다."
    echo ""
    echo "로그 확인:"
    echo "  sudo journalctl -u mysite.service -n 50"
    echo ""
    echo "누락된 파일이 있다면 Windows에서 업로드 후 다시 실행하세요."
fi

echo "══════════════════════════════════════════════════"
