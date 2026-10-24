# 경기 환경·특성 발견 이미지

2026-10-25, Codex 기본 제공 `image_gen`으로 생성했어요. 서버측 API 호출은 추가하지 않았어요.

| 파일 | 용도 | 규격 |
|---|---|---|
| `preparation.webp` | 비시즌 경기 전 루틴의 준비 장면 | 1536×1024, 238,094바이트 |
| `discovery.webp` | 숨은 특성 발견의 렌즈 속 야구공 | 512×512, RGBA 투명, 36,660바이트 |

PNG에서 Pillow로 WebP 품질 86으로 변환했어요. 발견 이미지는 512px로 축소하면서 알파를 유지했어요. 구단 로고·문구·실존 인물은 없어요. 문구·조건 아이콘·점수·선택·연출은 HTML/SVG/CSS로 표시해요. 미디어데이는 기존 `../press-room.webp`를 재사용해요. 이 준비 배경은 경기 날씨의 실제 기록을 나타내지 않아요.

## 최종 프롬프트

### discovery

Use case: stylized-concept. Asset type: transparent decorative centerpiece for a Korean baseball career game's hidden trait discovery dialog. Primary request: an elegant tangible scouting discovery object: a small white leather baseball with fine indigo stitching held inside a clear circular optical lens with a subtle brushed silver rim, viewed three-quarter front, a few restrained refracted indigo glints revealing the baseball's material. Premium realistic sports game item render, physically believable translucent glass, pearlescent white leather, quiet indigo #4f46e5 highlights. One compact centered object, generous transparent margin, silhouette clean at 160 pixels, isolated transparent background. A discovery and self-knowledge cue, not a victory trophy or medal. No lettering, numbers, text, branding, team logo, watermark, UI, hands or people. Square 1024x1024.

### preparation

Use case: stylized-concept. Asset type: wide background for a Korean baseball career simulation pre-season routine choice. Primary request: quiet morning preparation inside a clean covered baseball training dugout, a plain wooden baseball bat, worn leather fielding glove, folded white towel and unmarked water bottle arranged naturally on the right end of a bench, open view on the left toward a beautifully maintained sunlit baseball field and distant low stands. Premium cinematic realistic sports game environment art, natural wood, leather and clay, slightly desaturated editorial color grade, restrained soft blue indigo atmosphere, warm morning sunlight, focused and hopeful. Wide horizontal 1536x1024, field and environment legible in mobile center crop, natural negative space on the left for HTML text. No foreground people, readable signs, letters, text, numbers, logos, watermarks, real branding, confetti, trophies, interface or scoreboard text.
