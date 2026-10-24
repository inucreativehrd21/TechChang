"""로컬 익스트림 시제품 전용 DB예요. 운영 DB·SMTP를 사용하지 않아요."""
from .local import *

_PREVIEW_DATABASE = BASE_DIR / 'logs' / 'rookie-preview.sqlite3'
_PREVIEW_DATABASE.parent.mkdir(parents=True, exist_ok=True)
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': _PREVIEW_DATABASE}}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
ROOKIE_EXTREME_PREVIEW = os.environ.get('ROOKIE_EXTREME_PREVIEW', 'false').lower() == 'true'
