# TechChang (테크창) 커뮤니티 플랫폼

> Django 기반 Q&A 커뮤니티 + 브라우저 게임 + 포트폴리오 플랫폼
> 운영 사이트: **[techchang.com](https://techchang.com)**

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![Django](https://img.shields.io/badge/Django-5.2.6-green.svg)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3.svg)

---

## 📌 프로젝트 소개

TechChang는 Stack Overflow 스타일의 질문/답변 커뮤니티에 인터랙티브 브라우저 게임과
회원 포트폴리오 기능을 결합한 종합 커뮤니티 플랫폼입니다. AI(Claude)를 활용한
자동 칼럼 작성·답변 생성, 서버 로그 기반 자동 개선 파이프라인까지 운영 자동화에
초점을 맞춰 설계했습니다.

---

## 🌟 주요 기능

### 커뮤니티
- **Q&A 게시판** — 질문/답변/댓글, 추천(투표), 카테고리 보드, 파일 첨부
- **방명록** — 방문자 메시지
- **회원 포트폴리오** — 회원별 포트폴리오(프로젝트·경력·역량), 다중 포트폴리오(최대 5개),
  히어로 배경 이미지, 관리자 승인제 게시
- **프로필 / 포인트 / 랭킹** — 출석 체크, 포인트, 이모티콘, 사용자 랭킹

### 게임 센터 (`/games/`)
| 게임 | 설명 | 리더보드 |
|------|------|:-------:|
| 숫자야구 | 3자리 숫자 맞추기 | ✅ |
| 2048 | 타일 합치기 퍼즐 | ✅ |
| 지뢰찾기 | 클래식 마인스위퍼 | ✅ |
| 틱택토 | 실시간 대전(WebSocket) | — |
| 끝말잇기 | 단어 잇기 대전 | — |

### AI 기능 (Anthropic Claude)
- **AI 칼럼 자동 작성** — cron 기반 정기 칼럼 생성
- **AI 답변 생성** — 질문에 대한 보조 답변
- **로그 지적사항 → 자동 수정 PR 파이프라인** — 서버 로그를 분석해 지적사항을 도출하고,
  관리자 승인 시 GitHub Actions(`repository_dispatch`)로 Claude가 수정 PR을 생성, CI가 검증
  (심각도별 모델 선택, 종류 기반 중복 제거)

### 운영 / 관리자
- **관리자 대시보드** — 통계·모니터링, 사용자 관리(등급/활성화), IP 차단
- **서버 모니터링** — 웹 대시보드(`/common/admin/monitor/`) + 이메일 로그 리포트
- **방문자 리포트** — 주간/월간 방문 통계 메일, Google Search Console(노출/클릭/CTR) 연동
- **모바일 전용 UX** — User-Agent + 쿠키 기반 모바일 감지, 별도 모바일 템플릿 세트

---

## 🔧 기술 스택

**Backend** — Django 5.2.6, Python 3.12+, MySQL 8 (운영) / SQLite3 (로컬·CI), Channels(Daphne, WebSocket)
**AI** — Anthropic Claude API (`anthropic` SDK)
**Frontend** — Bootstrap 5.3, Vanilla JavaScript, Django Templates
**인증** — Django Allauth, 카카오 OAuth, 이메일 인증 코드
**배포** — Ubuntu 24.04 (OCI), Nginx, Gunicorn(WSGI), MySQL 8, Let's Encrypt SSL
**CI** — GitHub Actions (`check` + `test`), AI 자동 수정 워크플로

---

## 🚀 빠른 시작 (로컬 개발)

```bash
# 1. 클론
git clone https://github.com/inucreativehrd21/TechChang.git
cd TechChang

# 2. 가상환경
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

# 3. 패키지 설치
pip install -r requirements.txt

# 4. 환경변수
cp .env.example .env           # 값 채우기

# 5. DB 마이그레이션 & 관리자 계정
python manage.py migrate
python manage.py createsuperuser

# 6. 개발 서버
python manage.py runserver
```

브라우저에서 http://127.0.0.1:8000 접속.

### 주요 환경변수
| 변수 | 설명 |
|------|------|
| `DJANGO_SECRET_KEY` | Django SECRET_KEY (필수) |
| `DEBUG` | 개발 시 `True`, 운영 시 `False` |
| `DJANGO_ALLOWED_HOSTS` | 허용 호스트 |
| `ANTHROPIC_API_KEY` | Claude API 키 (AI 기능) |
| `KAKAO_REST_API_KEY` / `KAKAO_CLIENT_SECRET` | 카카오 로그인 |
| `RATE_LIMIT_REQUESTS` / `DDOS_THRESHOLD` | Rate limit / DDoS 임계값 |

전체 목록은 [.env.example](.env.example) 참조.

---

## 🏗️ 프로젝트 구조

```
mysite/
├── config/              # Django 설정 (settings/base.py · local.py · prod.py)
├── common/              # 인증·프로필·관리자·보안 미들웨어·모바일 로더
├── community/           # Q&A·게임·방명록·포트폴리오 (구 pybo 앱)
│   ├── views/           # 기능별 뷰 (question/answer/comment/games/portfolio…)
│   ├── models.py        # Question, Answer, Portfolio, 게임 모델 등
│   ├── consumers.py     # WebSocket consumer (실시간 게임)
│   └── urls.py          # namespace='community'
├── templates/           # base.html / base_mobile.html 상속 구조
│   ├── common/          # (mobile/ 서브 디렉터리 포함)
│   └── community/       # (mobile/ 서브 디렉터리 포함)
├── static/              # CSS · JS · 이미지
├── .github/workflows/   # ci.yml (검증), auto-fix.yml (AI 자동 수정)
├── nginx.conf           # Nginx 설정
├── mysite.service       # systemd 유닛
├── gunicorn.conf.py     # Gunicorn 설정
├── requirements.txt       # 공통 의존성 (로컬·CI)
├── requirements-prod.txt  # 운영 추가 의존성 (mysqlclient)
└── manage.py
```

> 앱/템플릿 네임스페이스는 `community`를 사용합니다 (구 `pybo`는 사용하지 않음).

---

## 📦 배포

프로덕션은 **Ubuntu 24.04 (OCI, aarch64) + Nginx + Gunicorn(WSGI) + systemd + MySQL 8** 구성으로 운영합니다.

| 항목 | 경로 |
|------|------|
| 프로젝트 | `/home/ubuntu/projects/mysite` |
| 가상환경 | `/home/ubuntu/venvs/mysite` (프로젝트 밖) |
| 서비스 | `/etc/systemd/system/mysite.service` ([mysite.service](mysite.service)) — `ubuntu` 계정, `EnvironmentFile=.env` |
| Nginx | `/etc/nginx/sites-available/techchang` ([nginx.conf](nginx.conf)) |
| 로그 | `sudo journalctl -u mysite`, `logs/django.log`, `logs/gunicorn_*.log`, `/var/log/nginx/techchang_*.log` |
| 백업 | `backups/db_<ts>.sql.gz` (`manage.py backup_db`, cron 매일 03:00 / 주 1회 메일) |

### 기존 서버 코드 업데이트

```bash
cd ~/projects/mysite && git pull origin main
~/venvs/mysite/bin/pip install -r requirements-prod.txt
export DJANGO_SETTINGS_MODULE=config.settings.prod
~/venvs/mysite/bin/python3 manage.py migrate
~/venvs/mysite/bin/python3 manage.py collectstatic --noinput
sudo systemctl restart mysite && systemctl is-active mysite
```

> `staticfiles/` 는 `collectstatic` 산출물이므로 저장소에서 추적하지 않습니다(서버에서 생성).

### 새 서버 구축

<details>
<summary><b>1) 인스턴스 & 시스템 패키지</b></summary>

Ubuntu 24.04 LTS, 2 vCPU / 4GB+ 권장. 방화벽 22/80/443 개방
(OCI 는 VCN 보안 목록 **과** 인스턴스 `iptables` 두 겹 — `sudo iptables -I INPUT 6 -p tcp -m state --state NEW --dport 80 -j ACCEPT` 등 + `sudo netfilter-persistent save`).

```bash
sudo timedatectl set-timezone Asia/Seoul       # crontab 시각 기준
sudo apt update && sudo apt install -y git curl rsync cron logrotate \
    python3 python3-venv python3-dev build-essential pkg-config \
    default-libmysqlclient-dev libjpeg-dev zlib1g-dev libmagic1 \
    mysql-server mysql-client nginx certbot python3-certbot-nginx
sudo usermod -aG adm,systemd-journal ubuntu    # send_log_report 가 nginx 로그·journalctl 읽음
sudo chmod o+x /home/ubuntu                    # 24.04 는 홈이 750 → nginx 가 static/media 접근 불가
```

> Ubuntu **Minimal** 이미지에는 `cron`/`logrotate` 가 없으니 반드시 설치.

</details>

<details>
<summary><b>2) MySQL</b></summary>

```bash
sudo mysql <<'SQL'
CREATE DATABASE techchang CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'techchang'@'localhost' IDENTIFIED BY '<비밀번호>';
CREATE USER 'techchang'@'127.0.0.1' IDENTIFIED BY '<비밀번호>';
GRANT ALL PRIVILEGES ON techchang.* TO 'techchang'@'localhost', 'techchang'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
# USE_TZ=True 환경에서 날짜 조회에 필요한 타임존 테이블
mysql_tzinfo_to_sql /usr/share/zoneinfo 2>/dev/null | sudo mysql -D mysql
```

</details>

<details>
<summary><b>3) 프로젝트 · 환경변수 · Django</b></summary>

```bash
mkdir -p ~/projects ~/venvs && cd ~/projects
git clone https://github.com/inucreativehrd21/TechChang.git mysite && cd mysite
python3 -m venv ~/venvs/mysite
~/venvs/mysite/bin/pip install --upgrade pip wheel
~/venvs/mysite/bin/pip install -r requirements-prod.txt      # mysqlclient 포함

cp .env.example .env && chmod 600 .env && nano .env
#   DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS(도메인+서버 IP), DJANGO_DB_*(ENGINE=mysql),
#   이메일(DJANGO_EMAIL_*, DJANGO_ADMIN_EMAIL), ANTHROPIC_API_KEY, KAKAO_* 등
#   SECRET_KEY 생성: python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

export DJANGO_SETTINGS_MODULE=config.settings.prod
~/venvs/mysite/bin/python3 manage.py check
~/venvs/mysite/bin/python3 manage.py migrate
~/venvs/mysite/bin/python3 manage.py collectstatic --noinput
~/venvs/mysite/bin/python3 manage.py createsuperuser        # 새 DB 일 때
```

기존 서버에서 옮기는 경우: `.env`, `media/`, `backups/`, `.env` 가 가리키는 외부 파일(GSC `token.json` 등)을 rsync 하고
최신 `backups/db_*.sql.gz` 를 복원합니다.
```bash
gunzip -c backups/db_YYYYMMDD_HHMMSS.sql.gz | mysql -u techchang -p techchang
~/venvs/mysite/bin/python3 manage.py migrate
```

</details>

<details>
<summary><b>4) Gunicorn(systemd) · Nginx · SSL</b></summary>

```bash
sudo cp mysite.service /etc/systemd/system/mysite.service
sudo systemctl daemon-reload && sudo systemctl enable --now mysite

sudo cp nginx.conf /etc/nginx/sites-available/techchang
sudo ln -sf /etc/nginx/sites-available/techchang /etc/nginx/sites-enabled/ && sudo rm -f /etc/nginx/sites-enabled/default
# 인증서가 아직 없으면 nginx.conf 의 443 블록 때문에 nginx -t 가 실패한다 →
# 먼저 80 만 있는 임시 설정으로 띄운 뒤 certbot 을 받거나, 기존 서버의 /etc/letsencrypt 를 rsync 로 가져온다.
sudo certbot --nginx -d techchang.com -d www.techchang.com
sudo nginx -t && sudo systemctl reload nginx
sudo certbot renew --dry-run
```

인증서 전에 IP 로 HTTP 검증이 필요하면 `.env` 에 `DJANGO_SECURE_SSL_REDIRECT=false` 를 잠시 두고(검증 후 삭제) 재시작합니다.
세션/CSRF 쿠키는 Secure 고정이라 HTTP 로는 로그인이 되지 않습니다.

</details>

<details>
<summary><b>5) cron (ubuntu 계정)</b></summary>

`crontab -e` — 경로는 절대경로, `%` 는 `\%` 로 이스케이프. 리포트 로그 `/var/log/techchang_report.log` 는 `sudo touch` 후 `chown ubuntu` 로 미리 생성.

```
0 3 * * *   cd /home/ubuntu/projects/mysite && /home/ubuntu/venvs/mysite/bin/python3 manage.py backup_db --keep 7 --dest /home/ubuntu/projects/mysite/backups >> /var/log/techchang_report.log 2>&1
30 3 * * 1  ... backup_db --keep 4 --dest ... --email <admin@example.com>
0 8 * * *   ... send_log_report --hours 24 --to <admin@example.com>
0 8 * * 1   ... send_log_report --hours 168 --to <admin@example.com>
30 8 * * 1  ... send_visitor_report --period weekly --to <admin@example.com>
0 9 1 * *   ... send_visitor_report --period monthly --to <admin@example.com>
0 10 * * 2  ... auto_write_columns --topic hrd    >> /home/ubuntu/projects/mysite/logs/techchang_columns.log 2>&1
0 10 * * 4  ... auto_write_columns --topic data   >> .../logs/techchang_columns.log 2>&1
0 10 * * 6  ... auto_write_columns --topic coding >> .../logs/techchang_columns.log 2>&1
0 10 * * 1  [ $(( $(date +\%V) \% 2 )) -eq 1 ] && ... auto_write_series >> .../logs/techchang_series.log 2>&1
```

</details>

<details>
<summary><b>운영 · 트러블슈팅</b></summary>

**로그 확인**
```bash
sudo journalctl -u mysite -n 50
sudo tail -f /var/log/nginx/techchang_error.log
tail -f ~/projects/mysite/logs/django.log
```

**DB 백업 / 복원 (MySQL)**
```bash
~/venvs/mysite/bin/python3 manage.py backup_db --keep 7          # backups/db_<ts>.sql.gz
gunzip -c backups/db_<ts>.sql.gz | mysql -u techchang -p techchang && ~/venvs/mysite/bin/python3 manage.py migrate
```

| 증상 | 점검 |
|------|------|
| 502 Bad Gateway | `systemctl status mysite` → 재시작, `journalctl -u mysite -n 50` |
| 정적/미디어 403·404 | `collectstatic --noinput`, `ls -ld /home/ubuntu` 가 `o+x` 인지, nginx `alias` 경로 |
| 빈 사이트(데이터 없음) | `.env` 에 `DJANGO_DB_ENGINE=mysql` 누락 → SQLite 로 기동됨 |
| `Error loading MySQLdb` | `pip install -r requirements-prod.txt` (mysqlclient) + apt 빌드 의존성 |
| 400 Bad Request | `.env` `DJANGO_ALLOWED_HOSTS` 에 도메인/IP 누락 |
| CSRF 에러 | prod.py `SECURE_PROXY_SSL_HEADER`, nginx `X-Forwarded-Proto` |
| 마이그레이션 에러 | `python manage.py showmigrations` 로 상태 확인 |

**보안 체크리스트** — `.env` gitignore 포함·600 권한 · `DEBUG=False` · 강력한 `SECRET_KEY` · `ALLOWED_HOSTS` 설정 · SSL 적용 · SSH 키 인증 · 정기 백업.

</details>

---

## 🔐 보안

- HTTPS 강제(HSTS), CSP **Nonce** 기반 정책, CSRF / XSS / SQL Injection 방어
- 카카오 OAuth **State 토큰**, 8자리 이메일 인증 코드
- Rate Limiting · DDoS 감지 미들웨어, 관리자 IP 차단
- 업로드 파일 MIME 검증, HTML 새니타이즈(bleach)
- 환경변수(`.env`) 기반 비밀 관리 (저장소 미포함)

---

## 🛠️ 개발

```bash
python manage.py check          # 시스템 점검 (커밋 전 필수)
python manage.py test           # 테스트
python manage.py makemigrations && python manage.py migrate
python manage.py collectstatic  # 정적 파일 수집
```

GitHub Actions가 push/PR 시 `check`와 `test`를 자동 실행합니다.

---

## 👤 개발자

**문승현 (Moon Seunghyun)**
인천대학교 창의인재개발학과 / 컴퓨터공학부
📧 seunghyunmoon55@gmail.com

---

## 📜 라이선스

개인 프로젝트입니다.
