# 연구실 그래픽 업그레이드 인계 (Codex · gpt-6-astra 작업용)

작성 2026-10-31. 대상은 다음 세션에서 이 작업을 이어받는 Codex예요. 이 문서만 읽고 시작할 수 있게 썼어요. 사용자의 최종 목표는 **제안서 8쪽의 연구실 이미지와 같은 수준의 그래픽을 /lab/에 구현**하는 거예요.

## 1. 한눈에 보기

| 항목 | 내용 |
|---|---|
| 문제 | 지금 3D 연구실은 상자·구·원통을 조합한 장면이라 제안서 이미지보다 훨씬 단순해 보여요 |
| 원인 | 제안서 이미지는 3D 렌더가 아니라 **AI 이미지 생성물**이에요. 코드로 메시를 더 다듬어도 따라잡기 어려워요 |
| 권장 경로 | **A. 생성 이미지 레이어 합성(2.5D)**. 방 배경판 1장 + 연구원 8명 스프라이트 + HTML 핫스팟·SVG 흐름선 |
| 대안 | B. Blender 베이크 glTF + Three.js (품질 상한은 높지만 사람 모델이 저폴리 스타일로 바뀌고 작업량이 커요) |
| 하지 않을 것 | 현재 `lab-scene.js`의 프리미티브 모델링 개선, 운영 배포, git push, DB 변경 |
| 먼저 할 일 | 이미지 생성 스파이크(섹션 6의 S1). 합격 못 하면 B로 갈지 사용자에게 보고하고 멈춰요 |
| 사용자 확인이 필요한 결정 | 섹션 10 |

## 2. 현재 상태 진단

- 구현: [lab-scene.js](../static/js/lab-scene.js) 444줄. Three.js 0.187.0(`static/vendor/three/`)으로 박스·구·원통·`limb()`를 조합해 방·가구·사람 8명을 만들어요. 외부 모델·텍스처는 없어요.
- 성능 기록(구현 기록 문서): PC 119 draw call·삼각형 92,570, 모바일 경량 47·48,338. 새 정적 자산 약 2.26MB(비압축).
- 화면: [output/lab-upgrade-desktop.png](../output/lab-upgrade-desktop.png) (현재), [output/pdf/assets/lab-studio-concept.png](../output/pdf/assets/lab-studio-concept.png) (목표, 1536×1024).
- 격차의 구체적 항목(비교해서 직접 확인해 주세요)
  - 재질: 목표는 대리석·브러시드 스틸·리브드 글라스·카펫 질감과 부드러운 간접광. 현재는 단색 `MeshStandardMaterial`과 단순 그림자.
  - 사람: 목표는 옷 주름·손·표정·의자 자세가 있는 실사형 인물. 현재는 구와 캡슐 조합에 얼굴 텍스처 한 장.
  - 소품: 목표는 서가의 패널·액자·보드, 모니터 화면의 도판, 화분·벤치·구형 오브제. 현재는 일부만 단순화.
  - 연출: 목표는 서가→테이블→발행대로 이어지는 인디고 빛줄기. 현재는 바닥의 점선 몇 개.
- 이 구조 자체는 유지해도 좋아요: 실제 상태 연동([lab-studio.js](../static/js/lab-studio.js)), 8명 이름 버튼, 회의 재생, 접근성 계약. 교체 대상은 **장면 렌더 계층**뿐이에요.

## 3. 경로 비교와 판단

| | A. 생성 이미지 레이어 합성 (권장) | B. Blender 베이크 + glTF | C. 현재 코드 개선 |
|---|---|---|---|
| 제안서와의 근접도 | 높음(같은 종류의 이미지) | 중간~높음, 사람은 스타일화 | 낮음 |
| 자유 회전 | **없음**(고정 등각 시점) | 있음(제한 각도 권장) | 있음 |
| 초기 전송량 | 약 0.3~0.8MB(WebP) | 1~3MB(메시+텍스처) | 약 2.3MB 비압축 |
| 모바일 | WebGL 불필요, "3D 시작" 단계 없이 바로 표시 | WebGL 필요, 발열·성능 부담 | 같음 |
| 위험 | 이미지 일관성(8명·카메라각), 투명 배경 추출 | 로컬에 Blender 없음, 코드로 방을 모델링하면 지금 결과와 같은 문제가 반복될 수 있음 | 시간만 쓰고 결과가 비슷함 |
| 판단 | 1순위 | A 스파이크 실패 시 2순위 | 하지 않아요 |

판단 근거: 사용자가 원하는 것은 "제안서 이미지 같은 그래픽"이고, 그 이미지는 생성 래스터예요. 같은 도구로 레이어를 만들면 가장 가깝고 가벼워요. 대가는 자유 회전을 잃는 거예요. 이 대가는 섹션 10에서 사용자가 확정해야 해요.

## 4. Codex 도구 점검 (이 PC에서 직접 확인한 사실)

확인한 것:
- `codex-cli 0.166.0`. `~/.codex/config.toml` 기본 모델은 `gpt-6.1-sol`(xhigh)이라, **Astra로 쓰려면 직접 지정**해야 해요: `codex -m gpt-6-astra -c model_reasoning_effort=high`.
- `models_cache.json`: `gpt-6-astra`(설명 "Frontier intelligence for the most demanding work", 입력 text·image, 추론 low~ultra). 같은 목록에 `gpt-6.1-sol`·`gpt-6.1-terra`·`gpt-6-luna` 등이 있어요.
- `codex features list`: `image_generation`, `view_image`, `browser_use`, `in_app_browser`, `computer_use`, `plugins` 모두 stable·켜짐. `~/.codex/generated_images/`에 이전 세션의 생성 PNG가 있어요.
- 로컬 환경: Node v22.20.0, npm, Python 3.10(`py -3.10`, Pillow 10.2.0), git-lfs.
- 설치되지 않음: **Blender, ImageMagick, cwebp, ffmpeg, gltf-transform**. 필요하면 사용자 승인 후 설치하거나 Pillow·Node 패키지로 대체해요.
- 기존 UI 스킬: `.agents/skills/techchang-ui` → `.claude/skills/techchang-ui/SKILL.md`, `design-guardrails`를 먼저 읽어요.

확인하지 못한 것(첫 작업에서 실험으로 확인해요):
- 이미지 생성 도구가 **어떤 모델로** 만들고 최대 해상도·투명 배경(alpha)을 지원하는지. 제안서 컨셉 이미지가 이 도구의 산출물인지도 확인하지 못했어요.
- 참조 이미지를 넣어 같은 카메라·같은 인물을 반복 생성할 때의 일관성.

역할 구분: Astra는 계획·좌표 계산·합성 코드·QA 판정(`view_image`)을 맡고, 이미지는 `image_generation` 도구가 만들어요. Astra가 직접 그림을 그린다고 가정하지 않아요.

## 5. 오픈소스·레포 검토

라이선스는 내려받는 시점에 해당 팩의 LICENSE 파일로 다시 확인하고 `docs/lab-graphic-credits.md`에 기록해요.

| 자원 | 용도 | 상태 |
|---|---|---|
| three.js (MIT) | 이미 `static/vendor/three/`에 고정. 경로 A에서는 폴백으로만 유지 | 확인됨(구현 기록) |
| Pillow(설치됨), sharp(npm, 선택) | WebP 변환·크롭·알파 처리 | 사용 가능 |
| rembg 또는 유사 배경 제거 도구 | 스프라이트 알파 추출(투명 배경 생성이 안 될 때) | **미검증**, 설치 전 라이선스·모델 가중치 약관 확인 |
| glTF-Transform CLI | 경로 B에서 meshopt·KTX2 압축(`optimize`, `meshopt`, `uastc`/`etc1s`) | npm readme로 명령 존재 확인. 정확한 플래그는 설치 후 `--help`로 확인 |
| Blender(GPL, 설치 필요) | 경로 B의 베이크·내보내기. glTF에는 라이트맵 슬롯이 없어 emissive 슬롯에 담았다가 three.js에서 `lightMap`으로 바꾸거나 AO로 내보내는 우회가 통용돼요 | 포럼 자료 기준, 현행 버전에서 재검증 필요 |
| Quaternius Universal Animation Library | 경로 B의 애니메이션·캐릭터 | CC0, 단 무료판은 일부 구성(45개 안팎 애니메이션)이고 전체·.blend는 유료. 무료판에 쓸 만한 인물 모델이 있는지는 **확인 못 함** |
| KayKit 캐릭터 팩, Kenney 캐릭터 | 경로 B의 저폴리 인물 | KayKit CC0(원본 재판매 금지 요청). Kenney 번들은 라이선스 미확인 |
| **Ready Player Me** | — | **사용 금지.** 2026-01-31 공개 서비스 종료 보도가 다수 |
| LimeZu 픽셀 에셋 | — | 기존 문서에 재배포·3D 전환을 하지 않기로 기록. 쓰지 않아요 |
| Mixamo, VRoid/three-vrm, MakeHuman | 경로 B 후보 | 약관·재배포 조건 **미검증**. 쓰려면 먼저 확인 |

가져올 만한 완성형 "연구실 그래픽" 레포는 찾지 못했어요. 이 작업의 핵심 자산은 오픈소스가 아니라 생성 이미지와 합성 코드예요.

## 6. 경로 A 작업 계획

### 6-0. 합성 구조

```text
.tc-ls-viewport (고정 비율, contain)
 ├─ plate.webp          사람이 없는 방 배경판 (제안서 이미지와 같은 등각 시점)
 ├─ people/<key>.webp   연구원 8명 투명 스프라이트, layout.json의 좌표·크기·발 위치로 배치
 ├─ <svg> 흐름선         서가 → 회의 테이블 → 발행대 경로, stroke-dashoffset 애니메이션
 ├─ 핫스팟 버튼 8개       스프라이트 위치 기반, 포커스·hover 링과 이름표
 └─ 상태 오버레이         활성 연구원 링 펄스, 비활성 약한 dim, 회의 발언자 강조
```

- 시점·크기 기준은 제안서 이미지(1536×1024). 화면 표시 폭이 약 800px이므로 배경판은 가로 1536~1800px이면 2x에 가까워요.
- 배경이 흰색인 이미지는 CSS `mix-blend-mode: multiply`로 카드 배경(`#f4f5f8` 계열)에 자연스럽게 얹을 수 있어요. 시험해 보고 어색하면 카드 배경을 흰색으로 맞춰요.
- 이미지 안에 **글자를 넣지 않아요.** 생성 이미지의 한글·영문은 깨져요. 이름표·안내는 전부 HTML이에요.

### 6-1. 연구원 배치(제안서의 9명 → 8명)

제안서 이미지는 9명이에요. 서가 2명을 1명으로 줄여 8명에 맞춰요.

| 자리 | 연구원 | 근거 |
|---|---|---|
| 서가 | 하경(`checker`, 검증관) | 자료 대조 역할 |
| 회의 테이블 4명(앉기 3·서기 1) | 은혜(`lead`), 예원(`critic`), 재원(`charter`), 승현(`editor`, 서 있는 사람) | 기존 `homes` 좌표의 자리 관계 |
| 책상 3석 | 한빈(`hrd`), 수정(`data`), 윤성(`coding`) | 칼럼니스트 3인 |
| 발행대 | 사람 없음, 종이 더미와 빛줄기 끝 | 제안서와 동일 |

외모는 [office/agents.py](../office/agents.py)의 `sprite`(머리 색·모양·피부색) 값을 따라요. 안경은 기존 모델대로 `editor`·`coding`·`checker`만 써요. **성별·나이·인종을 이름에서 추측하지 않아요**(스프라이트 값에 없으면 중립적으로 두고 8명의 머리·옷으로 구분해요). 옷은 사이트 팔레트(크림·차콜·인디고 포인트) 안에서 8명이 구분되게 해요. 실존 인물·유명인 닮은꼴·브랜드 로고는 쓰지 않아요.

### 6-2. 단계와 합격 게이트

| 단계 | 할 일 | 산출물 | 합격 기준(통과 못 하면 다음으로 가지 않아요) |
|---|---|---|---|
| S0 | 컨셉 이미지에서 카메라각·소실 방향·바닥 타일 기울기·사람 키 비율을 측정해 메모. 작업 전 `git status`로 다른 변경 보존 확인 | `scratchpad/` 메모 | 측정값이 문서화됨 |
| S1 **스파이크(타임박스 약 1시간)** | ① 사람 없는 방 배경판 4후보 ② 투명(또는 단색 키) 배경의 연구원 1명을 같은 카메라로 ③ 같은 인물을 3회 재생성해 일관성 확인 ④ 알파 추출 | 후보 이미지, 실험 기록(프롬프트·도구 옵션·해상도) | 배경판이 제안서와 같은 질감 수준, 인물 접지·알파 가장자리 깨끗함, 같은 인물 3회가 같은 사람으로 보임. **실패하면 중단하고 사용자에게 B 전환 여부를 물어요** |
| S2 | 배경판 확정. 스스로 `view_image`로 8개 항목 체크리스트(섹션 8) 채점 후 상위 2안을 사용자에게 제시 | `static/img/lab/plate/plate.webp`(+모바일용 축소판) | 사용자 승인 |
| S3 | 8명 스프라이트 생성·알파 정리·발 위치 기준 좌표 산출 | `static/img/lab/plate/people/<key>.webp`, `layout.json` | 8명이 서로 구분됨, 손·얼굴 깨짐 없음, 배경판 위에서 접지 그림자 자연스러움 |
| S4 | 어댑터 `static/js/lab-plate.js` 구현, 템플릿·CSS·문구 수정(섹션 7) | 코드 | 기존 상호작용 전부 동작 |
| S5 | 검증(섹션 9) 후 구현 기록 문서에 결과 추가 | 스크린샷, 측정 | 검증 항목 통과 |

생성 프롬프트에는 제안서 이미지를 스타일 참조로 넣고, 아래를 고정 문구로 써요: 등각 시점, 흰 배경, 따뜻한 화이트·라이트 그레이 톤, 인디고(`#4f46e5`) 빛줄기 포인트, 부드러운 간접광, 글자·로고·워터마크 없음. 스프라이트는 "같은 카메라각, 전신, 접지 그림자 별도"로 요청해요. 모든 프롬프트와 옵션을 `docs/lab-graphic-credits.md`에 남겨요.

## 7. 구현 계약 (경로 A의 S4)

코드는 아래 경계를 지켜서 `lab-studio.js`의 영향을 최소화해요.

- **어댑터 계약**: `lab-plate.js`가 기존 `createLabScene({canvas, labels, roster, onSelect, reducedMotion, onFailure})`와 같은 이름으로 내보내고, 반환 객체는 `select(key)`, `setMeeting(key)`, `setActive(key)`, `setPaused(bool)`, `setVisible(bool)`, `zoom(factor)`, `reset()`, `dispose()`, `stats()`를 유지해요([lab-scene.js:436-444](../static/js/lab-scene.js#L436-L444)). 이러면 `start3D()` 흐름을 거의 그대로 쓸 수 있어요.
- **엔진 전환**: 템플릿 루트에 `data-engine="plate|webgl"` 같은 표시를 두고, 합격 전까지 `lab-scene.js`와 `static/vendor/three/`는 **삭제하지 않아요**(되돌리기용). 삭제는 사용자 승인 뒤 별도 작업이에요.
- **줌·초기화**: 회전 대신 CSS transform의 확대·이동. 한도는 1배~2.2배, 경계 밖으로 못 나가게 클램프해요. 선택한 연구원이 있으면 그 위치로 부드럽게 이동해요.
- **시작 방식**: WebGL이 필요 없으므로 모바일에서도 "3D 시작" 버튼 없이 바로 표시해요. 단 `prefers-reduced-motion`이면 흐름선·펄스 애니메이션을 정지해요.
- **상태 의미 보존**: `setActive`는 실제 `/lab/live.json`의 진행 중 연구원에게만 링을 켜요. 대기 연출(숨쉬기 등)은 작게, "지금 작업 중"으로 오해되지 않게 해요. 기존 경계 문구는 유지해요([lab-3d-design.md](lab-3d-design.md)).
- **접근성**: 핫스팟은 `<button>`이고 `aria-pressed`·포커스 링을 가져요. 이름 버튼 8개(아래 명부)는 그대로 유지해요. 이미지 `alt`는 장면 요약 한 문장이고 장식 레이어는 `aria-hidden`.
- **문구 수정이 필요한 곳**: "좌우로 드래그해 둘러보고…", 캔버스 `aria-label`의 "좌우 방향키로 회전", 버튼 `title`/`aria-label`의 "시점 초기화"(→ "전체 보기" 등) — [_studio.html](../templates/office/_studio.html), [lab-studio.js](../static/js/lab-studio.js), [lab-studio.css](../static/css/lab-studio.css), 모바일 [templates/office/mobile/office.html](../templates/office/mobile/office.html). 방향키는 회전 대신 이동으로 바꿔요.
- **예산(경로 A)**: 초기 이미지 합계 PC ≤ 800KB, 모바일 ≤ 350KB(WebP). 사람 스프라이트는 개별 ≤ 60KB. 원본 PNG는 저장소 `static/`에 넣지 않고 `output/` 등 비추적 위치에 둬요. 지연 로딩은 배경판만 `fetchpriority="high"`.
- **지키는 규칙**: [CLAUDE.md](../CLAUDE.md)의 템플릿 규칙, 외부 CDN 런타임 없음, 새 런타임 의존성 없음, 색은 `static/css/premium.css` 토큰(인디고 `#4f46e5`), 한국어 해요체 UI 문구.

## 8. 이미지 QA 체크리스트 (스스로 채점, 항목별 pass/fail 기록)

1. 시점·원근이 제안서와 같은 등각이고 여러 레이어가 서로 어긋나지 않아요.
2. 질감: 대리석·스틸·유리·카펫이 단색이 아니라 재질로 읽혀요.
3. 인물 8명이 머리·옷으로 구분되고 손가락·얼굴·의자 자세에 깨짐이 없어요.
4. 모든 인물의 발과 의자 바퀴에 접지 그림자가 있어요.
5. 이미지 안에 읽을 수 있는 글자·로고·워터마크가 없어요.
6. 빛줄기는 인디고 단일 색이고 서가→테이블→발행대 순서로 이어져요.
7. 배경판 가장자리가 카드 배경과 이음새 없이 섞여요(PC·모바일).
8. 팔레트가 사이트 톤(밝은 중성색+인디고)에서 벗어나지 않아요.

최종 판단은 제안서 이미지와 **나란히 놓은 비교 스크린샷**으로 해요. "충분히 좋아졌다"는 말만 남기지 않고 pass/fail 표를 남겨요.

## 9. 검증

- 로컬 실행·캡처: `.claude/skills/run-local/SKILL.md`와 `webapp-testing`(Playwright). 격리된 브라우저 세션을 써요.
- PC 1440px, 모바일 390px(User-Agent + `force_version=mobile` 쿠키로 모바일 템플릿 선택까지 확인), `prefers-reduced-motion`.
- 확인 항목: 8명 선택(클릭·이름 버튼·Tab/Enter), `setActive`에 쓰는 실제 상태 형식의 테스트 응답, 회의 이전/다음/종료, 확대·축소·초기화·이동 키, 움직임 정지 시 추가 갱신 없음, 이미지 로딩 실패 시 대체 표시, 가로 넘침 없음, 콘솔 오류 없음, 전송량 예산.
- 스크린샷은 업무 DB가 아닌 임시 DB로 찍고, 테스트 데이터로 만든 상태는 최종 캡처에 쓰지 않아요(기존 방식 유지).
- 명령: `py -3.10 manage.py check`, 연구실 관련 `office` 테스트. `python` 스텁은 쓰지 않아요.
- 완료 보고는 한국어 해요체로, 실제로 확인한 것과 못 한 것(실기기 성능, 실서버 전송량)을 구분해요.

## 10. 사용자 결정이 필요한 항목 (기본값으로 진행하되 보고서에 명시)

| 결정 | 기본값 | 대안 |
|---|---|---|
| 자유 회전을 포기해도 되는가 | 포기(고정 시점 + 확대·이동) | 유지가 필수라면 경로 B로 가야 하고 인물 스타일이 달라져요 |
| 9명 → 8명 배치 | 섹션 6-1 | 서가 2명 유지 후 책상 1석 제거 등 |
| AI 생성 이미지를 사이트 자산으로 사용 | 사용. 도구 약관·권리를 `docs/lab-graphic-credits.md`에 기록 | 사용 불가 시 경로 B |
| Blender 등 도구 설치 | 설치하지 않음 | 경로 B 전환 시 사용자 승인 후 설치 |

## 11. 범위와 금지

- 건드려도 되는 파일: 위 섹션 7의 4개 화면 파일, 새 `static/js/lab-plate.js`, `static/img/lab/plate/`, 신규 문서 2개(`lab-graphic-credits.md`, 기존 구현 기록의 3D 절 갱신).
- **건드리지 않는 것**: `office/` 파이프라인·모델 라우팅 코드, 운영 서버, DB·마이그레이션, 메일·구독 호출, 다른 `.claude/skills`.
- 작업 트리에는 이 작업과 무관한 미커밋 변경이 많아요(`office/*`, `common/services/*` 등). **되돌리거나 스테이징하거나 커밋하지 않아요.** 커밋·push·배포는 사용자가 요청할 때만 해요.
- 비밀값·개인정보를 생성 프롬프트에 넣지 않아요. 비용이 드는 API 키 경로로 우회하지 않고, 구독(CLI)의 이미지 생성 도구만 써요.
- Claude 메모리 파일은 읽지도 쓰지도 않아요. 인계가 필요하면 보고서에 후보로 적어요.

## 12. 다음 세션 시작 문구 (복사해서 사용)

```text
codex -m gpt-6-astra -c model_reasoning_effort=high
```

```text
docs/lab-graphic-handoff.md를 먼저 끝까지 읽고 S0~S1부터 진행해 주세요.
목표는 output/pdf/assets/lab-studio-concept.png 수준의 연구실 그래픽이에요.
S1 스파이크 결과(합격/불합격, 근거 이미지)를 보고한 뒤 S2 이후로 가요.
커밋·push·배포는 하지 말고, 작업 트리의 기존 변경은 건드리지 마세요.
```

## 참고한 자료

- [Quaternius Universal Animation Library](https://quaternius.com/packs/universalanimationlibrary.html), [OpenGameArt 등록](https://opengameart.org/content/universal-animation-library)
- [@gltf-transform/cli (npm)](https://npmjs.com/package/@gltf-transform/cli)
- [three.js 포럼: 라이트맵과 AO 베이크](https://discourse.threejs.org/t/will-light-map-that-store-as-ao-map-in-blender-cause-any-lighting-data-loss/25030)
- [Ready Player Me 종료 정리](https://genies.com/blog/ready-player-me-shutdown)
- [KayKit 캐릭터 애니메이션](https://opengameart.org/content/kaykit-character-animations), [Kenney Character Assets](https://kenney.itch.io/kenney-character-assets)
- 저장소: [lab-3d-design.md](lab-3d-design.md), [lab-upgrade-implementation.md](lab-upgrade-implementation.md)
