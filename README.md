# 🚀 테크창 커뮤니티 플랫폼

**테크창**은 HRD, 데이터분석, 프로그래밍 전문가들이 모여 지식을 공유하는 현대적인 커뮤니티 플랫폼입니다.

## ✨ 주요 특징

### 📌 카테고리별 지식 공유
- **HRD**: 인적자원개발 및 교육 전문 지식
- **데이터분석**: 빅데이터, AI/ML, 비즈니스 인텔리전스
- **프로그래밍**: 개발 경험, 기술 트렌드, 코드 리뷰
- **자유게시판**: 자유로운 주제의 소통 공간
- **앨범**: 이미지 중심의 갤러리 공간

### � 커뮤니티 중심 설계
- **게시글 & 댓글**: 질문형 게시판이 아닌 자유로운 소통 구조
- **이미지 첨부**: 게시글과 댓글에 이미지 업로드 지원
- **사용자 프로필**: 닉네임 시스템과 프로필 이미지
- **추천 시스템**: 유용한 콘텐츠 추천 기능
- **검색 & 정렬**: 효율적인 콘텐츠 탐색

## 🛠️ 기술 스택

### Backend
- **Django 5.2.6**: 안정적인 웹 프레임워크
- **Python 3.10+**: 현대적인 Python 버전
- **SQLite**: 개발용 데이터베이스
- **Pillow**: 이미지 처리

### Frontend
- **Bootstrap 5.3.2**: 반응형 UI 프레임워크
- **Font Awesome 6.0.0**: 아이콘 라이브러리
- **Custom CSS**: 테크창 브랜드 디자인
- **Vanilla JavaScript**: 인터랙티브 기능

### 배포 & 인프라
- **Gunicorn**: WSGI 서버
- **Nginx**: 리버스 프록시
- **systemd**: 서비스 관리
- **Let's Encrypt**: SSL/TLS 인증서

## 🏗️ 프로젝트 구조

```
techwindow/
├── config/                 # Django 설정
│   ├── settings/
│   │   ├── base.py        # 기본 설정
│   │   ├── local.py       # 개발 환경
│   │   └── prod.py        # 프로덕션 환경
│   └── urls.py            # 메인 URL 설정
├── common/                 # 사용자 인증 앱
│   ├── models.py          # 프로필 모델
│   ├── views.py           # 로그인/회원가입
│   └── templatetags/      # 템플릿 필터
├── pybo/                   # 커뮤니티 메인 앱
│   ├── models.py          # 게시글, 댓글, 카테고리
│   ├── views/             # 분할된 뷰 파일들
│   ├── forms.py           # Django 폼
│   ├── templatetags/      # 커스텀 필터
│   └── management/        # 관리 명령어
├── templates/              # 템플릿 파일
│   ├── base.html          # 기본 레이아웃
│   ├── navbar.html        # 네비게이션
│   ├── pybo/              # 커뮤니티 템플릿
│   └── common/            # 인증 템플릿
├── static/                 # 정적 파일
│   ├── bootstrap.min.css
│   ├── bootstrap.min.js
│   └── style.css
├── media/                  # 업로드 파일
└── requirements.txt        # Python 의존성
```

## � 주요 기능

### 커뮤니티 기능
- ✅ **게시글 작성/조회**: 카테고리별 게시글 관리
- ✅ **댓글 시스템**: 게시글에 댓글 작성/삭제 
- ✅ **추천 시스템**: 게시글과 댓글에 추천/비추천
- ✅ **검색 기능**: 제목, 내용, 작성자 검색
- ✅ **페이지네이션**: 효율적인 페이지 분할

### 사용자 관리
- ✅ **회원가입/로그인**: Django 기본 인증 시스템
- ✅ **프로필 관리**: 프로필 이미지 업로드
- ✅ **작성글 관리**: 내가 쓴 글/댓글 조회
- ✅ **권한 관리**: 작성자만 수정/삭제 가능

### 관리 기능
- ✅ **카테고리 관리**: 게시판 카테고리 생성/관리
- ✅ **관리자 페이지**: Django Admin 인터페이스
- ✅ **이미지 업로드**: 프로필 이미지 관리

## �🚀 빠른 시작

### 개발 환경 설정

1. **저장소 클론**
   ```bash
   git clone <repository-url>
   cd mysite
   ```

2. **Python 가상환경 생성**
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # Linux/macOS
   source venv/bin/activate
   ```

3. **의존성 설치**
   ```bash
   pip install django pillow
   ```

4. **데이터베이스 마이그레이션**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

5. **관리자 계정 생성 (선택사항)**
   ```bash
   python manage.py createsuperuser
   ```

6. **개발 서버 실행**
   ```bash
   python manage.py runserver
   ```

7. **브라우저에서 접속**
   - http://localhost:8000

## 🌐 배포 가이드

### 필요한 설정

1. **환경변수 설정 (`settings.py` 수정)**
   ```python
   # 프로덕션 환경에서 설정 필요
   DEBUG = False
   ALLOWED_HOSTS = ['yourdomain.com', 'www.yourdomain.com']
   
   # 정적 파일 설정
   STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
   MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
   ```

2. **정적 파일 수집**
   ```bash
   python manage.py collectstatic
   ```

3. **데이터베이스 설정**
   - SQLite (개발용): 기본 설정으로 사용 가능
   - PostgreSQL/MySQL (프로덕션 권장): settings.py에서 데이터베이스 설정 변경

### 웹 서버 배포 (예: Apache/Nginx)

1. **WSGI 설정**
   ```python
   # wsgi.py 파일이 이미 config/ 디렉토리에 있음
   # 웹 서버에서 이 파일을 참조하도록 설정
   ```

2. **정적 파일 서빙**
   ```
   # 웹 서버에서 /static/ 경로를 staticfiles/ 디렉토리로 설정
      # /media/ 경로를 media/ 디렉토리로 설정
   ```

## 🔧 관리 명령어

### Django 기본 명령어
```bash
# 개발 서버 실행
python manage.py runserver

# 마이그레이션 생성 및 적용
python manage.py makemigrations
python manage.py migrate

# 관리자 계정 생성
python manage.py createsuperuser

# Django 쉘 실행
python manage.py shell

# 정적 파일 수집
python manage.py collectstatic
```

## 🔒 보안 기능

- **CSRF 보호**: Django 기본 CSRF 토큰 사용
- **XSS 방지**: 템플릿 자동 이스케이핑
- **SQL 인젝션 방지**: Django ORM 사용
- **파일 업로드 보안**: 이미지 파일 타입 검증
- **사용자 인증**: Django 내장 인증 시스템
- **권한 관리**: 작성자 권한 확인

## 🤝 기여하기

1. Fork 프로젝트
2. Feature 브랜치 생성 (`git checkout -b feature/AmazingFeature`)
3. 변경사항 커밋 (`git commit -m 'Add some AmazingFeature'`)
4. 브랜치에 Push (`git push origin feature/AmazingFeature`)
5. Pull Request 생성

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

## 📞 문의

프로젝트 관련 문의사항이 있으시면 이슈를 생성해주세요.

---

**TechWindow Community Platform v2.0.0** - Django 기반 현대적인 커뮤니티 플랫폼 ✨
   sudo cp mysite.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable mysite
   ```

2. **SSL 인증서 설정** (Let's Encrypt)
   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   ```

3. **서비스 시작**
   ```bash
   sudo systemctl start mysite
   sudo systemctl start nginx
   ```

## 🔧 개발 도구

### 개발 스크립트 사용법

```bash
./dev.sh setup    # 개발 환경 초기 설정
./dev.sh run      # 개발 서버 실행
./dev.sh test     # 테스트 실행
./dev.sh shell    # Django 쉘 실행
./dev.sh clean    # 캐시 파일 정리
```

### 관리 명령어

```bash
# 카테고리 초기화
python manage.py initialize_categories --force

# 테스트 데이터 생성 (있을 경우)
python manage.py loaddata fixtures/sample_data.json
```

## 📊 성능 최적화

### 정적 파일 최적화
- **Gzip 압축**: CSS, JS, 폰트 파일 압축
- **브라우저 캐싱**: 1년 캐시 설정
- **CDN 준비**: 정적 파일 CDN 연동 가능

### 이미지 최적화
- **업로드 제한**: 5MB 제한
- **보안 검증**: 이미지 파일 유형 검증
- **자동 압축**: 필요시 PIL 기반 압축 가능

### 데이터베이스 최적화
- **인덱싱**: 자주 조회되는 필드에 인덱스 적용
- **쿼리 최적화**: select_related, prefetch_related 사용
- **캐싱**: Django 캐싱 프레임워크 활용 가능

## 🔒 보안 기능

- **CSRF 보호**: 폼 보안
- **XSS 방지**: 템플릿 자동 이스케이핑
- **SQL 인젝션 방지**: Django ORM 사용
- **파일 업로드 보안**: 파일 타입 검증
- **HTTPS 강제**: 프로덕션 환경 SSL
- **보안 헤더**: HSTS, X-Frame-Options 등

### 보안 미들웨어 조정
환경 변수로 보안 미들웨어 민감도를 손쉽게 조절할 수 있습니다. (괄호 안은 기본값)

- `RATE_LIMIT_REQUESTS` (300): IP당 시간당 허용 요청 수
- `RATE_LIMIT_WINDOW` (3600): 요청 제한 카운트 초기화까지의 초 단위 시간
- `DDOS_THRESHOLD` (120): 60초 안에 해당 횟수를 넘으면 DDoS 의심으로 기록
- `BLOCK_DURATION` (180): 차단 지속 시간(초)
- `SUSPICION_SCORE_THRESHOLD` (10): 의심 점수 누적 시 차단 임계치
- `PROTECTED_PATH_ATTEMPTS_LIMIT` (20): 로그인 없이 보호 경로 접근 가능한 횟수
- `SUSPICIOUS_USER_AGENT_PATTERNS`: 콤마로 구분된 의심 User-Agent 패턴 목록 (정규식 지원)
- `TRUSTED_USER_AGENT_PATTERNS`: 허용할 User-Agent 패턴 목록 (예: `curl,python-requests`)
- `TRUSTED_HEALTHCHECK_PATHS`: 헬스체크 등 신뢰할 경로 목록 (예: `/health,/status`)

## 🧪 테스트

### 테스트 실행
```bash
# 전체 테스트
python manage.py test

# 특정 앱 테스트
python manage.py test pybo

# 커버리지 포함 테스트 (coverage 설치 필요)
coverage run --source='.' manage.py test
coverage report
coverage html
```

## 📝 API 문서

추후 Django REST Framework 도입 시 API 문서가 제공될 예정입니다.

## 🤝 기여하기

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📞 지원 및 문의

- **이슈 리포팅**: GitHub Issues
- **이메일**: [프로젝트 이메일]
- **문서**: [위키 링크]

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

## 🗺️ 테크창 비전 로드맵

### 🎆 Phase 1: 커뮤니티 고도화 (Q4 2024)
- [ ] 🔔 실시간 알림 시스템
- [ ] 🔍 고급 검색 엔진 (ElasticSearch)
- [ ] 🏷️ 전문 태그 시스템
- [ ] 🏅 전문가 인증 배지
- [ ] 📊 실시간 질문-답변 매칭

### 🚀 Phase 2: AI 통합 플랫폼 (Q1 2025)
- [ ] 🤖 AI 답변 어시스턴트
- [ ] 📱 모바일 앱 (네이티브)
- [ ] 🌍 다국어 지원 (KR/EN)
- [ ] 📈 비즈니스 대시보드
- [ ] 💼 기업 전용 솔루션

### 🌐 Phase 3: 글로벌 확장 (Q2 2025)
- [ ] 📺 온라인 웨비나 플랫폼
- [ ] 📄 전문 자격증 연동
- [ ] 🔗 기업 HRD 시스템 연동
- [ ] 💰 프리미엄 멤버십 서비스

---

💡 **Tip**: 개발 중 문제가 발생하면 `./dev.sh help`를 실행하여 도움말을 확인하세요! 본 문서는 테마 구조, 변경/추가 방법, 프론트–백엔드 연동 흐름을 정리합니다.

## 기술 스택
- Django 5.x
- Bootstrap 5.3
- Font Awesome 6.x
- Vanilla JS (IIFE + fetch)
- CSS Custom Properties (Design Tokens)

## 디렉터리 구조 (발췌)
```
static/
  css/
    variables.css   # 공통 불변/기본 토큰 (색상 팔레트, spacing, shadow 등)
    themes.css      # 개별 테마별 변수 override (.theme-light / .theme-dark / .theme-highcontrast)
  style.css         # 컴포넌트 & 레이아웃 스타일 (토큰 참조 중심)
common/
  models.py         # Profile(theme) 모델
  views.py          # save_theme (POST) API
  context_processors.py # theme_class 주입
  migrations/       # Profile 초기 마이그레이션
templates/
  base.html         # body 클래스, 초기 테마 적용 스크립트, setTheme() 정의
  navbar.html       # 테마 선택 드롭다운
```

## 테마 아키텍처
1. `variables.css` : 모든 테마가 공유하는 디자인 토큰. (색상 계층 베이스, spacing, radius, shadow, typography 등)
2. `themes.css` : 각 테마가 override 할 토큰(표면 색, 텍스트 컬러, gradient 등)을 `.theme-<name>` 스코프로 정의.
3. `style.css` : 실제 컴포넌트(버튼, 카드, 테이블, 폼, 페이지네이션 등)는 가능한 한 직접 색상값 대신 `var(--token)` 사용.
4. 초기 로딩: 서버 측 context processor 가 body에 `theme-<value>` 클래스를 렌더 → FOUC 최소화.
5. 클라이언트: JS가 localStorage / cookie 값을 읽어 재적용 (로그인 사용자는 서버 동기화 fetch).

## 저장 우선순위 (Theme Resolution Order)
1. 서버 템플릿 렌더 시: 사용자 Profile.theme (로그인) → `site_theme` 쿠키 → 기본값(light)
2. DOM 로드 직후 JS: localStorage(`site-theme`) → 쿠키(`site_theme`) → body 기본 클래스 유지
3. 사용자가 테마 선택: `setTheme(name)` → body 클래스 교체, localStorage + 쿠키 저장, 로그인 시 `/common/theme/` 호출

## 서버 API
### POST `/common/theme/`
- 파라미터: `theme=light|dark|highcontrast`
- 로그인 사용자: `Profile.theme` 업데이트
- 비로그인: 쿠키만 설정
- 응답(JSON): `{ "status": "ok", "theme": "dark" }`
- 실패 시: 400 + `{ "status": "error", "error": "invalid theme" }`

## JavaScript 흐름 (발췌)
```js
(function(){
  const KEY='site-theme';
  const IS_AUTH = "{{ user.is_authenticated|yesno:'true,false' }}" === 'true';
  // ... apply(theme) 정의 ...
  window.setTheme = function(theme){
     // body 클래스 교체 + localStorage + cookie 기록
     if(IS_AUTH){
        fetch('/common/theme/',{method:'POST', headers:{'X-CSRFToken': csrftoken}, body:new URLSearchParams({theme})});
     }
  }
})();
```

## 새 테마 추가 절차
1. `themes.css` 에 블록 추가:
```css
.theme-solarized {
  --bg-color: #fdf6e3;
  --text-color: #073642;
  --panel-color: #fffdf5;
  /* 필요한 token override 추가 */
}
```
2. Django `Profile` 모델에 선택지 추가 (선택적 – 서버 유지 필요 시):
```python
class Profile(models.Model):
    THEME_SOLARIZED = 'solarized'
    THEME_CHOICES = [
       # ...기존...
       (THEME_SOLARIZED, 'Solarized'),
    ]
```
3. 마이그레이션 생성 & 적용:
```cmd
python manage.py makemigrations common
python manage.py migrate
```
4. `navbar.html` 드롭다운에 버튼:
```html
<li><button class="dropdown-item" type="button" onclick="setTheme('solarized')">솔라라이즈드</button></li>
```
5. (선택) 기본 사용자 프로필 초기값 변경 시 `default='light'` 조정 또는 데이터 마이그레이션.

## 접근성 / QA 체크 리스트
- 대비(Contrast): 고대비 테마에서 텍스트 대비 (>= WCAG AA 4.5:1) 확인
- 포커스 표시: 키보드 탐색 시 outline 유지 여부
- 애니메이션 감소: 필요 시 `prefers-reduced-motion` media query 추가 고려
- FOUC: 초기 로드 시 테마 깜빡임 발생 여부(네트워크 Throttling으로 점검)
- 다크/라이트 변환 후 localStorage, cookie, 서버(Profile) 모두 일치 여부

## 성능 팁
- 가능하면 컴포넌트별 세부 색상 하드코딩보다 토큰 재사용 → 재디자인 비용 절감
- 중복 gradient 정의는 토큰화(예: `--gradient-card`) 후 테마별 override 고려
- CSS 파일 HTTP/2 환경에서는 분리가 캐싱 효율 향상, 장기적으로 SCSS 빌드 파이프라인 도입 가능

## 향후 확장 아이디어
- 사용자 설정 페이지(Form)에서 서버 렌더 기반 테마 변경 (JS 의존 제거 옵션)
- `prefers-color-scheme` 를 초기 기본값 후보로 사용 후 사용자 선택 시 고정
- 폰트 사이즈/간격 커스터마이징 (가독성 향상 프로필 옵션)
- 레이아웃 모드 (compact / comfortable) 추가

## 개발 메모
- Profile 자동 생성: `signals.py` (User post_save) 활용
- 미로그인 사용자는 서버 DB 접근 없이 쿠키 + localStorage 로 충분
- 서버 응답 캐싱 시 Vary 헤더에 Authorization/Session 고려 (현재 단순 페이지 렌더 수준)

## 실행 (로컬)
```cmd
python manage.py migrate
python manage.py runserver
```

## 라이선스
학습/개인용 예제 기반 프로젝트 (명시적 라이선스 미설정 시 내부 사용 전제)

---
문의나 개선 아이디어는 이 README 하단에 주석 형태로 메모를 추가하거나 Issue(TODO 관리 체계 도입 시)로 전환하세요.
