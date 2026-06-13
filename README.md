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

**Backend** — Django 5.2.6, Python 3.12+, SQLite3, Channels(Daphne, WebSocket)
**AI** — Anthropic Claude API (`anthropic` SDK)
**Frontend** — Bootstrap 5.3, Vanilla JavaScript, Django Templates
**인증** — Django Allauth, 카카오 OAuth, 이메일 인증 코드
**배포** — Ubuntu 24.04, Nginx, Gunicorn(WSGI), Let's Encrypt SSL
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
├── requirements.txt
└── manage.py
```

> 앱/템플릿 네임스페이스는 `community`를 사용합니다 (구 `pybo`는 사용하지 않음).

---

## 📦 배포

프로덕션은 **Ubuntu + Nginx + Gunicorn(WSGI) + systemd** 구성으로 운영합니다.

### 기존 서버 코드 업데이트

```bash
cd /home/ubuntu/projects/mysite
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart mysite
```

> `staticfiles/` 는 `collectstatic` 산출물이므로 저장소에서 추적하지 않습니다(서버에서 생성).

### 새 서버 구축

<details>
<summary><b>1) EC2 인스턴스 & 초기 설정</b></summary>

추천 사양: Ubuntu 24.04 LTS, t3.small 이상, 스토리지 20GB+.
Security Group — SSH(22, 본인 IP) / HTTP(80) / HTTPS(443).

```bash
ssh -i your-key.pem ubuntu@your-instance-ip

sudo apt update && sudo apt upgrade -y
sudo timedatectl set-timezone Asia/Seoul
sudo apt install -y python3-venv python3-dev nginx \
    git curl build-essential certbot python3-certbot-nginx
```

</details>

<details>
<summary><b>2) 도메인(DNS) 설정</b></summary>

도메인 제공업체(가비아, Route53 등)에서 A 레코드를 추가합니다.

```
Type    Name    Value
A       @       <EC2 Public IP>
A       www     <EC2 Public IP>
```

전파 확인: `nslookup techchang.com` / `dig techchang.com`

</details>

<details>
<summary><b>3) 프로젝트 배포</b></summary>

```bash
# 코드 가져오기
mkdir -p /home/ubuntu/projects && cd /home/ubuntu/projects
git clone https://github.com/inucreativehrd21/TechChang.git mysite
cd mysite

# 가상환경 & 패키지
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 환경변수 (SECRET_KEY 생성 예시)
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
cp .env.example .env && nano .env   # DJANGO_SECRET_KEY, DEBUG=False, ALLOWED_HOSTS, API 키 입력

# Django 초기화
python manage.py collectstatic --noinput
python manage.py migrate
python manage.py createsuperuser
```

</details>

<details>
<summary><b>4) Gunicorn (systemd) & Nginx</b></summary>

저장소의 [mysite.service](mysite.service)·[gunicorn.conf.py](gunicorn.conf.py)·[nginx.conf](nginx.conf) 를 사용합니다.

```bash
# systemd 서비스 등록
sudo cp mysite.service /etc/systemd/system/mysite.service
sudo systemctl daemon-reload
sudo systemctl enable --now mysite
sudo systemctl status mysite

# Nginx 설정
sudo cp nginx.conf /etc/nginx/sites-available/techchang
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/techchang /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```

</details>

<details>
<summary><b>5) SSL 인증서 (Let's Encrypt)</b></summary>

```bash
sudo certbot --nginx -d techchang.com -d www.techchang.com
sudo systemctl status certbot.timer   # 자동 갱신 확인
```

</details>

<details>
<summary><b>운영 · 트러블슈팅</b></summary>

**로그 확인**
```bash
sudo journalctl -u mysite -n 50          # 애플리케이션
sudo tail -f /var/log/nginx/techchang_error.log
tail -f /home/ubuntu/projects/mysite/logs/django.log
```

**DB 백업 (SQLite)**
```bash
mkdir -p ~/backups
cp db.sqlite3 ~/backups/db_$(date +%Y%m%d_%H%M%S).sqlite3
# 자동 백업 cron 예: 0 2 * * * cp .../db.sqlite3 ~/backups/db_$(date +\%Y\%m\%d).sqlite3
```

| 증상 | 점검 |
|------|------|
| 502 Bad Gateway | `systemctl status mysite` → 재시작, Nginx 에러 로그 |
| 정적 파일 미로드 | `collectstatic --noinput`, `staticfiles/` 권한(ubuntu:www-data) |
| CSRF 에러 | `.env` 의 `DJANGO_ALLOWED_HOSTS`, prod.py `SECURE_PROXY_SSL_HEADER` |
| 마이그레이션 에러 | `python manage.py showmigrations` 로 상태 확인 |

**보안 체크리스트** — `.env` gitignore 포함 · `DEBUG=False` · 강력한 `SECRET_KEY` · `ALLOWED_HOSTS` 설정 · SSL 적용 · SSH 키 인증 · 정기 백업.

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
