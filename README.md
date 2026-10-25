# TechChang (테크창) 커뮤니티 플랫폼

> Django 기반 Q&A 커뮤니티 + 브라우저 게임 + 포트폴리오 플랫폼
> 운영 사이트: **[techchang.com](https://techchang.com)**

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![Django](https://img.shields.io/badge/Django-5.2.6-green.svg)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3.svg)

---

## 📌 프로젝트 소개

TechChang는 Stack Overflow 스타일의 질문/답변 커뮤니티에 인터랙티브 브라우저 게임과
회원 포트폴리오 기능을 결합한 종합 커뮤니티 플랫폼입니다. Claude Code·Codex 구독 CLI를 활용한
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
| 게임 | 현재 운영 기능 |
|------|------|
| 야구선수 키우기 정식 모드 | 매일 활동·훈련·경기, 날짜별 구단 리포트, 리그·기록실 |
| 야구선수 키우기 라이트 모드 | 손님 플레이, 고1부터 은퇴까지 커리어, 전당·카드 |
| 야구선수 키우기 익스트림 모드 | 높은 성장 효율, 전용 사건 12종, 별도 커리어·순위·카드 |
| 숫자야구 / 2048 / 지뢰찾기 | 퍼즐 게임과 리더보드 |

야구 모드는 테크창 회원의 동나이·투타 기록 비교와 전체 리그·구단 조회를 제공해요.
가상 구단 선수의 시뮬레이션 기록과 공개 회원 DB 기록은 구분해요.
틱택토·끝말잇기는 코드만 보관하며 현재 URL은 비활성 상태예요.
익스트림은 운영에서 `ROOKIE_EXTREME_ENABLED=true`, 운영자 실험실은 별도 플래그로 기본 비공개예요.

### 연구실과 AI 호출
- **연구실** (`/lab/`) — 팀장·편집장·HRD/데이터/프로그래밍 칼럼니스트·검증관·평론가·차트 담당의 8개 역할이에요.
  회의 → 기획 → 설계도·근거 확인 → 집필 → 코드 점검 → 검증·평론·시각화·심사 → 보완 → 공개 대기로 진행해요.
- **구독 라우팅** — `common.services.claude.ask`가 Claude Code를 우선 쓰고, 명시적인 사용량 한도 때만
  Codex `gpt-6.1-sol`/medium으로 전환해요. 둘 다 쓸 수 없으면 보류하며 유료 API는 차단해요.
- **예약 공개** — 칼럼은 화·목·토, 연재는 월요일 10시 공개해요. 전날과 당일 새벽에 준비하고
  `office_release`가 10분 간격으로 준비된 원고를 공개해요.
- **정비** — 로그 지적사항과 회의 과제를 작업 카드로 관리해요. 서버에서 `crew_work`를 실행하지 않아요.
  패치·PR·배포는 승인된 개발 작업으로 처리하고 CI는 `check`와 테스트를 담당해요.
  과거 `auto-fix.yml`/`repository_dispatch` 자동 PR 흐름은 현재 저장소에 없어요.

### 운영 / 관리자
- **관리자 대시보드** — 통계·모니터링, 사용자 관리(등급/활성화), IP 차단
- **서버 모니터링** — 웹 대시보드(`/common/admin/monitor/`) + 이메일 로그 리포트
- **방문자 리포트** — 주간/월간 방문 통계 메일, Google Search Console(노출/클릭/CTR) 연동
- **모바일 전용 UX** — User-Agent + 쿠키 기반 모바일 감지, 별도 모바일 템플릿 세트

---

## 🔧 기술 스택

**Backend** — Django 5.2.6, Python 3.12+, MySQL 8 (운영) / SQLite3 (로컬·CI), Channels(Daphne, WebSocket)
**AI** — Claude Code 구독 CLI → Codex 구독 CLI 폴백. Anthropic SDK는 선택 경로만 남기고 운영 API 과금은 차단
**Frontend** — Bootstrap 5.3, Vanilla JavaScript, Django Templates
**인증** — Django 계정·프로필 공용, 카카오/Google OAuth 식별자 연결, 이메일 인증 코드
**배포** — Ubuntu 24.04 (OCI), Nginx, Gunicorn(WSGI), MySQL 8, Let's Encrypt SSL
**CI** — GitHub Actions `ci.yml` (`check` + `test`)

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

이 작업 PC의 Windows 환경은 `python`이 스텁이므로 `py -3.10 manage.py ...`를 사용해요.
로컬 화면 검증은 운영 DB와 분리한 SQLite·로컬 메일 설정에서 진행해요.

### 주요 환경변수
| 변수 | 설명 |
|------|------|
| `DJANGO_SECRET_KEY` | Django SECRET_KEY (필수) |
| `DEBUG` | 개발 시 `True`, 운영 시 `False` |
| `DJANGO_ALLOWED_HOSTS` | 허용 호스트 |
| `ANTHROPIC_API_KEY` | 유료 API를 명시적으로 허용한 환경에서만 사용하는 선택 키 |
| `CLAUDE_BACKEND` / `CLAUDE_CODE_OAUTH_TOKEN` | `cli` 면 Claude Code 구독으로 호출 |
| `AI_FALLBACK_BACKEND` | `codex_cli` 면 Claude 사용량 한도 때 Codex 구독으로 전환 |
| `AI_ALLOW_PAID_API` | 기본 `false`. Codex 폴백을 선택하면 값과 무관하게 API 키 과금 경로 차단 |
| `CODEX_HOME` / `CODEX_MODEL` | 서버 전용 구독 인증 저장소 / 기본 `gpt-6.1-sol` |
| `KAKAO_REST_API_KEY` / `KAKAO_CLIENT_SECRET` | 카카오 로그인 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google 로그인·기존 계정 연결 |
| `ROOKIE_EXTREME_ENABLED` / `ROOKIE_EXTREME_PREVIEW` | 일반 공개 / 운영자 실험실(별도) |
| `RATE_LIMIT_REQUESTS` / `DDOS_THRESHOLD` | Rate limit / DDoS 임계값 |

전체 목록은 [.env.example](.env.example) 참조.

구독 폴백의 인증·비공개 품질 비교·운영 적용·롤백 절차는
[Codex 구독 폴백 운영 안내](docs/codex-subscription-fallback.md)를 참고하세요.
최신 운영 점검은 [사이트 운영 런북](docs/site-operations.md), 구조 검토는
[연구실 아키텍처 리포트](docs/lab-architecture-review-20261024.md)에 있어요.

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
├── office/              # 가상 연구실: 에이전트 팀 회의(hold_meeting)·칼럼 파이프라인(office_publish)·/lab/
├── templates/           # base.html / base_mobile.html 상속 구조
│   ├── common/          # (mobile/ 서브 디렉터리 포함)
│   └── community/       # (mobile/ 서브 디렉터리 포함)
├── static/              # CSS · JS · 이미지
├── .github/workflows/   # ci.yml (검증)
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

cp .env.example .env && chmod 600 .env
# 사용할 수 있는 편집기로 .env를 설정해요. 저장소·채팅에 비밀값을 넣지 않아요.
#   DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS(도메인+서버 IP), DJANGO_DB_*(ENGINE=mysql),
#   이메일(DJANGO_EMAIL_*, DJANGO_ADMIN_EMAIL), Claude/Codex 구독 설정, KAKAO_*, GOOGLE_* 등
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
0 20 * * 0  ... hold_meeting --email <admin@example.com>
# 칼럼: HRD 화 / 데이터 목 / 프로그래밍 토 10시 공개
0 13 * * 1  ... office_publish --topic hrd --prepare
0 22 * * 1  ... office_publish --topic hrd --prepare
0 4 * * 2   ... office_publish --topic hrd --prepare
0 10 * * 2  ... office_publish --topic hrd --if-missing
# data: 수 13·22시 / 목 04·10시, coding: 금 13·22시 / 토 04·10시
0 13 * * 0  ... auto_write_series --series auto --prepare
0 22 * * 0  ... auto_write_series --series auto --prepare
0 4 * * 1   ... auto_write_series --series auto --prepare
0 10 * * 1  ... auto_write_series --series auto --if-missing
*/10 * * * * ... office_release
0 10 * * 5  ... make_newsletter
10 0 * * *  ... rookie_daily
*/5 11-23 * * * ... rookie_tick      # 야구선수 키우기 정식: 시간대 경기(ROOKIE_FULL_SLOTS, 시즌 2부터)
15 3 * * *  ... purge_personal_data
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
