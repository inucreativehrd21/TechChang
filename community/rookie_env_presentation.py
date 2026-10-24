"""경기 환경의 화면용 정보. 난수·특성 부여·공개·경기 계산에는 관여하지 않아요."""
from . import rookie_env as Env

TRAIT_ICONS = {
    'rain_man': 'rain', 'summer_man': 'sun', 'home_tiger': 'home', 'road_reaper': 'road',
    'night_owl': 'moon', 'dome_kid': 'dome', 'big_stage': 'crowd', 'cold_weak': 'cold',
    'heat_weak': 'heat', 'october': 'autumn', 'global': 'korea',
}
WEAK = {'cold_weak', 'heat_weak'}
ROUTINE_ICONS = {'balance': 'balance', 'travel': 'road', 'heat': 'heat', 'weather': 'rain', 'night': 'moon', 'park': 'dome'}
CONDITION_ICONS = {
    '홈': 'home', '원정': 'road', '중립 경기(대회)': 'field', '주간': 'sun', '야간': 'moon',
    '맑음': 'sun', '흐림': 'cloud', '비': 'rain', '폭염': 'heat', '한파': 'cold', '강풍': 'wind',
    '돔 구장': 'dome', '타자 친화 구장': 'bat', '투수 친화 구장': 'target', '보통 구장': 'field',
    '여름(7·8월)': 'sun', '만원 관중': 'crowd',
}


def trait(code):
    from .rookie_lite import TRAITS
    name, desc = TRAITS[code][:2]
    out = {'key': code, 'name': name, 'desc': desc}
    if code in Env.COND_TRAITS:
        out.update(icon=TRAIT_ICONS[code], condition=True, weak=code in WEAK)
    return out


def visible_traits(c):
    from .rookie_lite import TRAITS
    if Env.enabled():
        return [trait(t) for t in c.traits_seen or [] if t in TRAITS]
    return [{'name': TRAITS[t][0], 'desc': TRAITS[t][1]} for t in c.traits_seen or [] if t in TRAITS]


def discoveries(c, season):
    """이미 공개된 특성만 읽어요. 큰 경기·스카우팅 소식에만 남은 발견도 포함해요."""
    if not Env.enabled() or season is None:
        return []
    revealed = (season.env or {}).get('revealed') or []
    news = season.news or []
    out = []
    for code in dict.fromkeys(c.traits_seen or []):
        if code not in Env.COND_TRAITS:
            continue
        name = Env.COND_TRAITS[code][0]
        prefix = f'숨은 특성 발견 — {name}:'
        evidence = next((n[len(prefix):].strip() for n in news if n.startswith(prefix)), '')
        scouted = any(n.startswith('스카우팅 리포트 — 숨은 특성:') and name in n for n in news)
        if code in revealed or evidence or scouted:
            out.append(dict(trait(code), evidence=evidence or ('스카우팅 리포트에서 드러났어요.' if scouted else '시즌 기록에서 내 성향을 발견했어요.')))
    return out


def split_groups(role, rows):
    groups = [('홈과 원정', ('홈', '원정', '중립 경기(대회)')), ('낮과 밤', ('주간', '야간')),
              ('날씨', ('맑음', '흐림', '비', '폭염', '한파', '강풍', '강풍(뒷바람)', '강풍(맞바람)')),
              ('구장', ('돔 구장', '타자 친화 구장', '투수 친화 구장', '보통 구장')),
              ('계절과 관중', ('여름(7·8월)', '만원 관중'))]
    out = []
    for label, keys in groups:
        items = []
        for row in rows:
            if row['key'] not in keys:
                continue
            try:
                rate = float(row['rate'])
            except (TypeError, ValueError):
                rate = 0
            items.append(dict(row, icon=CONDITION_ICONS.get(row['key'], 'wind'), small=row['games'] < Env.REVEAL_MIN_GAMES,
                              width=round(max(0, min(100, rate * (200 if role == 'batter' else 10))), 1)))
        if items:
            out.append({'label': label, 'rows': items})
    return out


def game_conditions(env):
    if not env:
        return []
    weather, park = env.get('weather'), env.get('park')
    items = []
    if weather:
        items.append({'label': weather, 'icon': 'dome' if weather == '돔' else CONDITION_ICONS.get(weather, 'cloud')})
    if env.get('wind') and weather == '강풍':
        items.append({'label': '뒷바람' if env['wind'] == 'out' else '맞바람', 'icon': 'wind'})
    if env.get('time'):
        items.append({'label': env['time'], 'icon': 'moon' if env['time'] == '야간' else 'sun'})
    if park in Env.PARK_LABEL and not (weather == '돔' and park == 'dome'):
        label = Env.PARK_LABEL[park]
        items.append({'label': label, 'icon': CONDITION_ICONS[label]})
    if env.get('crowd'):
        items.append({'label': env['crowd'] + ' 관중', 'icon': 'crowd'})
    return items


def preview_context(role='batter'):
    """디자인 미리보기용 가상 기록. 선수·세션·커리어 난수를 사용하지 않아요."""
    from types import SimpleNamespace
    role = role if role in ('batter', 'pitcher') else 'batter'
    splits = {}
    for i, key in enumerate(Env.SPLIT_ORDER):
        games = 5 if key == '한파' else 12 + i * 3
        if role == 'batter':
            splits[key] = dict(g_env=games, g=games, ab=games*4, pa=games*4+games//2,
                               h=round(games*4*(.25+(i%5)*.018)), hr=games//5, bb=games//2, so=games,
                               **{'2b': games//3, '3b': 1})
        else:
            splits[key] = dict(g_env=games, g=games, gs=games, outs=games*18, er=round(games*(1.4+(i%5)*.25)),
                               r=games*2, so=games*6, bb=games*2, h=games*5)
    rows = Env.split_rows(role, splits)
    routines = [dict(r, icon=ROUTINE_ICONS[r['key']]) for r in Env.routine_choices()]
    return dict(c=SimpleNamespace(role=role), routines=routines,
                forecast={'park': '투수 친화 구장', 'away': 72, 'night': 112, 'rain': 24, 'heat': 9},
                env_rows=rows, env_groups=split_groups(role, rows), env_routine='궂은 날 대비',
                traits=[trait(t) for t in Env.COND_TRAITS], env_enabled=True)
