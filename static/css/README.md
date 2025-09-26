# CSS 아키텍처 가이드

## 📁 파일 구조

```
static/css/
├── variables.css    # CSS 변수 정의 (색상, 간격, 크기 등)  
├── base.css        # 기본 리셋 및 전역 스타일
├── components.css   # 재사용 가능한 UI 컴포넌트
├── utilities.css    # 유틸리티 클래스 모음
└── main.css        # 메인 통합 스타일시트
```

## 🎨 CSS 변수 시스템

### 색상 체계
- `--primary-color`, `--primary-light`, `--primary-dark`
- `--secondary-color`, `--secondary-light`, `--secondary-dark`
- `--text-color`, `--text-secondary`, `--text-muted`
- `--bg-primary`, `--bg-secondary`, `--bg-tertiary`

### 간격 시스템  
- `--spacing-xs` (0.25rem)
- `--spacing-sm` (0.5rem)
- `--spacing-md` (1rem)
- `--spacing-lg` (1.5rem)
- `--spacing-xl` (2rem)
- `--spacing-2xl` (3rem)

### 그림자 시스템
- `--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-xl`, `--shadow-2xl`

## 🧩 컴포넌트 시스템

### 네이밍 규칙 (BEM 방식)
```css
.component-name          /* 블록 */
.component-name__element /* 엘리먼트 */
.component-name--modifier /* 수정자 */
```

### 예시
```css
.card-enhanced                /* 기본 카드 */
.card-enhanced__header        /* 카드 헤더 */
.card-enhanced__body          /* 카드 바디 */
.card-enhanced--primary       /* 프라이머리 카드 */
```

## 🛠 확장 가능한 컴포넌트

### 1. 버튼 컴포넌트
```css
.btn-enhanced
.btn-enhanced--primary
.btn-enhanced--secondary  
.btn-enhanced--outline
.btn-enhanced--sm
.btn-enhanced--lg
```

### 2. 카드 컴포넌트  
```css
.card-enhanced
.card-enhanced__header
.card-enhanced__body
.card-enhanced__footer
```

### 3. 입력 필드
```css
.input-enhanced
.input-enhanced--error
.input-enhanced--success
```

### 4. 배지 시스템
```css
.badge-enhanced
.badge-enhanced--primary
.badge-enhanced--success
.badge-enhanced--danger
.badge-enhanced--outline
```

## 📱 반응형 시스템

### 브레이크포인트
- `--breakpoint-sm`: 576px
- `--breakpoint-md`: 768px  
- `--breakpoint-lg`: 992px
- `--breakpoint-xl`: 1200px
- `--breakpoint-xxl`: 1400px

### 반응형 유틸리티 클래스
```css
.xs\:d-none     /* 576px 이하에서 숨김 */
.sm\:d-block    /* 768px 이하에서 블록 */
.md\:flex-column /* 992px 이하에서 세로 배치 */
```

## 🎯 새로운 컴포넌트 추가 방법

### 1. components.css에 새 컴포넌트 추가
```css
/* 새로운 컴포넌트 */
.new-component {
  /* 기본 스타일 */
}

.new-component__element {
  /* 하위 요소 스타일 */
}

.new-component--modifier {
  /* 변형 스타일 */
}
```

### 2. 필요시 variables.css에 새 변수 추가
```css
:root {
  --new-component-color: #value;
  --new-component-size: 1rem;
}
```

### 3. utilities.css에 관련 유틸리티 추가
```css
.new-utility { property: value !important; }
```

## 🔧 유지보수 가이드

### CSS 변수 활용
- 하드코딩된 값 대신 CSS 변수 사용
- 일관된 디자인 시스템 유지
- 테마 변경 용이성 확보

### 컴포넌트 독립성
- 각 컴포넌트는 독립적으로 작동
- 전역 스타일에 의존하지 않음
- 재사용 가능한 구조

### 명명 규칙 준수
- BEM 방식의 일관된 네이밍
- 의미 있는 클래스명 사용
- 약어보다는 명확한 단어 사용

## 🌟 성능 최적화

### CSS 최적화
- 중복 스타일 제거
- 선택자 간소화
- 미사용 스타일 정리

### 로딩 최적화
- 필요한 CSS만 로드
- 인라인 스타일 최소화
- CSS 파일 압축

## 🎨 디자인 토큰

### 색상 토큰
```css
/* 브랜드 색상 */
--primary-color: #4a90e2;
--secondary-color: #f39c12;

/* 시맨틱 색상 */
--success-color: #27ae60;
--danger-color: #e74c3c;
--warning-color: #f1c40f;
--info-color: #3498db;
```

### 타이포그래피 토큰
```css
/* 폰트 크기 */
--font-xs: 0.75rem;
--font-sm: 0.875rem;
--font-base: 1rem;
--font-lg: 1.125rem;

/* 폰트 무게 */
--font-light: 300;
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;
```

## 📋 체크리스트

### 새 기능 추가 시
- [ ] CSS 변수 활용 확인
- [ ] 컴포넌트 독립성 확인  
- [ ] 반응형 디자인 적용
- [ ] 접근성 고려사항 확인
- [ ] 크로스 브라우저 호환성 확인

### 코드 리뷰 시
- [ ] 네이밍 규칙 준수 확인
- [ ] 중복 코드 제거 확인
- [ ] 성능 최적화 확인
- [ ] 문서화 업데이트 확인

이 가이드를 따라 확장 가능하고 유지보수 가능한 CSS 코드를 작성하세요! 🚀