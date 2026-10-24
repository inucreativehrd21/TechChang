# 시리즈 전광판 이미지 제작 기록

2026-10-25, Codex 기본 제공 `image_gen` 도구로 생성했어요. 서버측 AI API 호출은 추가하지 않았어요.

| 파일 | 상황 | 크기 |
|---|---|---|
| `international.webp` | WBC·올림픽·아시안게임·프리미어12 경기 기록 | 1536×1024 |
| `amateur.webp` | 고교·대학 대회 경기 기록 | 1536×1024 |
| `reflection.webp` | 최종 라운드 패배·준우승·탈락 회고 | 1536×1024 |

가을야구는 기존 `../finals-stadium.webp`를 재사용해요. 패배 배경이 대회 종류보다 우선해요. 로고·인물·글자를 넣지 않았고, 원본 PNG에서 Pillow로 WebP 품질 85로 변환했어요. 문구·점수·승패·축하는 HTML/CSS/JS에서 실제 저장 기록으로 표시해요. 이 배경은 실제 경기 날씨나 구장 정보가 아닌 대회 분위기를 표현해요.

## 최종 프롬프트

### international

Use case: stylized-concept. Asset type: panoramic backdrop for an international baseball tournament recap in a Korean baseball career simulation. Primary request: cinematic realistic high-end sports game environment art of a grand neutral international baseball stadium, viewed from behind home plate, broad curved tiers, tiny distant indistinct spectators, elegant rows of unmarked pennant poles on the far rim, immaculate diamond. Lighting: luminous early evening with floodlights, restrained cool blue atmosphere. Wide horizontal 1536x1024 composition, lower two thirds contain field and architecture, soft open sky. Natural grass and clay, photographic physically believable materials, understated slightly desaturated color grade. No recognizable real venue, no text, numbers, logos, watermark, readable flags, branding, UI, foreground players, trophies or confetti. Outcome-neutral scene usable for any national team's tournament result.

### amateur

Use case: stylized-concept. Asset type: panoramic backdrop for Korean high-school and university baseball tournament recap. Primary request: a beautiful modest Korean amateur baseball ground from behind home plate, low simple bleachers, safety netting, distant green hills and a few trees beyond the outfield, freshly chalked diamond and sunlit clay. Polished realistic high-end sports game environment art, restrained natural materials matching cinematic baseball game art. Bright clear afternoon, quiet expectant atmosphere, soft sky, wide horizontal 1536x1024 framing, diamond and stands in lower two thirds. No real school, no people in foreground, no text, letters, numbers, logos, banners, watermark, branding, UI, trophies or confetti. Outcome-neutral.

### reflection

Use case: stylized-concept. Asset type: panoramic baseball career game tournament defeat and runner-up recap. Primary request: quiet cinematic view from the mouth of an empty baseball dugout after the final game, a plain well-used leather baseball glove and a baseball resting on the right end of the wooden bench in the foreground, softly lit empty baseball diamond and distant unmarked stands beyond. Sophisticated realistic high-end sports game environment art, natural wood, subtle material texture, muted clay and grass, gentle blue dusk with a few soft floodlights. Reflective and hopeful, calm dignified mood without celebration or despair. Wide horizontal 1536x1024 composition with glove at lower right and open field toward left, useful for mobile crop too. No people, text, numbers, lettering, logos, watermarks, UI, branding, trophies, medals, confetti.
