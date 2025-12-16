#!/bin/bash

# 마이그레이션 파일 수정 스크립트
# pybo → community 앱 rename 후 마이그레이션 문제 해결

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}마이그레이션 파일 수정 스크립트${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

PROJECT_DIR="/home/ubuntu/projects/mysite"
cd $PROJECT_DIR

echo -e "${YELLOW}Step 1: 마이그레이션 파일에서 pybo → community 참조 변경${NC}"
echo ""

# community/migrations/ 디렉토리의 모든 마이그레이션 파일 수정
MIGRATION_DIR="$PROJECT_DIR/community/migrations"

if [ ! -d "$MIGRATION_DIR" ]; then
    echo -e "${RED}❌ 마이그레이션 디렉토리를 찾을 수 없습니다: $MIGRATION_DIR${NC}"
    exit 1
fi

echo "마이그레이션 파일 수정 중..."
COUNT=0

# __init__.py 제외하고 모든 .py 파일 수정
for file in $MIGRATION_DIR/*.py; do
    if [ "$(basename $file)" != "__init__.py" ]; then
        MODIFIED=0

        # 1. dependencies에서 ('pybo', → ('community', 변경
        if grep -q "('pybo'," "$file" 2>/dev/null; then
            sed -i "s/('pybo',/('community',/g" "$file"
            MODIFIED=1
        fi

        # 2. lazy references에서 'pybo.xxx' → 'community.xxx' 변경
        if grep -q "'pybo\." "$file" 2>/dev/null; then
            sed -i "s/'pybo\./'community./g" "$file"
            MODIFIED=1
        fi

        # 3. swappable에서 "pybo.xxx" → "community.xxx" 변경
        if grep -q '"pybo\.' "$file" 2>/dev/null; then
            sed -i 's/"pybo\./"community./g' "$file"
            MODIFIED=1
        fi

        if [ $MODIFIED -eq 1 ]; then
            echo "  ✓ $(basename $file)"
            COUNT=$((COUNT + 1))
        fi
    fi
done

echo ""
echo -e "${GREEN}✓ $COUNT 개의 마이그레이션 파일 수정 완료${NC}"
echo ""

echo -e "${YELLOW}Step 2: django_migrations 테이블 업데이트${NC}"
echo ""

# SQLite에서 pybo → community로 앱 이름 변경
echo "데이터베이스 마이그레이션 히스토리 업데이트 중..."

sqlite3 "$PROJECT_DIR/db.sqlite3" <<EOF
UPDATE django_migrations SET app = 'community' WHERE app = 'pybo';
SELECT 'Updated ' || changes() || ' migration records';
EOF

echo ""
echo -e "${GREEN}✓ 데이터베이스 마이그레이션 히스토리 업데이트 완료${NC}"
echo ""

echo -e "${YELLOW}Step 3: 마이그레이션 상태 확인${NC}"
echo ""

source venv/bin/activate
python manage.py showmigrations community | head -30

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ 마이그레이션 수정 완료!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "이제 update_server.sh 스크립트를 계속 진행할 수 있습니다."
echo ""
