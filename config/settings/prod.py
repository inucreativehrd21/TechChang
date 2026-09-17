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

# SECRET_KEY는 반드시 환경변수로 설정되어야 함 (보안)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise ValueError(
        "DJANGO_SECRET_KEY 환경변수가 설정되지 않았습니다. "
        "프로덕션 환경에서는 반드시 안전한 SECRET_KEY를 설정해야 합니다."
    )

# Admin URL 커스터마이징 (보안: 추측하기 어려운 경로)
# 환경변수로 설정 가능, 기본값: secret-control-panel/
ADMIN_URL = os.environ.get('DJANGO_ADMIN_URL', 'secret-control-panel/')

# 허용 호스트
# 환경변수로 설정 가능 (쉼표로 구분)
# 예: DJANGO_ALLOWED_HOSTS=techchang.com,www.techchang.com,your-ip
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if os.environ.get('DJANGO_ALLOWED_HOSTS') else [
    'techchang.com',
    'www.techchang.com',
    '161.118.232.178',  # 서버 IP 주소 (OCI)
]

# ===== 정적 파일 =====
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
# 주의: STATICFILES_STORAGE 는 Django 5.1 에서 제거된 설정이라 아래 줄은 무시된다(실제 활성 스토리지는
# base STORAGES 기본값 = StaticFilesStorage, 해시 없는 파일명). 라이브도 이 상태로 운영 중이므로 그대로 둔다.
# 해시 파일명(Manifest)으로 바꾸려면 STORAGES['staticfiles']['BACKEND'] 를 설정하고, collectstatic 실패 시
# 전 페이지 500 이 되는 점을 감안해 별도 작업으로 진행할 것.
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'  # (무효, 문서화용)

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
#  기본 True. 새 서버에서 인증서 적용 전에 IP 로 HTTP 검증할 때만
#  .env 에 DJANGO_SECURE_SSL_REDIRECT=false 를 두고, 검증이 끝나면 반드시 제거한다.
#  (세션/CSRF 쿠키는 Secure 고정이라 HTTP 로는 로그인이 안 된다 — 페이지 렌더/정적/미디어 확인 용도)
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', 'true').lower() == 'true'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Referrer 정책
SECURE_REFERRER_POLICY = 'same-origin'

# Content Security Policy (CSP)
# nonce 기반 CSP로 XSS 공격 방어 강화
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = (
    "'self'",
    # "'unsafe-inline'", 제거됨 - nonce로 대체
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
)
CSP_STYLE_SRC = (
    "'self'",
    # "'unsafe-inline'", 제거됨 - nonce로 대체
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

# nonce 포함 설정 (django-csp 3.8+)
CSP_INCLUDE_NONCE_IN = ['script-src', 'style-src']

# ===== 세션·CSRF 보안 =====
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
# CSRF 쿠키는 HttpOnly로 두면 안 된다.
# AJAX(fetch)에서 X-CSRFToken 헤더를 채우려면 JS가 csrftoken 쿠키를 읽어야 하는데,
# HttpOnly=True면 document.cookie로 못 읽어 헤더가 비고 → 403 → 인증 코드 발송 실패.
# Django 공식 권장값도 False다(CSRF는 교차도메인 방어용이라 HttpOnly의 실익이 없음).
CSRF_COOKIE_HTTPONLY = False
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
        'null': {
            'class': 'logging.NullHandler',
        },
        'file': {
            'level': 'INFO',
            # 크기 제한 회전: 대시보드 모니터가 이 파일을 읽어 로그/보안/실시간 로그를
            # 제공하므로(저널 권한 불필요) 무한 증가를 막아 읽기 비용·디스크를 관리한다.
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 1024 * 1024 * 5,  # 5MB
            'backupCount': 3,
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
        # 미등록 Host(스캐너·봇)로 인한 DisallowedHost는 실제 장애가 아니므로
        # 로그를 남기지 않아 모니터의 Error/Traceback 노이즈를 제거한다 (nginx 444로 1차 차단).
        'django.security.DisallowedHost': {
            'handlers': ['null'],
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
