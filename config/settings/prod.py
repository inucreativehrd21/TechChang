from .base import *
import os

# dotenv 로드 (선택 사항)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ===== 보안 및 기본 설정 =====
DEBUG = False
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'temporary-secret-key-change-in-production')

# 허용 호스트
# 환경변수로 설정 가능 (쉼표로 구분)
# 예: DJANGO_ALLOWED_HOSTS=techchang.com,www.techchang.com,your-ip
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if os.environ.get('DJANGO_ALLOWED_HOSTS') else [
    'techchang.com',
    'www.techchang.com',
    '43.203.93.244',  # 서버 IP 주소
]

# ===== 정적 파일 =====
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# ===== 미디어 파일 =====
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ===== 보안 헤더 =====
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# HTTPS 리다이렉트
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Referrer 정책
SECURE_REFERRER_POLICY = 'same-origin'

# Content Security Policy (CSP)
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = (
    "'self'",
    "'unsafe-inline'",  # GSAP 및 인라인 스크립트용
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
)
CSP_STYLE_SRC = (
    "'self'",
    "'unsafe-inline'",  # Bootstrap 및 인라인 스타일용
    "cdn.jsdelivr.net",
    "fonts.googleapis.com",
)
CSP_FONT_SRC = (
    "'self'",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
)
CSP_IMG_SRC = ("'self'", "data:", "https:")
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)

# ===== 세션·CSRF 보안 =====
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# ===== 성능 최적화 =====
USE_ETAGS = True

# ===== 로깅 설정 =====
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
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

# ===== 이메일 설정 =====
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

if EMAIL_USE_SSL:
    EMAIL_USE_TLS = False

DEFAULT_FROM_EMAIL = os.environ.get(
    'DJANGO_DEFAULT_FROM_EMAIL',
    EMAIL_HOST_USER or 'noreply@techchang.com'
)
SERVER_EMAIL = os.environ.get(
    'DJANGO_SERVER_EMAIL',
    DEFAULT_FROM_EMAIL
)

ADMINS = [
    ('Admin', os.environ.get('DJANGO_ADMIN_EMAIL', DEFAULT_FROM_EMAIL)),
]
MANAGERS = ADMINS
