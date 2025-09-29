
from .base import *

# 프로덕션은 디버그 비활성화
DEBUG = False

ALLOWED_HOSTS = ['43.202.203.131', 'tc.o-r.kr']

# 정적 파일: 해시 기반 파일명으로 캐시 무효화(collectstatic 필요)
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# 프로덕션에서는 Nginx가 /static/ /media/를 서빙함. Django urlpatterns에 static() 추가 금지.
