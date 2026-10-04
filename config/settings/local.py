
from .base import *

ALLOWED_HOSTS = []

DEBUG = True
# 로컬은 커밋 없이 CSS 를 고치므로 서버 기동 시각으로 캐시 무효화
import time as _time
STATIC_VERSION = str(int(_time.time()))
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'