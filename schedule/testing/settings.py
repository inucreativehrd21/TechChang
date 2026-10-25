from pathlib import Path

HERE = Path(__file__).resolve().parent

SECRET_KEY = 'schedule-standalone-tests'
DEBUG = False
ALLOWED_HOSTS = ['testserver']

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'schedule.apps.ScheduleConfig',
]
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
ROOT_URLCONF = 'schedule.testing.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [HERE / 'templates'],           # 호스트 사이트의 base.html / base_mobile.html 대역
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
TIME_ZONE = 'Asia/Seoul'
LANGUAGE_CODE = 'ko-kr'
STATIC_URL = '/static/'
LOGIN_URL = '/login/'
SCHEDULE = {'FIRST_WEEKDAY': 6, 'FEED_PROVIDERS': []}
