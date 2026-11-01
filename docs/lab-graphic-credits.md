# 연구실 그래픽 생성·실험 기록


## S3 · B 배경 확정 및 8명 제작 (2026-10-31)
사용자가 배경 B안을 승인했어요. checker는 S1 첫 결과를 재사용하고 나머지 7명은 내장 image_gen으로 각각 생성했어요. 참조는 `output/lab-graphic-spike/plate-b.png`, 옵션은 `transparent_background=true`예요. 성별·나이는 이름에서 추정하지 않고 머리 모양·피부색은 실제 agents.py의 sprite를 따랐어요. 의상은 인계 문서의 크림·차콜·인디고 범위로 통일했어요.

### lead
```text
Use case: stylized-concept. Production transparent cutout for the referenced isometric architectural miniature research studio. Match its high camera elevation about 35 degrees, photoreal miniature materials, soft indirect light, warm white and light grey, natural fabric and correct anatomy. Full body and chair if seated, generous transparent margin, feet visible. Fictional neutral adult, no resemblance to real people. No background, floor, table, desk, text, logos, watermark, glow, or cast shadow. True RGBA transparency immediately outside silhouette; contact shadow will be separate CSS. Long dark espresso hair #2b2118, light warm skin #f1c9a5. Muted indigo knit top #4f46e5, charcoal trousers. Sitting on light grey upholstered thin steel office chair facing lower-right of image (three-quarter front), holding a closed plain notebook on lap. No glasses.
```

### critic
```text
Use case: stylized-concept. Production transparent cutout for the referenced isometric architectural miniature research studio. Match its high camera elevation about 35 degrees, photoreal miniature materials, soft indirect light, warm white and light grey, natural fabric and correct anatomy. Full body and chair if seated, generous transparent margin, feet visible. Fictional neutral adult, no resemblance to real people. No background, floor, table, desk, text, logos, watermark, glow, or cast shadow. True RGBA transparency immediately outside silhouette; contact shadow will be separate CSS. Chestnut bob hair #805449, light warm skin #f1c9a5. Cream cardigan over charcoal top, dark trousers. Sitting on light grey upholstered thin steel office chair facing upper-right of image, seen three-quarter back. Holding open plain notebook in lap. No glasses.
```

### charter
```text
Use case: stylized-concept. Production transparent cutout for the referenced isometric architectural miniature research studio. Match its high camera elevation about 35 degrees, photoreal miniature materials, soft indirect light, warm white and light grey, natural fabric and correct anatomy. Full body and chair if seated, generous transparent margin, feet visible. Fictional neutral adult, no resemblance to real people. No background, floor, table, desk, text, logos, watermark, glow, or cast shadow. True RGBA transparency immediately outside silhouette; contact shadow will be separate CSS. Short dark brown hair #2b2118, light warm skin #efc8a8. Light grey collared shirt, charcoal trousers. Sitting on light grey upholstered thin steel office chair facing upper-left of image, seen three-quarter back. Holding a plain sheet near lap. No glasses.
```

### editor
```text
Use case: stylized-concept. Production transparent cutout for the referenced isometric architectural miniature research studio. Match its high camera elevation about 35 degrees, photoreal miniature materials, soft indirect light, warm white and light grey, natural fabric and correct anatomy. Full body and chair if seated, generous transparent margin, feet visible. Fictional neutral adult, no resemblance to real people. No background, floor, table, desk, text, logos, watermark, glow, or cast shadow. True RGBA transparency immediately outside silhouette; contact shadow will be separate CSS. Short grey-brown hair #79746f, light warm skin #f3d1b0, thin dark glasses. Charcoal blazer over cream shirt, dark trousers. Standing facing lower-left, three-quarter front, holding a plain paper folder at waist and gesturing gently with one hand.
```

### hrd
```text
Use case: stylized-concept. Production transparent cutout for the referenced isometric architectural miniature research studio. Match its high camera elevation about 35 degrees, photoreal miniature materials, soft indirect light, warm white and light grey, natural fabric and correct anatomy. Full body and chair if seated, generous transparent margin, feet visible. Fictional neutral adult, no resemblance to real people. No background, floor, table, desk, text, logos, watermark, glow, or cast shadow. True RGBA transparency immediately outside silhouette; contact shadow will be separate CSS. Short curly dark brown hair #4a2c17, light warm skin #f3d1b0. Stone grey sweater over white shirt, charcoal trousers. Sitting on light grey upholstered office chair facing upper-right, seen three-quarter back, relaxed forearms extending forward at keyboard height but no desk or keyboard. No glasses.
```

### data
```text
Use case: stylized-concept. Production transparent cutout for the referenced isometric architectural miniature research studio. Match its high camera elevation about 35 degrees, photoreal miniature materials, soft indirect light, warm white and light grey, natural fabric and correct anatomy. Full body and chair if seated, generous transparent margin, feet visible. Fictional neutral adult, no resemblance to real people. No background, floor, table, desk, text, logos, watermark, glow, or cast shadow. True RGBA transparency immediately outside silhouette; contact shadow will be separate CSS. Straight black bob hair #1d1d1d, light warm skin #efc8a8. Ivory shirt with dark grey sleeveless vest, charcoal trousers. Sitting on light grey upholstered office chair facing upper-right, seen three-quarter back, relaxed forearms extending forward at keyboard height but no desk or keyboard. No glasses.
```

### coding
```text
Use case: stylized-concept. Production transparent cutout for the referenced isometric architectural miniature research studio. Match its high camera elevation about 35 degrees, photoreal miniature materials, soft indirect light, warm white and light grey, natural fabric and correct anatomy. Full body and chair if seated, generous transparent margin, feet visible. Fictional neutral adult, no resemblance to real people. No background, floor, table, desk, text, logos, watermark, glow, or cast shadow. True RGBA transparency immediately outside silhouette; contact shadow will be separate CSS. Short medium brown hair #5a3a2a, light warm skin #f1c9a5, thin dark glasses. Muted indigo overshirt #4f46e5, charcoal trousers. Sitting on light grey upholstered office chair facing upper-right, seen three-quarter back, relaxed forearms extending forward at keyboard height but no desk or keyboard.
```

## S1 결과: 통과, S2 배경 선택 대기

배경 4장(각 1536×1024 RGB), 인물 3장(각 1024×1536 RGBA)을 생성했어요. 세 인물의 투명 픽셀은 각각 1,219,307 / 1,127,270 / 1,151,267개예요. alpha 범위는 모두 0~254예요. 원본의 alpha를 보존했고 별도 배경 제거 모델은 쓰지 않았어요. 흰색과 회색 판 위의 실제 브라우저 합성에서 눈에 띄는 검은 테두리나 배경 덩어리가 보이지 않았어요.

같은 머리 묶음·안경·옷·책·체형이 세 번 유지됐어요. 팔 각도·옷 주름·인물 크기는 조금씩 달라서 발 위치와 표시 크기는 개별 정렬해야 해요. 뒷면/측면 시험이므로 정면 얼굴 일관성까지 확인한 결과는 아니에요. 서가 앞의 한 인물을 CSS 접지 그림자와 합성해 시점·접지를 확인했어요. 앉은 인물·의자·책상 뒤의 가림 처리는 S3에서 별도로 검증해야 해요.

### 후보 판단

| 후보 | 판단 |
|---|---|
| A | 재질은 통과. 서가 앞의 반투명 패널이 남아 인물 합성 영역이 복잡해 후순위예요. |
| B | 추천. 제안서 배치와 가장 가깝고 서가·세 작업석·발행대가 정돈돼 있어요. |
| C | 차선. 따뜻한 질감과 풍부한 서가가 좋아요. 발행대의 추가 조형물은 원안과 차이가 있어요. |
| D | 제외. 사람 없는 배경에는 적합하지만 제거 요청한 좌석이 남아 별도 의자 레이어와 충돌해요. |

### 8개 QA 항목의 현재 범위

| 항목 | S1 판정 | 최종 화면에서 남은 확인 |
|---|---|---|
| 등각 시점·레이어 정합 | PASS — B안과 서 있는 1인 합성 | 앉은 7인 추가 시 확인 |
| 석재·스틸·유리·카펫 질감 | PASS — B/C 모두 | 압축 이미지 최종 표시 |
| 8명 구분·손·얼굴·자세 | 시험 1인은 PASS, 전체 미검증 | 8명 제작 이후 확인 |
| 발·의자 접지 | 서 있는 1인은 PASS, 의자 미검증 | 앉은 인물과 가림 순서 |
| 읽을 수 있는 글자·로고 없음 | PASS — 표시 크기 육안 확인 | 모든 인물·소품 최종 확인 |
| 인디고 흐름선 | 미적용 — 별도 SVG 예정 | 서가→테이블→발행대 연결 |
| 카드 배경 경계 | 흰색 비교판 PASS | 실제 PC·모바일 템플릿 검증 |
| 밝은 중성색 팔레트 | PASS — B/C 모두 | 인디고 상태 연출 추가 후 확인 |

S1 통과는 생성·합성 방식의 실현 가능성 판정이에요. S3~S5의 최종 품질 합격으로 보고하지 않아요. 선택 전에는 static 자산이나 서비스 렌더 계층을 교체하지 않았어요.

### 검토 자료·크기

- [기준 이미지와 합성 비교](../output/lab-graphic-spike/comparison.png)
- [회색 배경 alpha 확인](../output/lab-graphic-spike/alpha-review.png)
- [상위 B/C 후보 비교](../output/lab-graphic-spike/candidates.png)
- [브라우저 합성 원본](../output/lab-graphic-spike/review.html)
- B 배경: PC WebP 136,858 bytes, 모바일 52,196 bytes. C: 139,060 / 52,926 bytes.
- 시험 인물 320px 높이 WebP: 6,634 / 7,646 / 7,452 bytes. Pillow는 포맷 변환·리사이즈에만 사용했고 alpha를 보존했어요. 전체 8명 전송량은 아직 실측하지 않았어요.
- 기존 서비스 코드를 수정하지 않은 이미지 실험이므로 Django 회귀 검사를 반복하지 않았어요. UI 적용 시 인계 문서 S5 검사를 진행해요.

다음 작업: 사용자 배경 선택 → 선택 배경에 맞는 8명·의자·가림 레이어 제작 → lab-plate 어댑터 → PC/모바일 검증. Claude 메모리에는 고정 시점의 이미지 합성 경로, WebGL 회전 제거, 배경 B/C 선택과 8인 가림 설계가 인계 후보예요.

## 같은 인물 재생성 2회

첫 인물 checker-1.png와 기준 방 이미지를 함께 참조했어요. transparent_background=true. 아래 동일 프롬프트를 두 번 독립 호출했어요.

```text
Use case: identity-preserve / background-extraction. Re-create the EXACT SAME fictional researcher in image 1 as a full-body production sprite: same tied medium-brown hair, thin charcoal glasses, cream collared overshirt, charcoal straight trousers, dark shoes, skin tone, build and open blank booklet held in both hands. Same three-quarter back/side orientation toward upper left. Image 2 defines the high isometric room camera and miniature rendering style: match that camera elevation precisely. Realistic hands, fabric folds, anatomy. Entire person with both shoes and margin. CRITICAL: true RGBA transparency immediately outside the silhouette. Absolutely no black background, glow, aura, halo, vignette, fog, floor or cast shadow. No text, logos, watermarks. This is the same person, not a new character; small natural difference in booklet angle only.
```


2026-10-31. 인계 문서 S0~S1 실험. 서비스 적용 전이에요.

## 도구·권리

내장 image_gen을 사용했고 API 키 경로로 우회하지 않았어요. 도구가 실제 모델 ID·최대 해상도를 제공하지 않아 특정 모델명은 기록하지 않아요. 참조는 이전 세션 생성물 output/pdf/assets/lab-studio-concept.png예요. 실존 인물 사진·LimeZu·외부 모델은 사용하지 않았어요.

[OpenAI 이용약관](https://openai.com/policies/terms-of-use/)의 Content 절을 확인했어요. 당사자 사이에서 법이 허용하는 범위의 출력물 권리는 사용자에게 귀속되며, 고유성은 보장되지 않아요. 독점권·제3자 권리 비침해를 별도 보증하는 기록은 아니에요. 별도 사업자 계약이 있으면 그 계약도 적용돼요.

기본값은 고정 시점+확대·이동, 8명 배치, 생성 이미지 활용, 신규 도구 설치 없음이에요.

## 배경 4안 프롬프트

공통 참조: output/pdf/assets/lab-studio-concept.png. transparent_background=false. 각 후보를 독립 호출했어요.

### A안

```text
Use case: precise-object-edit. Create a production background plate based on the supplied architectural research studio reference. Same fixed isometric view, approximately 30-degree floor diagonals, same 3:2 landscape framing and room footprint. REMOVE EVERY PERSON and all chairs (chairs will be in separate person layers). Preserve the extraordinary premium photoreal miniature architectural quality: finely veined pale limestone, brushed steel, ribbed translucent glass, tactile carpet, books and research image panels, soft indirect lighting, subtle ambient occlusion, elegant plants. Keep archive on left, exactly three workstation desks along back/right, oval central meeting table with three empty seating positions and one standing position, circular publication pedestal at front/right. NO text, letters, logos, watermarks, NO people or body parts. Abstract diagrams only on papers/screens. Neutral warm white/light gray, single indigo #4f46e5 accent. Remove the reference's floating document panels and luminous connecting cable: these will be separate interactive layers. White background, entire room in frame with margin. A: Match the reference composition as closely as possible. Restrained ivory limestone, softly luminous shelving and oval textured rug.
```

### B안

```text
Use case: precise-object-edit. Create a production background plate based on the supplied architectural research studio reference. Same fixed isometric view, approximately 30-degree floor diagonals, same 3:2 landscape framing and room footprint. REMOVE EVERY PERSON and all chairs (chairs will be in separate person layers). Preserve the extraordinary premium photoreal miniature architectural quality: finely veined pale limestone, brushed steel, ribbed translucent glass, tactile carpet, books and research image panels, soft indirect lighting, subtle ambient occlusion, elegant plants. Keep archive on left, exactly three workstation desks along back/right, oval central meeting table with three empty seating positions and one standing position, circular publication pedestal at front/right. NO text, letters, logos, watermarks, NO people or body parts. Abstract diagrams only on papers/screens. Neutral warm white/light gray, single indigo #4f46e5 accent. Remove the reference's floating document panels and luminous connecting cable: these will be separate interactive layers. White background, entire room in frame with margin. B: Same footprint and camera. More finely ribbed glass, brushed steel table base, slightly cooler pearl-gray limestone, exquisitely soft gallery lighting.
```

### C안

```text
Use case: precise-object-edit. Create a production background plate based on the supplied architectural research studio reference. Same fixed isometric view, approximately 30-degree floor diagonals, same 3:2 landscape framing and room footprint. REMOVE EVERY PERSON and all chairs (chairs will be in separate person layers). Preserve the extraordinary premium photoreal miniature architectural quality: finely veined pale limestone, brushed steel, ribbed translucent glass, tactile carpet, books and research image panels, soft indirect lighting, subtle ambient occlusion, elegant plants. Keep archive on left, exactly three workstation desks along back/right, oval central meeting table with three empty seating positions and one standing position, circular publication pedestal at front/right. NO text, letters, logos, watermarks, NO people or body parts. Abstract diagrams only on papers/screens. Neutral warm white/light gray, single indigo #4f46e5 accent. Remove the reference's floating document panels and luminous connecting cable: these will be separate interactive layers. White background, entire room in frame with margin. C: Same footprint and camera. Warm cream stone, more detailed archival shelving, subtly sculpted rounded table edges, quiet afternoon diffuse light.
```

### D안

```text
Use case: precise-object-edit. Create a production background plate based on the supplied architectural research studio reference. Same fixed isometric view, approximately 30-degree floor diagonals, same 3:2 landscape framing and room footprint. REMOVE EVERY PERSON and all chairs (chairs will be in separate person layers). Preserve the extraordinary premium photoreal miniature architectural quality: finely veined pale limestone, brushed steel, ribbed translucent glass, tactile carpet, books and research image panels, soft indirect lighting, subtle ambient occlusion, elegant plants. Keep archive on left, exactly three workstation desks along back/right, oval central meeting table with three empty seating positions and one standing position, circular publication pedestal at front/right. NO text, letters, logos, watermarks, NO people or body parts. Abstract diagrams only on papers/screens. Neutral warm white/light gray, single indigo #4f46e5 accent. Remove the reference's floating document panels and luminous connecting cable: these will be separate interactive layers. White background, entire room in frame with margin. D: Same footprint and camera. Editorial gallery atmosphere, pale microcement, slim steel workstations and richer textile rug. Keep warm white and indigo, not dark.
```

## 검증관 첫 생성

동일 참조, transparent_background=true.

```text
Use case: stylized-concept / background-extraction. Asset: a single full-body photoreal miniature researcher sprite, isolated on truly transparent RGBA background. Reference image defines architectural miniature style, soft gallery light and high fixed isometric camera looking downward, NOT identity. One fictional adult person with neutral gender presentation, warm light skin #f3d1b0, medium brown #7a4a1e hair neatly tied at back, thin charcoal eyeglasses, cream overshirt, charcoal straight trousers, simple dark shoes. Standing, holding an open plain research booklet naturally with both hands, facing upper-left in the room (three-quarter back/side visible). Realistic clothing folds, hands, anatomy, head and eyes; not chibi or toy capsule. Whole figure including shoes, comfortable transparent margin, one person only. No furniture, floor, background, cast shadow, text, watermark or logos. Contact shadows will be a separate layer. Match the supplied room's approximately 30-degree isometric floor axes and camera elevation, muted warm-white/gray palette.
```

# 최종 집필석 자세 수정 · 2026-10-31

사용자의 작업 재개와 다리 수정 요청에 따라 B 배경 적용을 마무리했어요. 기존 S1/S2 기록은 이전 시점의 기록이에요. 현재 결과는 [최종 검증](lab-graphic-final-review.md)에 있어요.

내장 `image_gen`으로 편집했고 `transparent_background=false`를 사용했어요. 입력 1은 `output/lab-graphic-spike/plate-b.png`(편집 대상), 입력 2는 사용자 첨부의 빨간 원이 있는 작업석 이미지(인물·문제 위치 참조)예요. API 키 경로는 사용하지 않았어요. Pillow는 생성 결과의 크기 조절과 WebP 인코딩에만 사용했어요.

원본은 `output/lab-graphic-final/workstations-seated.png`(1536×1024), 실제 사용 자산은 `static/img/lab/plate/plate-seated.webp`(171,036 bytes)와 `plate-seated-mobile.webp`(960×640, 68,106 bytes)예요. 기존 배경·인물 파일은 보존했어요.

## 최종 편집 프롬프트

```text
Use case: precise-object-edit.
Input image 1 is the EDIT TARGET: the empty isometric research studio background. Input image 2 is a supporting identity/reference crop with RED ANNOTATIONS showing a previous bad composite. Produce a finished corrected version of IMAGE 1 at its exact same full-room framing and 3:2 aspect ratio.
Change ONLY the three workstation seating areas along the right/back wall: add the same three fictional adult workers from image 2, from left to right curly brown hair and grey sweater; black bob and ivory shirt with charcoal vest; short brown hair, thin glasses, muted indigo shirt. Each sits naturally in a grey upholstered swivel office chair, faces their own monitor, has hands placed naturally on their own desk keyboard, and has BOTH thighs/knees/legs UNDER the desk in the recessed leg space. Knees bent normally, feet resting on floor inside the desk recess, not floating, not pointing into the aisle, no crossed legs. Chair close enough for typing, natural relaxed ergonomic posture. Desk top correctly OCCLUDES thighs and knees, desk side panels correctly occlude feet when appropriate. Allow adjusting/removing only the under-desk drawer blocks where necessary to make real usable knee space. Three distinct seating positions and exactly three people.
The flaw in reference image 2 is that legs sit in front of solid desk cabinets and feet float outside: FIX THAT. Do not copy those leg poses. Render people and furniture together with correct depth and contact shadows.
Preserve ALL other image-1 elements precisely: full room outline, camera elevation, perspective, white background, ribbed glass, shelving, plants, central oval table and its EMPTY surrounds, rug, publication pedestal, all textures, neutral palette, light, and all furniture positions. No other people anywhere. No cropping, no camera shift. Same realistic high quality architectural miniature aesthetic. People must be realistically scaled to furniture, not oversized.
No red circles or markings, no labels, text, watermark or logos. Keep the rest of the room empty for separately composited interactive figures.
```

---
