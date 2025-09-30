# config/settings/prod.py

from .base import *
import os

# Load environment variables if using python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 프로덕션 보안 설정
DEBUG = False
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', SECRET_KEY)

# 호스트 설정 (기존 IP 주소 유지)
ALLOWED_HOSTS = [
    '43.203.93.244',      # 기존 서버 IP (중요!)
    'tc.o-r.kr', 
    '127.0.0.1', 
    'localhost'
]

# 정적 파일 설정 (프로덕션 최적화)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
# ManifestStaticFilesStorage로 캐시 무효화 지원
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# 미디어 파일 설정
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# 보안 헤더 설정
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# 세션 보안
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# 성능 최적화
USE_ETAGS = True

# 로깅 설정 (기존 설정 유지)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# 이메일 설정 (환경 변수 기반) - 개선된 버전
EMAIL_BACKEND = os.environ.get(
    'DJANGO_EMAIL_BACKEND', 
    'django.core.mail.backends.smtp.EmailBackend'
)
EMAIL_HOST = os.environ.get('DJANGO_EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('DJANGO_EMAIL_PORT', 587))
EMAIL_HOST_USER = os.environ.get('DJANGO_EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('DJANGO_EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('DJANGO_EMAIL_USE_TLS', 'true').lower() == 'true'
EMAIL_USE_SSL = os.environ.get('DJANGO_EMAIL_USE_SSL', 'false').lower() == 'true'
EMAIL_TIMEOUT = int(os.environ.get('DJANGO_EMAIL_TIMEOUT', 30))

# SSL과 TLS 충돌 방지
if EMAIL_USE_SSL:
    EMAIL_USE_TLS = False

# 발신자 이메일 설정
DEFAULT_FROM_EMAIL = os.environ.get(
    'DJANGO_DEFAULT_FROM_EMAIL',
    EMAIL_HOST_USER or 'noreply@tc.o-r.kr'
)
SERVER_EMAIL = os.environ.get(
    'DJANGO_SERVER_EMAIL',
    DEFAULT_FROM_EMAIL
)

# 관리자 이메일 설정 (에러 리포트용)
ADMINS = [
    ('Admin', os.environ.get('DJANGO_ADMIN_EMAIL', DEFAULT_FROM_EMAIL)),
]
MANAGERS = ADMINS

# 프로덕션에서는 Nginx가 /static/ /media/를 서빙함
