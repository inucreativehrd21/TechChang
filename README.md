# TechChang 커뮤니티 사이트

> Django 기반 커뮤니티 플랫폼 with 게임, Q&A, 방명록

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Django](https://img.shields.io/badge/Django-5.2-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## 🌟 주요 기능

### 커뮤니티
- **Q&A 게시판**: 질문과 답변, 댓글, 투표 기능
- **방명록**: 방문자 메시지 남기기
- **사용자 프로필**: 활동 내역, 포인트, 이모티콘 시스템
- **카카오 로그인**: 소셜 로그인 지원

### 게임 센터
- **숫자야구**: 3자리 숫자 맞추기 게임
- **2048**: 타일 합치기 퍼즐 게임
- **지뢰찾기**: 클래식 지뢰찾기 게임
- **리더보드**: 각 게임별 순위 시스템

### 관리자 기능
- **커스텀 대시보드**: 통계 및 모니터링
- **사용자 관리**: 등급 변경, 활성화/비활성화
- **IP 차단**: 보안 관리
- **포인트 시스템**: 출석 체크, 이모티콘 상점

## 🚀 빠른 시작

### 사전 요구사항
- Python 3.11 이상
- pip 및 venv

### 로컬 개발 환경 설정

1. **저장소 클론**
```bash
git clone <repository-url>
cd mysite
```

2. **가상환경 생성 및 활성화**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. **패키지 설치**
```bash
pip install -r requirements.txt
```

4. **환경변수 설정**
```bash
cp .env.example .env
# .env 파일을 열어서 필요한 값들을 입력하세요
```

필수 환경변수:
- `DJANGO_SECRET_KEY`: Django SECRET_KEY
- `DEBUG`: 개발 환경에서는 `True`
- `OPENAI_API_KEY`: OpenAI API 키 (선택사항)
- `KAKAO_REST_API_KEY`: 카카오 로그인 API 키
- `KAKAO_CLIENT_SECRET`: 카카오 클라이언트 시크릿

5. **데이터베이스 마이그레이션**
```bash
python manage.py migrate
```

6. **관리자 계정 생성**
```bash
python manage.py createsuperuser
```

7. **개발 서버 실행**
```bash
python manage.py runserver
```

브라우저에서 http://127.0.0.1:8000 접속

## 📦 프로덕션 배포

### 새 서버에 배포하기

자세한 배포 가이드는 [DEPLOYMENT.md](DEPLOYMENT.md)를 참조하세요.

#### 자동 배포 (추천)
```bash
# 프로젝트 파일을 서버에 업로드 후
cd /home/ubuntu/projects/mysite
chmod +x deploy_new_instance.sh
./deploy_new_instance.sh
```

#### 수동 배포
[DEPLOYMENT.md](DEPLOYMENT.md)의 "방법 2: 수동 배포" 섹션 참조

### 기존 서버 업데이트

**방법 1: 기존 서버 In-Place 업데이트 (권장 ⭐)**
- **빠른 체크리스트**: [QUICK_UPDATE_CHECKLIST.md](QUICK_UPDATE_CHECKLIST.md) - 10분 완료
- **상세 가이드**: [INPLACE_UPDATE.md](INPLACE_UPDATE.md) - 단계별 설명

**방법 2: 새 서버로 이전**
- **빠른 가이드**: [QUICK_MIGRATION.md](QUICK_MIGRATION.md) - 3단계 요약
- **상세 가이드**: [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) - 전체 프로세스

## 🏗️ 프로젝트 구조

```
mysite/
├── common/              # 사용자 인증, 프로필, 관리자 기능
├── community/           # Q&A, 게임, 방명록 (이전 pybo 앱)
├── config/              # Django 프로젝트 설정
│   ├── settings/
│   │   ├── base.py      # 기본 설정
│   │   ├── local.py     # 로컬 개발 설정
│   │   └── prod.py      # 프로덕션 설정
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── templates/           # HTML 템플릿
│   ├── common/
│   └── community/
├── static/              # 정적 파일 (CSS, JS, 이미지)
├── media/               # 사용자 업로드 파일
├── nginx.conf           # Nginx 설정 파일
├── deploy_new_instance.sh  # 자동 배포 스크립트
├── DEPLOYMENT.md        # 배포 가이드
└── requirements.txt     # Python 패키지 목록
```

## 🔧 기술 스택

### 백엔드
- **Django 5.2**: 웹 프레임워크
- **Channels**: WebSocket 지원 (비활성화됨)
- **Django Allauth**: 소셜 로그인

### 프론트엔드
- **Bootstrap 5**: UI 프레임워크
- **GSAP**: 애니메이션
- **Font Awesome**: 아이콘

### 배포
- **Gunicorn**: WSGI 서버
- **Nginx**: 리버스 프록시
- **Let's Encrypt**: SSL 인증서

### 데이터베이스
- **SQLite** (개발 및 소규모 프로덕션)
- **PostgreSQL** (대규모 프로덕션 권장)

## 📝 환경변수

`.env` 파일에서 설정할 수 있는 주요 환경변수:

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `DJANGO_SECRET_KEY` | Django SECRET_KEY | 필수 |
| `DEBUG` | 디버그 모드 | `False` |
| `DJANGO_ALLOWED_HOSTS` | 허용 호스트 | `techchang.com,www.techchang.com` |
| `OPENAI_API_KEY` | OpenAI API 키 | 선택 |
| `KAKAO_REST_API_KEY` | 카카오 REST API 키 | 필수 (카카오 로그인 사용 시) |
| `KAKAO_CLIENT_SECRET` | 카카오 클라이언트 시크릿 | 필수 (카카오 로그인 사용 시) |
| `RATE_LIMIT_REQUESTS` | Rate limit 요청 수 | `300` |
| `DDOS_THRESHOLD` | DDoS 감지 임계값 | `120` |

전체 환경변수 목록은 [.env.example](.env.example) 참조

## 🔐 보안

- ✅ HTTPS 강제 (프로덕션)
- ✅ CSRF 보호
- ✅ XSS 방지
- ✅ SQL Injection 방지
- ✅ Rate Limiting
- ✅ DDoS 보호
- ✅ 보안 헤더 (HSTS, CSP, X-Frame-Options 등)
- ✅ 환경변수 기반 설정

## 📊 성능

- **정적 파일 캐싱**: 1년
- **Gzip 압축**: CSS, JS, 폰트
- **HTTP/2**: 지원
- **Lazy Loading**: 이미지 지연 로딩

## 🛠️ 개발

### 코드 스타일
- PEP 8 준수
- Black 포매터 사용 권장

### 테스트
```bash
python manage.py test
```

### 마이그레이션 생성
```bash
python manage.py makemigrations
python manage.py migrate
```

### 정적 파일 수집
```bash
python manage.py collectstatic
```

## 📖 문서

- **배포 관련**
  - [배포 가이드](DEPLOYMENT.md) - 새 서버 배포 전체 프로세스
  - [빠른 마이그레이션](QUICK_MIGRATION.md) - 기존 서버 → 새 서버 3단계
  - [상세 마이그레이션](MIGRATION_GUIDE.md) - 데이터 마이그레이션 완전 가이드
- **기타**
  - [변경 로그](CHANGELOG_2024.md) - 2024년 개편 내역
  - [.env 예시](.env.example) - 환경변수 템플릿

## 🐛 트러블슈팅

일반적인 문제 해결 방법은 [DEPLOYMENT.md](DEPLOYMENT.md#트러블슈팅)의 트러블슈팅 섹션을 참조하세요.

## 📜 라이선스

이 프로젝트는 개인 프로젝트입니다.

## 👤 개발자

**TechChang**
- Website: https://techchang.com
- Email: admin@techchang.com

## 🙏 감사의 말

- Django 커뮤니티
- Bootstrap 팀
- 모든 오픈소스 기여자들

---

## 📅 최근 업데이트

### 2024년 12월 - 대규모 개편
- `pybo` 앱을 `community`로 리네임
- URL 구조 개선 (`/pybo/` → `/`)
- 보안 강화 (환경변수 기반 설정)
- 도메인 변경 (tc.o-r.kr → techchang.com)
- 자동 배포 스크립트 추가
- 완전한 배포 가이드 작성

자세한 변경사항은 [CHANGELOG_2024.md](CHANGELOG_2024.md) 참조

---

**Happy Coding! 🚀**
