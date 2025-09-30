# 🚀 테크창 (TechWindow) - Technology + HRD 통합 플랫폼

**테크창**은 Technology와 HRD(Human Resource Development)를 결합한 혁신적인 지식 공유 플랫폼입니다. 
데이터분석, 프로그래밍, 인적자원개발 전문가들이 모여 실무 경험과 전문 지식을 나누는 프리미엄 커뮤니티입니다.

## ✨ 테크창만의 특별 기능

### 🎆 전문 영역별 지식 허브
- **HRD 전문관**: 인재개발, 교육 커리큘럼, 조직 발전 노하우
- **데이터분석 마스터**: 빅데이터, AI/ML, 비즈니스 인텔리전스 전문 지식
- **프로그래밍 구루**: 최신 기술 트렌드, 실무 개발 경험, 코드 리뷰

### 🏆 프리미엄 커뮤니티 기능
- **실시간 Q&A**: 빠른 문제 해결과 전문가 답변
- **🖼️ 비주얼 콘텐츠**: 다이어그램, 스크린샷, 코드 첨부
- **🎆 전문가 네트워킹**: 업계 리더들과의 직접 소통
- **📝 지식 아카이브**: 체계적 자료 수집과 사례 연구
- **⭐ 품질 관리**: 전문가 검증 및 커뮤니티 평가 시스템

## 🛠️ 테크창 기술 아키텍처

### 🏆 엔터프라이즈 Backend
- **Django 5.2.6**: 엔터프라이즈급 웹 프레임워크
- **Python 3.10+**: AI/ML 통합 지원 언어
- **PostgreSQL**: 프로덕션 데이터베이스 (개발: SQLite)
- **Gunicorn**: 고성능 WSGI 서버
- **Redis**: 캐싱 및 세션 저장소

### 🎨 모던 Frontend
- **Bootstrap 5**: 반응형 UI 프레임워크
- **Font Awesome 6**: 프로페셔널 아이콘 세트
- **Custom CSS**: 테크창 브랜드 디자인
- **Vanilla JavaScript**: 경량 인터랙션 라이브러리

### 🚀 클라우드 인프라
- **AWS/GCP**: 글로벌 클라우드 배포
- **Nginx**: 고성능 리버스 프록시
- **Docker**: 컨테이너 오케스트레이션
- **Let's Encrypt**: 무료 SSL/TLS 인증서
- **Monitoring**: 성능 및 에러 모니터링

## 🏗️ 테크창 프로젝트 구조

```
techwindow/
├── config/                 # Django 설정
│   ├── settings/
│   │   ├── base.py        # 기본 설정
│   │   ├── local.py       # 개발 환경
│   │   └── prod.py        # 프로덕션 환경
│   ├── urls.py            # URL 라우팅
│   └── wsgi.py            # WSGI 설정
├── pybo/                  # 메인 앱
│   ├── models.py          # 데이터 모델
│   ├── forms.py           # 폼 정의
│   ├── views/             # 뷰 로직
│   ├── templates/         # 템플릿
│   └── management/        # 관리 명령
├── common/                # 공통 기능 (인증, 프로필)
├── static/                # 정적 파일
├── media/                 # 업로드된 파일
├── templates/             # 공통 템플릿
├── requirements.txt       # Python 의존성
├── nginx.conf            # Nginx 설정
├── gunicorn.conf.py      # Gunicorn 설정
├── mysite.service        # systemd 서비스
├── deploy.sh             # 배포 스크립트
└── dev.sh                # 개발 도구
```

## 🚀 빠른 시작

### 개발 환경 설정

1. **저장소 클론**
   ```bash
   git clone https://github.com/inucreativehrd21/Django-Study.git
   cd Django-Study
   ```

2. **개발 환경 자동 설정**
   ```bash
   # Linux/macOS
   chmod +x dev.sh
   ./dev.sh setup
   
   # Windows (Git Bash)
   bash dev.sh setup
   ```

3. **개발 서버 실행**
   ```bash
   ./dev.sh run
   ```

4. **브라우저에서 접속**
   - https://tc.o-r.kr

### 수동 설정 (고급 사용자)

1. **가상환경 생성 및 활성화**
   ```bash
   python -m venv venv
   
   # Linux/macOS
   source venv/bin/activate
   
   # Windows
   venv\Scripts\activate
   ```

2. **의존성 설치**
   ```bash
   pip install -r requirements.txt
   ```

3. **환경변수 설정**
   ```bash
   cp .env.example .env
   # .env 파일을 편집하여 환경에 맞게 설정
   ```

4. **데이터베이스 마이그레이션**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

5. **카테고리 초기화**
   ```bash
   python manage.py initialize_categories --force
   ```

6. **슈퍼유저 생성**
   ```bash
   python manage.py createsuperuser
   ```

7. **정적 파일 수집**
   ```bash
   python manage.py collectstatic
   ```

## 🌐 프로덕션 배포

### 자동 배포 (권장)

```bash
# 서버에서 실행
sudo chmod +x deploy.sh
sudo ./deploy.sh production
```

### 수동 배포

1. **서버 설정**
   ```bash
   # Nginx 설정 복사
   sudo cp nginx.conf /etc/nginx/sites-available/mysite
   sudo ln -s /etc/nginx/sites-available/mysite /etc/nginx/sites-enabled/
   
   # systemd 서비스 등록
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
