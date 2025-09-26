# PyBo 커뮤니티 (확장형 테마 시스템)

## 개요
PyBo 는 Django 기반 Q&A 커뮤니티 애플리케이션으로, 확장 가능한 디자인 토큰 / 다중 테마(light / dark / highcontrast) 시스템을 갖추고 있습니다. 본 문서는 테마 구조, 변경/추가 방법, 프론트–백엔드 연동 흐름을 정리합니다.

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
