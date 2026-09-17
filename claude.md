# TechChang Community Platform

## WHAT (기술 스택)

**Backend**: Django 5.2.6, Python 3.12+, MySQL 8 (운영, `DJANGO_DB_ENGINE=mysql`) / SQLite3 (로컬·CI)
**Frontend**: Bootstrap 5.3, Vanilla JavaScript, Django Templates
**서버**: Ubuntu 24.04 (OCI A1 aarch64), Nginx, Gunicorn(WSGI)
**배포**: 161.118.232.178 (techchang.com)

## WHY (프로젝트 목적)

질문/답변 커뮤니티 + 인터랙티브 게임 플랫폼
- Stack Overflow 스타일 Q&A
- 5가지 브라우저 게임 (숫자야구, 2048, 지뢰찾기, 틱택토, 끝말잇기)
- 사용자 포인트 및 랭킹 시스템

## 구조

```
config/              # Django 설정 (settings/base.py, dev.py, prod.py)
community/           # 메인 앱 (구 pybo → community로 마이그레이션 완료)
  ├── views/         # 기능별 뷰 (question, answer, comment, games)
  ├── models.py      # Question, Answer, Comment, Games
  └── urls.py        # URL: namespace='community'
common/              # 인증 및 프로필
templates/           # Django 템플릿 (base.html 상속 구조)
  ├── base.html      # 기본 레이아웃
  └── community/     # community 앱 템플릿
static/              # 정적 파일 (style.css, Bootstrap, JS)
```

## HOW (개발 명령어)

**로컬 개발**:
```bash
source venv/bin/activate  # 가상환경 (Windows: venv\Scripts\activate)
python manage.py runserver
python manage.py makemigrations && python manage.py migrate
```

**서버 배포** (자세한 절차는 README.md 배포 섹션. 서버 경로: 프로젝트 `~/projects/mysite`, venv `~/venvs/mysite`):
```bash
cd ~/projects/mysite && git pull origin main
~/venvs/mysite/bin/pip install -r requirements-prod.txt
DJANGO_SETTINGS_MODULE=config.settings.prod ~/venvs/mysite/bin/python3 manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings.prod ~/venvs/mysite/bin/python3 manage.py collectstatic --noinput
sudo systemctl restart mysite
```

**검증**:
```bash
python manage.py check
sudo systemctl status mysite nginx
```

## 핵심 규칙

### URL/템플릿 네임스페이스
- ✅ `{% url 'community:index' %}`
- ❌ `{% url 'pybo:index' %}` (구 앱 이름, 사용 금지)
- ✅ `'community/question_list.html'`
- ❌ `'pybo/question_list.html'`

### 템플릿 구조
- 항상 `{% extends 'base.html' %}` 상속
- 정적 파일: `{% load static %}` → `{% static 'style.css' %}`
- 폼: `{% csrf_token %}` 필수

### 프론트엔드
- Bootstrap 5.3 우선 사용
- 커스텀 CSS는 `static/css/` 또는 `<style>` 태그
- JavaScript는 템플릿 하단 `<script>` 태그

## 배포 참고

- **서비스**: `/etc/systemd/system/mysite.service`
- **Nginx**: `/etc/nginx/sites-available/techchang`
- **로그**: `sudo journalctl -u mysite -n 50`, `logs/django.log`
- **정적파일**: `python manage.py collectstatic --clear`
- **DB 백업**: `python manage.py backup_db` → `backups/db_<ts>.sql.gz` (cron 매일 03:00)
- **cron**: ubuntu 계정 `crontab -l` (backup_db, send_log_report, send_visitor_report, auto_write_*)
