"""야구선수 키우기 은퇴 카드 공용 — 라이트·정식 판이 같이 쓴다(2026-10-19 사용자 요청: 정식 판에도 라이트의 좋은 기능을).

구단색(_palette)·유니폼 어깨 이름(_jersey_name)·이미지 찍기(render_png, png_response)와 정식 판 카드(main_card).
카드 화면은 templates/community/games/_lite_retire.html(유니폼 등판), 이미지 틀은 lite_card_shot.html.
"""
import logging
import os
import threading
import colorsys

from django.conf import settings
from django.http import FileResponse, HttpResponse

from . import rookie_world as W

logger = logging.getLogger(__name__)


# 은퇴 카드 구단색(2026-10-19 사용자 요청: 구단별로 예쁘게) — (주색, 보조색, 핀스트라이프). KBO 는 구단마다 골라 두고,
# 나머지는 주색에서 만든다. 유니폼은 흰 홈 유니폼, 글씨는 주색(밝은 주색이면 보조색) + 보조색 테두리.
KBO_TRIM = {'kia': ('#EA0029', '#06141F', False), 'kt': ('#231F20', '#EB1C24', False), 'lg': ('#C30452', '#231F20', True),
            'nc': ('#315288', '#C7A079', False), 'ssg': ('#CE0E2D', '#FFB81C', False), 'doosan': ('#131230', '#ED1C24', True),
            'lotte': ('#041E42', '#D00F31', False), 'samsung': ('#074CA1', '#B6BCC4', False),
            'kiwoom': ('#820024', '#B07F4A', False), 'hanwha': ('#FF6600', '#07111F', False)}
PINSTRIPES = {'nyy', 'phi', 'chc'}


def uniform_club(club, color):
    """새 이미지가 없는 구단은 색이 가까운 KBO 원단을 사용한다. 녹색·노랑은 중립 원단."""
    if club in KBO_TRIM:
        return club
    if club in PINSTRIPES:
        return 'doosan'
    rgb = tuple(int(color.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    if s < .35 or v < .22:
        return 'kt'
    if .15 < h < .48:  # 생성하지 않은 녹색·노랑 유니폼 대신 검정/흰 원단을 공유한다.
        return 'kt'
    def distance(code):
        c = KBO_TRIM[code][0].lstrip('#')
        ch, cs, cv = colorsys.rgb_to_hsv(*(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)))
        dh = min(abs(h - ch), 1 - abs(h - ch))
        return dh * 4 + abs(s - cs) * .2 + abs(v - cv) * .6
    return min(KBO_TRIM, key=distance)


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4   # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _palette(league: str, club: str) -> dict:
    """카드 색 — primary(배경·글씨), secondary(테두리·장식), ink(흰 유니폼 위 글씨), pin(핀스트라이프)."""
    if club in KBO_TRIM:
        primary, secondary, pin = KBO_TRIM[club]
    else:
        primary = W.club_color(league, club) or '#4f46e5'
        secondary = '#C8CDD6' if _lum(primary) < 0.25 else '#0E1130'
        pin = club in PINSTRIPES
    ink = primary if _lum(primary) < 0.4 else (secondary if _lum(secondary) < 0.4 else '#0E1130')
    trim = secondary if abs(_lum(secondary) - _lum(ink)) > 0.08 else '#ffffff'
    bg = primary if _lum(primary) < 0.45 else secondary            # 노랑처럼 밝은 주색은 바탕을 보조색으로(탁한 올리브가 되지 않게)
    source = uniform_club(club, primary) if club in W.PRO_TEAM else ''
    return {'primary': primary, 'secondary': secondary, 'ink': ink, 'trim': trim, 'pin': pin, 'bg': bg,
            'jersey_source': source, 'jersey_asset': f'img/rookie/uniforms/{source}.webp' if source else ''}


def _jersey_name(name: str) -> dict:
    """유니폼 어깨 이름 — 짧을수록 크게·넓게(유니폼 글씨처럼)."""
    n = len(name)
    size, spacing = ((23, 0.22) if n <= 3 else (20, 0.09) if n <= 5 else (16, 0.04) if n <= 7 else (12, 0.01) if n <= 10 else (10, 0))
    return {'size': size, 'spacing': spacing}


# ───────────────────────────── 은퇴 카드 이미지(SNS 에 올리는 PNG · 링크 미리보기)
# 서버의 headless Chromium(playwright — 연구실 위클리 카드뉴스와 같은 것)으로 카드 화면을 찍어 media/lite_cards 에 둔다.
# 은퇴 카드는 바뀌지 않으니 한 번 찍으면 계속 쓴다 — 디자인을 바꾸면 CARD_V 를 올린다.
CARD_V = 9                  # 최상위 리그 WAR와 하위 리그 평가를 구분한 카드
SHOTS = {'card': (432, 540, 2.5), 'og': (1200, 630, 1),       # 1080×1350(인스타 세로 피드) · 링크 미리보기 1200×630
         'story': (432, 768, 2.5)}                                  # 1080×1920 인스타그램 스토리(2026-10-19 사용자 요청)
_shot_lock = threading.Lock()


def _shot_path(pk, kind: str) -> str:
    return os.path.join(settings.MEDIA_ROOT, 'lite_cards', f'{pk}-{kind}-v{CARD_V}.png')


def render_png(html: str, size: tuple, out: str):
    """HTML 한 장을 PNG 로 — 정적 파일(/static/…)은 디스크에서 바로 넣어 준다(서버가 자기 자신을 부르지 않게)."""
    from django.contrib.staticfiles import finders
    from playwright.sync_api import sync_playwright
    w, h, scale = size

    def serve(route):
        path = route.request.url.split('://', 1)[-1].split('/', 1)[-1].split('?', 1)[0]
        found = finders.find(path[len('static/'):]) if path.startswith('static/') else None
        if not found and path.startswith('static/'):
            found = os.path.join(settings.STATIC_ROOT, path[len('static/'):])
        if found and os.path.exists(found):
            route.fulfill(path=found)
        else:
            route.fulfill(status=404, body='')
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--font-render-hinting=none'])   # 리눅스 힌팅이 작은 글씨를 'M VP'처럼 벌려서
        try:
            page = browser.new_page(viewport={'width': w, 'height': h}, device_scale_factor=scale)
            page.route('http://shot.local/**', serve)
            page.set_content(html, wait_until='load')
            page.evaluate('document.fonts.ready.then(() => true)')
            os.makedirs(os.path.dirname(out), exist_ok=True)
            tmp = out + '.tmp.png'
            page.screenshot(path=tmp, clip={'x': 0, 'y': 0, 'width': w, 'height': h})
            os.replace(tmp, out)
        finally:
            browser.close()


def png_response(key, kind: str, filename: str, download: bool, renderer, make_html):
    """카드 이미지 — 한 번 찍어 두고(media/lite_cards/<key>-<kind>-v<CARD_V>.png) 계속 쓴다. 못 찍으면 503.
    renderer 는 부르는 쪽 모듈의 render_png(테스트가 바꿔 끼울 수 있게)."""
    out = _shot_path(key, kind)
    if not os.path.exists(out):
        with _shot_lock:
            if not os.path.exists(out):
                try:
                    renderer(make_html(), SHOTS[kind], out)
                except Exception:
                    logger.exception('은퇴 카드 이미지를 만들지 못함 key=%s kind=%s', key, kind)
                    return HttpResponse('카드 이미지를 만들지 못했어요. 잠시 뒤 다시 시도해 주세요.', status=503,
                                        content_type='text/plain; charset=utf-8')
    resp = FileResponse(open(out, 'rb'), content_type='image/png', as_attachment=download, filename=filename)
    resp['Cache-Control'] = 'public, max-age=86400'
    return resp


# ───────────────────────────── 정식 판 은퇴 카드
FOCUS_EPITHET = {'contact': '안타 제조기', 'power': '거포', 'eye': '선구안의 달인', 'speed': '대도', 'defense': '수비 달인',
                 'velocity': '파이어볼러', 'control': '제구 마술사', 'breaking': '변화구 장인', 'stamina': '이닝이터',
                 'mental': '강심장'}


def _ym(d) -> str:
    return f'{d.year}.{d.month:02d}'


def main_card(p) -> dict:
    """정식 판 선수(은퇴) 카드 — 라이트 카드와 같은 꼴(_lite_retire.html)의 맥락. 통산 수입 대신 쌓은 TP(활동의 흔적)."""
    from django.utils import timezone

    from . import rookie as R
    from . import rookie_league as L
    from . import rookie_lite as X
    from .models import RookieAward, RookieSeasonStat
    from .rookie_legacy import _sum
    rows = sorted(RookieSeasonStat.objects.filter(player=p).select_related('season'),
                  key=lambda r: (r.season.number, W.level(r.league)))
    pro = [r for r in rows if W.is_pro(r.league)]
    total = _sum(r.totals for r in (pro or rows))
    line = L.line_view(p.role, total) if total else {}

    def n(k):
        return f"{int(line.get(k) or 0):,}"
    if p.role == 'pitcher':
        stats = [('경기', n('g')), ('승', n('w')), ('패', n('l')), ('세이브', n('sv')), ('평균자책점', line.get('era_text') or '-'),
                 ('탈삼진', n('so'))]
    else:
        stats = [('경기', n('g')), ('타율', line.get('avg_text') or '-'), ('안타', n('h')), ('홈런', n('hr')), ('타점', n('rbi')),
                 ('OPS', line.get('ops_text') or '-')]
    awards = list(RookieAward.objects.filter(player=p).values_list('kind', 'league'))
    mvp = sum(1 for k, _lg in awards if k == 'mvp')
    gg_by = {}
    for k, lg in awards:
        if k == 'gg':
            gg_by[lg] = gg_by.get(lg, 0) + 1
    gg = sum(gg_by.values())
    gg_label = L.AWARD_STYLE.get(max(gg_by, key=gg_by.get), {}).get('gg', '골든글러브') if gg_by else '골든글러브'
    titles = sum(1 for k, _lg in awards if k in ('title', 'ace'))
    best9 = p.logs.filter(kind='mile', text__contains='베스트 9').count()
    miles = p.logs.filter(kind='mile').exclude(text__contains='베스트 9').exclude(text__startswith='각성').count()
    best_ovr = round(max([p.best_ovr] + [r.best_ovr for r in rows]), 1)
    if mvp >= 2 or best_ovr >= 92:
        tier, tier_label = 'legend', '레전드'
    elif mvp or best_ovr >= 85 or gg + titles >= 4:
        tier, tier_label = 'star', '스타'
    elif any(r.league in W.TOP_LEAGUES for r in pro):
        tier, tier_label = 'pro', '프로'
    else:
        tier, tier_label = 'rookie', '루키'
    clubs = []
    for r in pro:
        name = W.club_short(r.league, r.team)
        if not clubs or clubs[-1] != name:
            clubs.append(name)
    # 커리어 하이 — 가장 높은 무대에서 제대로 뛴 시즌(타자 100타석·투수 30이닝) 가운데 WAR 최고
    full = [r for r in pro if (r.totals.get('outs', 0) >= 90 if p.role == 'pitcher' else r.totals.get('pa', 0) >= 100)]
    pick = max(full or pro or rows, key=lambda r: (W.level(r.league), r.war), default=None)
    best = ({'year': f'시즌 {pick.season.number}', 'league': W.short(pick.league), 'age': pick.age or p.age,
             'line': X._short(p.role, pick.totals), 'war': round(pick.war, 1)} if pick and pick.totals else None)
    ret = (p.career or {}).get('retired') or {}
    league, club = ret.get('league') or p.league, ret.get('club') or p.club
    team_name = W.club_label(league, club)
    prefix, _sp, nick = team_name.rpartition(' ')
    peak = max([r.league for r in rows] + [league], key=W.level)
    ep = FOCUS_EPITHET.get(p.focus, '')
    seasons = len({r.season_id for r in rows})
    end = timezone.localtime(p.retired_at) if p.retired_at else timezone.now()
    return {'palette': _palette(league, club), 'team_prefix': prefix, 'team_nick': nick or team_name,
            'jersey': _jersey_name(p.name), 'serial': f'{p.pk:04d}', 'tier': tier, 'tier_label': tier_label,
            'years': f'{_ym(timezone.localtime(p.created_at))}–{_ym(end)}', 'seasons': seasons, 'stats': stats,
            'keys': [('최상위 WAR', round(sum(r.war for r in pro if r.league in W.TOP_LEAGUES), 1)), ('최고 OVR', best_ovr), ('쌓은 TP', f'{p.tp_earned:,}')],
            'honors': [{'n': mvp, 'label': 'MVP'}, {'n': gg, 'label': gg_label}, {'n': titles, 'label': '타이틀'},
                       {'n': best9, 'label': '베스트 9'}, {'n': miles, 'label': '이정표'}],
            'best': best, 'clubs': clubs[:5], 'more_clubs': max(0, len(clubs) - 5), 'peak_short': W.short(peak),
            'epithet': ep, 'war': round(sum(r.war for r in pro), 1),
            'headline': {'tag': '[은퇴]', 'title': f"{'‘' + ep + '’ ' if ep else ''}{p.name}, {seasons}시즌 현역 마침표…박수 받으며 떠난다"},
            'identity': R.identity(p)}
