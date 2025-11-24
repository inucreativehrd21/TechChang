# Gunicorn 설정 파일
# 파일명: gunicorn.conf.py
# 사용법: gunicorn -c gunicorn.conf.py config.wsgi:application

import multiprocessing
import os
from pathlib import Path

# 기본 경로 계산
BASE_DIR = Path(__file__).resolve().parent

# 로그 디렉토리 설정 (환경 변수로 덮어쓰기 가능)
_log_dir_env = os.environ.get('GUNICORN_LOG_DIR', str(BASE_DIR / 'logs'))
LOG_DIR = Path(_log_dir_env)
if not LOG_DIR.is_absolute():
    LOG_DIR = BASE_DIR / LOG_DIR

try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    LOG_DIR = BASE_DIR / 'logs'
    LOG_DIR.mkdir(parents=True, exist_ok=True)

# 서버 소켓
bind = "127.0.0.1:8000"
backlog = 2048

# 워커 프로세스
workers = multiprocessing.cpu_count() * 2 + 1  # 권장 공식
worker_class = "sync"  # 동기 워커 (Django 기본)
worker_connections = 1000
max_requests = 1000  # 메모리 누수 방지
max_requests_jitter = 100  # 요청 수에 랜덤성 추가
timeout = 60  # 워커 타임아웃
keepalive = 5  # Keep-Alive 연결 유지 시간

# 프로세스 관리
preload_app = True  # 앱 사전 로드로 메모리 절약
reload = False  # 프로덕션에서는 비활성화
daemon = False  # systemd 사용시 False

# 로깅
loglevel = "info"
accesslog = str(LOG_DIR / "gunicorn_access.log")
errorlog = str(LOG_DIR / "gunicorn_error.log")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 프로세스 이름
proc_name = "mysite_gunicorn"

# 사용자/그룹 (프로덕션에서 설정)
# user = "www-data"
# group = "www-data"

# 임시 디렉토리
tmp_upload_dir = "/tmp"

# 보안
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8192

# 성능 최적화
enable_stdio_inheritance = True

def on_starting(server):
    """서버 시작시 실행"""
    server.log.info("Django mysite 서버가 시작됩니다...")

def on_reload(server):
    """리로드시 실행"""
    server.log.info("Django mysite 서버가 리로드됩니다...")

def worker_int(worker):
    """워커 인터럽트시 실행"""
    worker.log.info("워커가 중단됩니다: %s", worker.pid)