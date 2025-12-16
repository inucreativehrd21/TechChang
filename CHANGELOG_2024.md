# TechChang 커뮤니티 사이트 개편 변경사항

## 개편 날짜: 2024년 12월

---

## 주요 변경사항

### 1. **앱 리네임: pybo → community**
- 실습용 이름에서 전문적인 이름으로 변경
- 모든 URL 패턴 업데이트: `/pybo/...` → `/...` (루트 경로)
- 템플릿 디렉토리: `templates/pybo/` → `templates/community/`
- Python 모듈: `pybo.models` → `community.models`

**영향받는 파일:**
- `config/settings/base.py` - INSTALLED_APPS
- `config/urls.py` - URL 패턴
- `config/asgi.py` - WebSocket 라우팅
- `common/views.py` - 모델 import
- `community/apps.py` - AppConfig
- `community/urls.py` - app_name
- 모든 템플릿 파일 (127개 참조 업데이트)

---

### 2. **보안 강화**
#### SECRET_KEY 환경변수화
- **변경 전:** 하드코딩된 SECRET_KEY
- **변경 후:** 환경변수 `DJANGO_SECRET_KEY` 사용
- 개발 환경에서는 기본값 제공, 프로덕션에서는 필수

#### DEBUG 설정 개선
- **변경 전:** `DEBUG = True` 하드코딩
- **변경 후:** 환경변수 `DEBUG`로 제어
- 기본값: `False` (안전한 기본값)

#### ALLOWED_HOSTS 유연성
- **변경 전:** base.py와 prod.py에 중복 설정
- **변경 후:** 환경변수 `DJANGO_ALLOWED_HOSTS`로 관리
- 쉼표로 구분하여 여러 호스트 설정 가능

**관련 파일:**
- [config/settings/base.py](config/settings/base.py)
- [config/settings/prod.py](config/settings/prod.py)
- [.env](.env)
- [.env.example](.env.example)

---

### 3. **도메인 설정 업데이트**
- **이전 도메인:** tc.o-r.kr
- **새 도메인:** techchang.com, www.techchang.com
- IP 주소 하드코딩 제거

**변경된 설정:**
- nginx.conf - server_name 업데이트
- .env 파일 - DJANGO_ALLOWED_HOSTS

---

### 4. **Nginx 설정 개선**
#### SSL 인증서 설정
- snakeoil 인증서 → Let's Encrypt 인증서로 변경
- certbot 자동 갱신 지원

#### 보안 헤더 강화
- HSTS (HTTP Strict Transport Security) 추가
- CSP (Content Security Policy) 유지
- 추가 보안 헤더 적용

#### 로그 파일명 변경
- `mysite_*.log` → `techchang_*.log`

#### 프록시 설정 최적화
- 하드코딩된 IP 주소 → `127.0.0.1` 사용

**관련 파일:**
- [nginx.conf](nginx.conf)

---

### 5. **환경변수 파일 재구성**
#### .env.example 개선
- 모든 필요한 환경변수 문서화
- 각 변수에 대한 설명 및 예시 추가
- 보안 설정 변수 추가

#### .env 파일 정리
- 불필요한 주석 제거
- 구조화된 섹션 (Django 기본, API 키, 게임, 보안)
- 개발 환경용 기본값 설정

**관련 파일:**
- [.env](.env)
- [.env.example](.env.example)

---

### 6. **배포 자동화**
#### 새 배포 스크립트 추가
- `deploy_new_instance.sh` - 새 인스턴스에 완전 자동 배포
- 10단계 자동화 프로세스
- 대화형 프롬프트로 사용자 입력 받기

**기능:**
1. 시스템 패키지 업데이트
2. 필수 패키지 설치
3. 프로젝트 디렉토리 생성
4. Python 가상환경 설정
5. Django 설정 및 마이그레이션
6. Gunicorn 서비스 등록
7. Nginx 설정
8. SSL 인증서 자동 발급

**관련 파일:**
- [deploy_new_instance.sh](deploy_new_instance.sh)

---

### 7. **문서화 개선**
#### 배포 가이드 작성
- 완전한 배포 프로세스 문서화
- 수동 배포 및 자동 배포 방법 모두 설명
- 트러블슈팅 섹션 추가
- 운영 및 유지보수 가이드 포함

**포함 내용:**
- EC2 인스턴스 설정
- 도메인 DNS 설정
- 자동/수동 배포 방법
- 배포 후 확인사항
- 트러블슈팅
- 보안 체크리스트
- 성능 최적화 팁

**관련 파일:**
- [DEPLOYMENT.md](DEPLOYMENT.md)

---

## URL 구조 변경

### 이전
```
/                    → 홈
/pybo/               → 커뮤니티 메인
/pybo/<id>/          → 게시글 상세
/pybo/games/         → 게임 센터
/pybo/baseball/      → 숫자야구
```

### 현재
```
/                    → 커뮤니티 메인 (홈)
/<id>/               → 게시글 상세
/games/              → 게임 센터
/baseball/           → 숫자야구
/common/             → 사용자 관리
/admin/              → 관리자 페이지
```

**장점:**
- URL이 더 간결하고 직관적
- SEO에 유리
- 전문적인 구조

---

## 마이그레이션 가이드 (기존 사이트 → 새 인스턴스)

### 1. 데이터 백업
```bash
# 기존 서버에서
cp db.sqlite3 db_backup_$(date +%Y%m%d).sqlite3
scp db.sqlite3 ubuntu@new-server:/home/ubuntu/projects/mysite/
```

### 2. 미디어 파일 복사
```bash
# 기존 서버에서
tar -czf media_backup.tar.gz media/
scp media_backup.tar.gz ubuntu@new-server:/home/ubuntu/projects/mysite/
```

### 3. 새 서버에서 배포
```bash
# 새 서버에서
cd /home/ubuntu/projects/mysite
./deploy_new_instance.sh
```

### 4. 데이터 복구
```bash
# 데이터베이스 복사 (배포 후)
cp db_backup_*.sqlite3 db.sqlite3

# 미디어 파일 압축 해제
tar -xzf media_backup.tar.gz

# Gunicorn 재시작
sudo systemctl restart gunicorn
```

### 5. DNS 전환
- 도메인 DNS를 새 서버 IP로 변경
- TTL이 짧으면 빠르게 전파됨 (5-30분)

---

## 테스트 체크리스트

배포 후 다음 항목들을 테스트하세요:

### 기본 기능
- [ ] 홈페이지 접속 (/)
- [ ] 로그인/로그아웃
- [ ] 회원가입
- [ ] 게시글 목록 조회
- [ ] 게시글 작성/수정/삭제
- [ ] 댓글 작성/수정/삭제
- [ ] 투표 기능

### 게임 기능
- [ ] 게임 센터 접속 (/games/)
- [ ] 숫자야구 플레이
- [ ] 2048 게임 플레이
- [ ] 지뢰찾기 플레이
- [ ] 리더보드 확인

### 관리 기능
- [ ] 관리자 페이지 접속 (/admin/)
- [ ] 사용자 관리
- [ ] 게시글 관리
- [ ] 커스텀 관리자 대시보드 (/common/admin/dashboard/)

### 보안
- [ ] HTTP → HTTPS 리다이렉트
- [ ] SSL 인증서 유효성
- [ ] CSRF 보호
- [ ] XSS 방지
- [ ] Rate Limiting

---

## 성능 비교

### 예상 개선사항
- **URL 길이 단축**: `/pybo/games/` → `/games/` (약 25% 단축)
- **SEO 점수**: 전문적인 URL 구조로 개선
- **유지보수성**: 환경변수 기반 설정으로 배포 간소화
- **보안성**: 환경변수화, SSL 강제, 보안 헤더 강화

---

## 알려진 이슈

현재 알려진 이슈는 없습니다.

---

## 향후 계획

### 단기 (1개월)
- [ ] 프로덕션 환경에서 안정성 모니터링
- [ ] 사용자 피드백 수집
- [ ] 성능 메트릭 수집

### 중기 (3개월)
- [ ] PostgreSQL 마이그레이션 (트래픽 증가 시)
- [ ] Redis 캐싱 도입
- [ ] CDN 연동 (정적 파일)

### 장기 (6개월+)
- [ ] 모바일 앱 개발 고려
- [ ] API 서버 분리
- [ ] 마이크로서비스 아키텍처 검토

---

## 개발자 노트

이번 개편의 주요 목표는 **취미 수준에서 실제 서비스 수준으로의 전환**이었습니다.

주요 성과:
1. ✅ 전문적인 URL 구조
2. ✅ 프로덕션 레벨 보안
3. ✅ 자동화된 배포 프로세스
4. ✅ 완전한 문서화

이제 TechChang 커뮤니티는 새 인스턴스에 언제든지 배포할 수 있으며, 확장 가능한 구조를 갖추었습니다.

---

**개편 완료일: 2024년 12월 16일**
