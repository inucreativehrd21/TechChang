"""
포인트로 구매하는 회원 이모티콘 시드 데이터 생성 커맨드

- 귀여운 카와이 얼굴 이모티콘 10종 (각 1000P)
- 테크창 로고 이모티콘 1종 (100P)
이미지는 PIL로 생성하여 media/emoticons/ 에 저장하고 Emoticon 레코드를 만든다.

사용법:
  python manage.py seed_emoticons            # 없는 것만 생성
  python manage.py seed_emoticons --force    # 이미지/가격을 다시 생성(덮어쓰기)
"""
import math
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from PIL import Image, ImageDraw

SS = 3          # 슈퍼샘플링 배율 (계단현상 방지)
SIZE = 480      # 최종 출력 크기(px)

CUTE_PRICE = 1000
TECH_PRICE = 100


# ──────────────────────────────────────────────────────────────
# 드로잉 헬퍼 (좌표는 0~SIZE 기준, 내부에서 SS배 확대)
# ──────────────────────────────────────────────────────────────
def _new_canvas():
    img = Image.new('RGBA', (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _c(*vals):
    """좌표/길이를 SS배로 변환."""
    return tuple(v * SS for v in vals)


def ellipse(d, cx, cy, rx, ry, fill=None, outline=None, width=1):
    d.ellipse(_c(cx - rx, cy - ry, cx + rx, cy + ry), fill=fill,
              outline=outline, width=width * SS)


def line(d, x1, y1, x2, y2, fill, width):
    d.line(_c(x1, y1, x2, y2), fill=fill, width=width * SS)


def arc(d, cx, cy, rx, ry, start, end, fill, width):
    d.arc(_c(cx - rx, cy - ry, cx + rx, cy + ry), start, end,
          fill=fill, width=width * SS)


def polygon(d, pts, fill):
    d.polygon([(x * SS, y * SS) for x, y in pts], fill=fill)


def heart(d, cx, cy, s, fill):
    """하트 모양 (s = 대략 반폭)."""
    r = s * 0.5
    ellipse(d, cx - r, cy - r * 0.6, r, r, fill=fill)
    ellipse(d, cx + r, cy - r * 0.6, r, r, fill=fill)
    polygon(d, [(cx - s, cy - r * 0.3), (cx + s, cy - r * 0.3), (cx, cy + s)], fill=fill)


def star(d, cx, cy, s, fill):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = s if i % 2 == 0 else s * 0.42
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    polygon(d, pts, fill)


def head(d, color, outline):
    """둥근 얼굴 베이스."""
    cx = cy = SIZE / 2
    r = SIZE * 0.40
    ellipse(d, cx, cy, r, r, fill=color, outline=outline, width=3)


def blush(d, color):
    cy = SIZE * 0.58
    for dx in (-SIZE * 0.24, SIZE * 0.24):
        ellipse(d, SIZE / 2 + dx, cy, SIZE * 0.075, SIZE * 0.05, fill=color)


# 각 이모티콘 그리기 함수 -------------------------------------------------
INK = (60, 50, 70, 255)


def draw_smile(d):
    head(d, (255, 224, 130, 255), (245, 196, 80, 255))
    ellipse(d, SIZE * 0.38, SIZE * 0.46, SIZE * 0.035, SIZE * 0.045, fill=INK)
    ellipse(d, SIZE * 0.62, SIZE * 0.46, SIZE * 0.035, SIZE * 0.045, fill=INK)
    arc(d, SIZE / 2, SIZE * 0.52, SIZE * 0.16, SIZE * 0.14, 20, 160, INK, 7)
    blush(d, (255, 150, 150, 110))


def draw_wink(d):
    head(d, (255, 192, 203, 255), (240, 160, 175, 255))
    ellipse(d, SIZE * 0.38, SIZE * 0.46, SIZE * 0.035, SIZE * 0.045, fill=INK)
    line(d, SIZE * 0.565, SIZE * 0.45, SIZE * 0.655, SIZE * 0.45, INK, 7)  # 윙크
    arc(d, SIZE / 2, SIZE * 0.53, SIZE * 0.14, SIZE * 0.12, 20, 160, INK, 7)
    blush(d, (255, 120, 140, 120))


def draw_heart_eyes(d):
    head(d, (255, 170, 165, 255), (240, 140, 135, 255))
    heart(d, SIZE * 0.38, SIZE * 0.46, SIZE * 0.06, (220, 40, 70, 255))
    heart(d, SIZE * 0.62, SIZE * 0.46, SIZE * 0.06, (220, 40, 70, 255))
    arc(d, SIZE / 2, SIZE * 0.55, SIZE * 0.14, SIZE * 0.13, 15, 165, INK, 7)


def draw_laugh(d):
    head(d, (255, 200, 120, 255), (240, 170, 90, 255))
    # ^ ^ 눈
    arc(d, SIZE * 0.38, SIZE * 0.50, SIZE * 0.05, SIZE * 0.05, 200, 340, INK, 7)
    arc(d, SIZE * 0.62, SIZE * 0.50, SIZE * 0.05, SIZE * 0.05, 200, 340, INK, 7)
    # 활짝 웃는 입
    d.pieslice(_c(SIZE / 2 - SIZE * 0.15, SIZE * 0.50, SIZE / 2 + SIZE * 0.15, SIZE * 0.68),
               10, 170, fill=INK)
    blush(d, (255, 140, 140, 110))


def draw_surprise(d):
    head(d, (150, 210, 245, 255), (110, 185, 230, 255))
    ellipse(d, SIZE * 0.38, SIZE * 0.46, SIZE * 0.055, SIZE * 0.065, fill=(255, 255, 255, 255), outline=INK, width=4)
    ellipse(d, SIZE * 0.62, SIZE * 0.46, SIZE * 0.055, SIZE * 0.065, fill=(255, 255, 255, 255), outline=INK, width=4)
    ellipse(d, SIZE * 0.38, SIZE * 0.47, SIZE * 0.02, SIZE * 0.025, fill=INK)
    ellipse(d, SIZE * 0.62, SIZE * 0.47, SIZE * 0.02, SIZE * 0.025, fill=INK)
    ellipse(d, SIZE / 2, SIZE * 0.62, SIZE * 0.05, SIZE * 0.06, fill=INK)


def draw_love(d):
    head(d, (210, 190, 245, 255), (185, 160, 230, 255))
    ellipse(d, SIZE * 0.38, SIZE * 0.46, SIZE * 0.035, SIZE * 0.045, fill=INK)
    ellipse(d, SIZE * 0.62, SIZE * 0.46, SIZE * 0.035, SIZE * 0.045, fill=INK)
    arc(d, SIZE / 2, SIZE * 0.53, SIZE * 0.13, SIZE * 0.12, 20, 160, INK, 7)
    blush(d, (255, 130, 160, 150))
    heart(d, SIZE * 0.78, SIZE * 0.30, SIZE * 0.05, (230, 80, 110, 255))


def draw_sleepy(d):
    head(d, (180, 195, 240, 255), (150, 170, 225, 255))
    arc(d, SIZE * 0.38, SIZE * 0.47, SIZE * 0.05, SIZE * 0.04, 20, 160, INK, 6)
    arc(d, SIZE * 0.62, SIZE * 0.47, SIZE * 0.05, SIZE * 0.04, 20, 160, INK, 6)
    ellipse(d, SIZE / 2, SIZE * 0.60, SIZE * 0.025, SIZE * 0.03, fill=INK)
    # Z z
    for (zx, zy, zs) in [(SIZE * 0.74, SIZE * 0.30, 0.05), (SIZE * 0.82, SIZE * 0.22, 0.035)]:
        line(d, zx - SIZE * zs, zy - SIZE * zs, zx + SIZE * zs, zy - SIZE * zs, INK, 5)
        line(d, zx + SIZE * zs, zy - SIZE * zs, zx - SIZE * zs, zy + SIZE * zs, INK, 5)
        line(d, zx - SIZE * zs, zy + SIZE * zs, zx + SIZE * zs, zy + SIZE * zs, INK, 5)


def draw_cool(d):
    head(d, (130, 215, 200, 255), (95, 190, 175, 255))
    # 선글라스
    d.rounded_rectangle(_c(SIZE * 0.30, SIZE * 0.42, SIZE * 0.47, SIZE * 0.52), radius=10 * SS, fill=INK)
    d.rounded_rectangle(_c(SIZE * 0.53, SIZE * 0.42, SIZE * 0.70, SIZE * 0.52), radius=10 * SS, fill=INK)
    line(d, SIZE * 0.47, SIZE * 0.45, SIZE * 0.53, SIZE * 0.45, INK, 6)
    # 살짝 미소
    arc(d, SIZE * 0.54, SIZE * 0.58, SIZE * 0.10, SIZE * 0.09, 10, 90, INK, 7)


def draw_excited(d):
    head(d, (170, 230, 170, 255), (135, 205, 135, 255))
    star(d, SIZE * 0.38, SIZE * 0.46, SIZE * 0.07, (255, 205, 60, 255))
    star(d, SIZE * 0.62, SIZE * 0.46, SIZE * 0.07, (255, 205, 60, 255))
    d.pieslice(_c(SIZE / 2 - SIZE * 0.16, SIZE * 0.52, SIZE / 2 + SIZE * 0.16, SIZE * 0.70),
               10, 170, fill=INK)


def draw_angel(d):
    head(d, (255, 245, 220, 255), (235, 220, 185, 255))
    # 후광
    ellipse(d, SIZE / 2, SIZE * 0.16, SIZE * 0.13, SIZE * 0.04, outline=(255, 215, 90, 255), width=6)
    ellipse(d, SIZE * 0.38, SIZE * 0.47, SIZE * 0.035, SIZE * 0.045, fill=INK)
    ellipse(d, SIZE * 0.62, SIZE * 0.47, SIZE * 0.035, SIZE * 0.045, fill=INK)
    arc(d, SIZE / 2, SIZE * 0.54, SIZE * 0.12, SIZE * 0.11, 20, 160, INK, 7)
    blush(d, (255, 170, 170, 110))


CUTE = [
    ('방긋이',   draw_smile),
    ('윙크냥',   draw_wink),
    ('하트뿅',   draw_heart_eyes),
    ('헤헤웃음', draw_laugh),
    ('깜짝이',   draw_surprise),
    ('사랑둥이', draw_love),
    ('새근새근', draw_sleepy),
    ('멋쟁이',   draw_cool),
    ('신나라',   draw_excited),
    ('천사화창', draw_angel),
]


def render(draw_fn) -> bytes:
    img, d = _new_canvas()
    draw_fn(d)
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def render_techchang() -> bytes:
    """테크창 로고를 둥근 배경 위에 올린 이모티콘."""
    size = SIZE
    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    # 부드러운 인디고 원형 배경
    pad = int(size * 0.06)
    d.ellipse((pad, pad, size - pad, size - pad), fill=(238, 242, 255, 255),
              outline=(79, 70, 229, 255), width=max(3, size // 120))

    logo_path = settings.BASE_DIR / 'static' / 'images' / 'techwindow-logo.png'
    if logo_path.exists():
        logo = Image.open(logo_path).convert('RGBA')
        target = int(size * 0.62)
        logo.thumbnail((target, target), Image.LANCZOS)
        ox = (size - logo.width) // 2
        oy = (size - logo.height) // 2
        canvas.paste(logo, (ox, oy), logo)
    buf = BytesIO()
    canvas.save(buf, 'PNG')
    return buf.getvalue()


class Command(BaseCommand):
    help = '포인트로 구매하는 이모티콘 시드 데이터를 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='이미 존재해도 이미지/가격을 다시 생성')

    def handle(self, *args, **options):
        from common.models import Emoticon
        force = options['force']

        created_n = updated_n = skipped_n = 0

        def upsert(name, price, data, slug):
            nonlocal created_n, updated_n, skipped_n
            obj, created = Emoticon.objects.get_or_create(
                name=name, defaults={'price': price, 'is_available': True})
            if created:
                obj.image.save(f'{slug}.png', ContentFile(data), save=False)
                obj.price = price
                obj.is_available = True
                obj.save()
                created_n += 1
                self.stdout.write(self.style.SUCCESS(f'  생성: {name} ({price}P)'))
            elif force:
                obj.image.save(f'{slug}.png', ContentFile(data), save=False)
                obj.price = price
                obj.is_available = True
                obj.save()
                updated_n += 1
                self.stdout.write(f'  갱신: {name} ({price}P)')
            else:
                skipped_n += 1
                self.stdout.write(f'  건너뜀(이미 있음): {name}')

        self.stdout.write('귀여운 이모티콘 생성 중...')
        for idx, (name, fn) in enumerate(CUTE, 1):
            upsert(name, CUTE_PRICE, render(fn), f'cute_{idx:02d}')

        self.stdout.write('테크창 이모티콘 생성 중...')
        upsert('테크창', TECH_PRICE, render_techchang(), 'techchang')

        self.stdout.write(self.style.SUCCESS(
            f'\n완료 - 생성 {created_n} / 갱신 {updated_n} / 건너뜀 {skipped_n}'))
