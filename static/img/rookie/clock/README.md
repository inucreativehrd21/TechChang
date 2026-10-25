# 정식 모드 시간대 구장

기본 제공 `image_gen`으로 원본 `../stadium.webp`를 편집·생성했어요. 서버 API 호출은 없어요.

카메라·구도·구장 구조를 유지한 1536×1024 이미지 7장과 같은 크기의 투명 장식 3장이에요. PNG 원본은 로컬 검증 폴더에 보존하며 WebP 변환은 Pillow로 했어요. 투명 장식은 알파 채널이 원본과 일치해요.

| 파일 | 용량 | 용도 |
| --- | --- | --- |
| `dawn.webp` | 284.8 KiB | 시각별 배경 |
| `morning.webp` | 301.4 KiB | 시각별 배경 |
| `noon.webp` | 290.4 KiB | 시각별 배경 |
| `afternoon.webp` | 291.9 KiB | 시각별 배경 |
| `dusk.webp` | 268.5 KiB | 시각별 배경 |
| `night.webp` | 286.9 KiB | 시각별 배경 |
| `main.webp` | 282.7 KiB | 시각별 배경 |
| `opening.webp` | 97.1 KiB | 투명 시즌 장식 |
| `stretch.webp` | 33.9 KiB | 투명 시즌 장식 |
| `postseason.webp` | 208.2 KiB | 투명 시즌 장식 |

현재 시각 배경과 해당 시즌 장식만 즉시 요청해요. 다음 배경은 시각 경계에 도달할 때 불러와요. 장식은 선수·로고·글자가 없는 추상 관중 불빛과 빈 깃발이에요.

## 최종 프롬프트

### dawn

Use case: lighting-weather. Edit target: the attached stadium image. Asset: dawn variant for an existing baseball game environment, landscape 1536x1024. Preserve the exact camera, perspective, architecture, bleachers, home plate, chalk diamond, masts and horizon of the reference image. Change only sky, light and subtle field preparation: quiet pale dawn before sunrise, floodlights completely off, cool pearly blue sky, slightly damp infield with a neatly rolled small groundskeeping tarp far to the right edge, no people. Left third remains pale and low contrast with ample clear light atmosphere for dark HTML text; keep darker areas on the right. Same sophisticated realistic 3D environment art and slightly desaturated palette. No text, no logos, no figures, no real team branding. This is one single full-frame image, no panel or collage.

### morning

Use case: lighting-weather. Edit target: reference image 1, the original stadium.webp. Make ONE single full-frame landscape 1536x1024 variant for a baseball career game. Keep exactly the same home-plate camera, perspective, chalk line geometry, masts, seating, buildings, horizon and crop. Keep field entirely empty of players and characters. Change only lighting and sky. Same polished realistic 3D environment art, restrained color. No text, logos, letters, watermarks, emblems or team branding. The left third must stay luminous, pale and low contrast for dark HTML text, with strongest dark blue shadows on the right. Clear 11:00 morning sunshine, fresh clean blue sky and gentle short shadows, floodlights off, crisp mown grass.

### noon

Use case: lighting-weather. Edit target: reference image 1, the original stadium.webp. Make ONE single full-frame landscape 1536x1024 variant for a baseball career game. Keep exactly the same home-plate camera, perspective, chalk line geometry, masts, seating, buildings, horizon and crop. Keep field entirely empty of players and characters. Change only lighting and sky. Same polished realistic 3D environment art, restrained color. No text, logos, letters, watermarks, emblems or team branding. The left third must stay luminous, pale and low contrast for dark HTML text, with strongest dark blue shadows on the right. 13:00 high noon, sun high overhead, very short shadows, bright clean pearly blue sky, floodlights off.

### afternoon

Use case: lighting-weather. Edit target: reference image 1, the original stadium.webp. Make ONE single full-frame landscape 1536x1024 variant for a baseball career game. Keep exactly the same home-plate camera, perspective, chalk line geometry, masts, seating, buildings, horizon and crop. Keep field entirely empty of players and characters. Change only lighting and sky. Same polished realistic 3D environment art, restrained color. No text, logos, letters, watermarks, emblems or team branding. The left third must stay luminous, pale and low contrast for dark HTML text, with strongest dark blue shadows on the right. 15:30 late afternoon, warm sunlight from left, longer delicate field shadows, pale blue sky, floodlights off. Keep closest to the original mood.

### dusk

Use case: lighting-weather. Edit target: reference image 1, the original stadium.webp. Make ONE single full-frame landscape 1536x1024 variant for a baseball career game. Keep exactly the same home-plate camera, perspective, chalk line geometry, masts, seating, buildings, horizon and crop. Keep field entirely empty of players and characters. Change only lighting and sky. Same polished realistic 3D environment art, restrained color. No text, logos, letters, watermarks, emblems or team branding. The left third must stay luminous, pale and low contrast for dark HTML text, with strongest dark blue shadows on the right. 18:00 sunset, muted peach and lavender horizon into pale indigo upper sky, floodlights just beginning to glow, moderate grass illumination, quiet cinematic transition.

### night

Use case: lighting-weather. Edit target: reference image 1, the original stadium.webp. Make ONE single full-frame landscape 1536x1024 variant for a baseball career game. Keep exactly the same home-plate camera, perspective, chalk line geometry, masts, seating, buildings, horizon and crop. Keep field entirely empty of players and characters. Change only lighting and sky. Same polished realistic 3D environment art, restrained color. No text, logos, letters, watermarks, emblems or team branding. The left third must stay luminous, pale and low contrast for dark HTML text, with strongest dark blue shadows on the right. 20:00 night game light, floodlights on, soft luminous hazy pale blue atmosphere at the upper-left sky fading to deep indigo to the right. Fully illuminated green field. Preserve pale left negative space.

### main

Use case: lighting-weather. Edit target: reference image 1, the original stadium.webp. Make ONE single full-frame landscape 1536x1024 variant for a baseball career game. Keep exactly the same home-plate camera, perspective, chalk line geometry, masts, seating, buildings, horizon and crop. Keep field entirely empty of players and characters. Change only lighting and sky. Same polished realistic 3D environment art, restrained color. No text, logos, letters, watermarks, emblems or team branding. The left third must stay luminous, pale and low contrast for dark HTML text, with strongest dark blue shadows on the right. 22:00 main event, floodlights at full intensity, small abstract sparkling seat lights (no visible people), atmospheric night sky pale hazy luminous at left and deep indigo at right, crisp bright playing field, sophisticated sports finale mood. No fireworks (those are a separate layer).

### opening

Use case: compositing. Reference image 1 is ONLY the exact camera/alignment guide of a baseball stadium. Create ONE transparent RGBA overlay, 1536x1024, for compositing directly over this guide at identical scale and placement. Render ONLY the newly described seasonal decorations. ALL stadium, sky, field, ground and architecture from the reference must be absent/fully transparent in the output. The left 40 percent and the lower foreground must be entirely transparent for HTML text and home plate. Use restrained indigo and off-white fabric, realistic 3D details and believable scale. No lettering, logos, watermarks, numbers, people or real team branding. Genuine alpha transparency, not a checkerboard painted in pixels. Opening day atmosphere: elegant blank indigo and white bunting on the right-side spectator railings (roughly x900-1500,y480-640), a few blank opening-day pennants along the roof edge, and a delicate spread of tiny abstract crowd light specks aligned to right seats suggesting a full house without depicting any human figures. Keep the decorations sparse and precisely positioned for the original perspective.

### stretch

Use case: compositing. Reference image 1 is ONLY the exact camera/alignment guide of a baseball stadium. Create ONE transparent RGBA overlay, 1536x1024, for compositing directly over this guide at identical scale and placement. Render ONLY the newly described seasonal decorations. ALL stadium, sky, field, ground and architecture from the reference must be absent/fully transparent in the output. The left 40 percent and the lower foreground must be entirely transparent for HTML text and home plate. Use restrained indigo and off-white fabric, realistic 3D details and believable scale. No lettering, logos, watermarks, numbers, people or real team branding. Genuine alpha transparency, not a checkerboard painted in pixels. Final stretch week: three slender blank indigo/white pennant flags attached at the existing right grandstand roof line, concentrated x1050-1500,y350-580, fabric gently unfurled toward left, a few distant pennants at the far center railing. Transparent elsewhere; no celebration, no fireworks.

### postseason

Use case: compositing. Reference image 1 is ONLY the exact camera/alignment guide of a baseball stadium. Create ONE transparent RGBA overlay, 1536x1024, for compositing directly over this guide at identical scale and placement. Render ONLY the newly described seasonal decorations. ALL stadium, sky, field, ground and architecture from the reference must be absent/fully transparent in the output. The left 40 percent and the lower foreground must be entirely transparent for HTML text and home plate. Use restrained indigo and off-white fabric, realistic 3D details and believable scale. No lettering, logos, watermarks, numbers, people or real team branding. Genuine alpha transparency, not a checkerboard painted in pixels. Postseason: blank indigo/white flags on the right stadium railings at x1000-1500,y420-600, with two refined small silver and pale indigo firework bursts in the upper right sky at x1100-1450,y120-330 and just a few tiny falling sparks. Elegant finals atmosphere, fully transparent elsewhere. No trophy, text or people.
