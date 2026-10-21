# 야구게임 구장 이미지

이벤트 배경 네 장(`manager-office.webp`, `press-room.webp`, `negotiation-room.webp`, `finals-stadium.webp`)의 프롬프트와 제작 방법은 [story-prompts.md](story-prompts.md)에 있어요.

KBO 10구단 유니폼과 카드 배경의 제작 기록은 [uniforms/README.md](uniforms/README.md)에 있어요.

- 파일: `stadium.webp` (1536×1024, 약 299 KiB)
- 제작: Codex 기본 제공 `image_gen` 도구로 새로 생성했어요. 별도 서버 API 호출은 추가하지 않았어요.
- 용도: 정식·라이트 공용 구장 배경과 각성·승부·수상 장면 배경이에요.
- 원본은 PNG이며, Pillow로 WebP 품질 86으로 변환했어요.
- 구단 로고·인물·UI 글자는 포함하지 않았어요. 문구와 효과는 HTML/CSS로 표시해요.

## 최종 생성 프롬프트

Use case: stylized-concept. Asset type: premium baseball career simulation game panoramic stadium backdrop, landscape 1536x1024. A beautifully crafted realistic 3D baseball stadium viewed from just behind home plate, symmetrical diamond receding toward center field, immaculate mown grass, pale chalk lines and clay infield, grand sweeping stands and fine architectural floodlight masts, hazy late afternoon sunlight, clear luminous pale gray blue sky occupying upper half with generous negative space. High-end sports video game environment art, physically believable materials, subtle film grain, sophisticated slightly desaturated editorial color grade, natural grass is restrained muted green, soft indigo atmosphere in far stands, pale white highlights. Empty playing field without people, no foreground objects. No UI, no text, no logos, no lettering, no watermarks, no real team branding. Render an immersive polished environment with cinematic depth and understated lighting that can support HTML text overlay. All stadium and field detail mostly in lower two thirds, landscape wide framing.
