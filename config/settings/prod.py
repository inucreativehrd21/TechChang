
from .base import *

# 프로덕션은 디버그 비활성화
DEBUG = False

ALLOWED_HOSTS = ['43.202.203.131', 'tc.o-r.kr']

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# 프로덕션에서는 Nginx가 /static/ /media/를 서빙함. Django urlpatterns에 static() 추가 금지.
