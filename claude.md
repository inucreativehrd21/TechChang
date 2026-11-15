# TechChang Community Platform

## WHAT (기술 스택)

**Backend**: Django 5.2.19, Python 3.12+, MySQL 8 (운영, `DJANGO_DB_ENGINE=mysql`) / SQLite3 (로컬·CI)
**Frontend**: Bootstrap 5.3, Vanilla JavaScript, Django Templates
**서버**: Ubuntu 24.04 (OCI A1 aarch64), Nginx, Gunicorn(WSGI)
**배포**: 161.118.232.178 (techchang.com)

## WHY (프로젝트 목적)

질문/답변 커뮤니티 + 인터랙티브 게임 플랫폼
- Stack Overflow 스타일 Q&A
- 야구선수 키우기 3모드(정식·라이트·익스트림), 숫자야구·2048·지뢰찾기(틱택토·끝말잇기 URL은 비활성)
- 사용자 포인트 및 랭킹 시스템

## 구조

```
config/              # Django 설정 (settings/base.py, dev.py, prod.py)
community/           # 메인 앱 (구 pybo → community로 마이그레이션 완료)
  ├── views/         # 기능별 뷰 (question, answer, comment, games)
  ├── models.py      # Question, Answer, Comment, Games
  └── urls.py        # URL: namespace='community'
common/              # 인증 및 프로필
office/              # 가상 연구실 (에이전트 역할 8개: agents.py, 회의 hold_meeting, 칼럼 파이프라인 office_publish, /lab/)
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
DJANGO_SETTINGS_MODULE=config.settings.prod ~/venvs/mysite/bin/python3 manage.py check && sudo systemctl restart mysite   # check 실패면 재시작하지 않는다(11-16 기동 실패 40초)
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
- **비공개 미디어**: `/media/question_files/`, `/media/questions/`, `/media/answers/`, `/media/comments/`, `/media/portfolio/`는 Nginx `auth_request`로 Django 권한을 확인한다. 운영 설정을 바꿀 때 [접근제어 문서](docs/private-media-access.md)를 따른다.
- **DB 백업**: `python manage.py backup_db` → `backups/db_<ts>.sql.gz` (cron 매일 03:00)
- **cron**: ubuntu 계정 `crontab -l` (backup_db, send_log_report, send_visitor_report, hold_meeting 일 20:00, 칼럼·연재 **예약 공개**: 전날 13·22시 `--prepare` → 공개 대기 → `office_release` 10분마다 / 당일 10시 `--if-missing` 안전망(office/schedule.py), make_newsletter 금 10:00, 야구 `rookie_daily` 00:10·`rookie_tick` 11~23시 5분마다)
- **AI 호출**: `common.services.claude.ask` → Claude Code 구독(`claude-sonnet-5-5`) 우선, 명시적인 한도 오류만 Codex 구독(`gpt-6.1-sol`, medium)으로 전환해요. 실제 전환은 `common/services/subscriptions.py`, Codex 제약은 `common/services/codex.py`에 있어요.
- **비용 정책**: 운영은 `CLAUDE_BACKEND=cli`, `CLAUDE_CLI_FALLBACK=false`, `AI_ALLOW_PAID_API=false`, `AI_FALLBACK_BACKEND=codex_cli`예요. 두 구독 모두 불가하면 보류해요. API 과금이나 `crew_work` 서버 실행으로 우회하지 않아요.
- **개인정보 경계**: 2026-10-29 시행 처리방침 이전에는 `send_log_report`의 Codex 폴백을 차단해요(`common/legal.py`). 시행일·현재 적용 버전을 구분하고, 비밀값·개인정보를 일반 콘텐츠 프롬프트에 넣지 않아요.
- **운영 참고 문서**: 구독 폴백은 `docs/codex-subscription-fallback.md`, 계정 연동은 `docs/social-login-setup.md`, 비공개 미디어는 `docs/private-media-access.md`를 참고해요.
- **연구실 단일 인계(2026-11-12)**: [docs/lab-handoff.md](docs/lab-handoff.md)에 칼럼 변경 공지 작성 지침, 편성·집필·관리자 수정·회의 선택 변경, 운영·감사 정책, 배포와 CI 근거를 통합했어요. 심화·실용 각 1편 편성과 일괄 검토·systemd 실행기는 운영 적용 상태이며 **A 유지·B 기본 전환 보류**예요. 날짜별 연구실 문서는 이 문서로 대체했어요. 공지를 작성할 때 구현 사실과 아직 사람 평가가 필요한 성과를 구분해요.
