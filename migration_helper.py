# Django 모델 마이그레이션 강제 생성 스크립트
# 
# 사용법: python manage.py migrate --fake pybo 0001
# 그 다음: python manage.py makemigrations pybo --empty
# 마지막: 생성된 빈 마이그레이션 파일을 수정

"""
만약 필드가 이미 데이터베이스에 존재하는 경우:
1. 마이그레이션 파일을 수동으로 생성
2. 또는 --fake 옵션으로 기존 상태를 인정
3. 이후 새로운 변경사항만 마이그레이션 적용
"""

# 임시 해결책으로 사용할 수 있는 명령어들:
# python manage.py showmigrations pybo
# python manage.py sqlmigrate pybo 0001
# python manage.py migrate pybo --fake-initial