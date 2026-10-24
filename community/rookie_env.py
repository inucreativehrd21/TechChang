"""경기 환경(날씨·홈/원정·낮밤·구장·관중)과 경기 전 대비(시즌 루틴·미디어데이) — 라이트·익스트림(2026-10-25 사용자 결정).

원칙:
- **환경은 커리어 난수로 진짜로 뽑는다**(같은 경기를 다시 열어도 같다). 시즌 난수는 쓰지 않는 파생 난수라
  시즌의 다른 난수 순서를 밀지 않는다. 정식 모드는 리그·날짜 기준 고정(후속).
- 보정은 그 경기에만, 작게(±1~3). 날씨는 월별 확률 + 연속성(비 온 다음 날은 또 흐리기 쉽다), 돔은 날씨가 없다.
- 구장은 널리 알려진 것만 성향을 준다(돔·타자 친화·투수 친화). 나머지는 중립.
- 같은 환경이 양 팀에 똑같이 미치는 것(비 오는 날 모두 조금 못 친다)은 상대적인 차이가 아니라서, 득점 환경(k)으로만
  다룬다 — 타자는 k 만큼 파워·컨택이 오르고, 투수는 상대가 그만큼 잘 치므로 구위가 내려간다.
- `ROOKIE_ENV_ENABLED`(설정 또는 환경 변수, 기본 꺼짐)가 꺼져 있으면 아무 일도 하지 않는다.
"""
from __future__ import annotations

import os
import random

WEATHERS = ('맑음', '흐림', '비', '폭염', '한파', '강풍')
# 달마다 날씨 확률(맑음, 흐림, 비, 폭염, 한파, 강풍) — 한국 프로야구 시즌의 결
MONTH_WEATHER = {
    3: (.45, .25, .10, .00, .15, .05), 4: (.50, .25, .12, .00, .08, .05), 5: (.55, .25, .12, .00, .00, .08),
    6: (.42, .30, .20, .03, .00, .05), 7: (.30, .30, .25, .12, .00, .03), 8: (.40, .20, .15, .22, .00, .03),
    9: (.55, .25, .12, .00, .00, .08), 10: (.58, .25, .10, .00, .04, .03), 11: (.45, .25, .08, .00, .17, .05),
}
STICKY = .40                       # 앞 경기 날씨가 그대로 이어질 확률(장마·무더위는 며칠 간다)
PARK = {                           # 'dome' 돔, 'hitter' 타자 친화, 'pitcher' 투수 친화 — 나머지는 중립
    'kiwoom': 'dome', 'lg': 'pitcher', 'doosan': 'pitcher', 'samsung': 'hitter', 'ssg': 'hitter',
    'col': 'hitter', 'cin': 'hitter', 'bos': 'hitter', 'sd': 'pitcher', 'sf': 'pitcher',
    'sea': 'dome', 'tb': 'dome', 'hou': 'dome', 'mil': 'dome', 'mia': 'dome', 'ari': 'dome', 'tex': 'dome', 'tor': 'dome',
    'yomiuri': 'dome', 'chunichi': 'dome', 'orix': 'dome', 'softbank': 'dome', 'nipponham': 'dome', 'seibu': 'dome',
}
PARK_LABEL = {'dome': '돔 구장', 'hitter': '타자 친화 구장', 'pitcher': '투수 친화 구장', 'neutral': '보통 구장'}
PARK_K = {'hitter': 2.0, 'pitcher': -2.0, 'dome': 0.0, 'neutral': 0.0}
WEATHER_K = {'맑음': 0.0, '흐림': 0.0, '비': -1.0, '폭염': 1.0, '한파': -2.0}
HOME_EDGE = 1.0                    # 홈 +1 · 원정 −1(내 주요 능력)

ROUTINES = {   # 시즌 루틴 — 평균 가치는 비슷하게(경기당 능력치 합 +0.5 안팎, 하네스로 맞춤), 어울리는 상황이 다르다
    'balance': ('컨디션 관리', '어떤 환경이든 손해를 25% 줄여요'),
    'travel': ('원정 루틴', '원정 경기의 손해가 절반으로 줄어요'),
    'heat': ('여름 체력 관리', '폭염 손해가 없어지고 7·8월 경기 +0.5'),
    'weather': ('궂은 날 대비', '흐림·비·한파·강풍 경기 +0.5, 궂은 날씨 손해는 절반'),
    'night': ('야간 집중', '야간 경기 +0.6, 주간 경기 −1'),
    'park': ('홈 구장 맞춤', '홈 구장 성향의 효과가 1.5배(좋은 쪽도 나쁜 쪽도)'),
}
DEFAULT_ROUTINE = 'balance'


def enabled() -> bool:
    from common.game_controls import enabled as control_enabled
    return control_enabled('ROOKIE_ENV_ENABLED')


def _rng(c, tag: str) -> random.Random:
    return random.Random(f'env:{getattr(c, "pk", 0)}:{getattr(c, "name", "")}:{getattr(c, "year", 0)}:{tag}')


def park_of(club: str) -> str:
    return PARK.get(club or '', 'neutral')


def month_of(chunk: int) -> int:
    return 4 + max(0, min(5, chunk))                       # 6구간 = 4~9월


def _weather(month: int, prev: str | None, r) -> str:
    probs = MONTH_WEATHER.get(month, MONTH_WEATHER[5])
    if prev and prev in WEATHERS and probs[WEATHERS.index(prev)] > 0 and r.random() < STICKY:
        return prev
    return r.choices(WEATHERS, probs)[0]


def season(c, code: str, club: str, games: int, fixtures=(), pro: bool = True, amateur_league: bool = False) -> list:
    """이번 시즌 모든 경기의 환경 — 커리어·연도·리그로 정해진 파생 난수(시즌 중 다시 불러도 같다)."""
    r = _rng(c, f'season:{code}:{club}')
    out, prev = [], None
    for i in range(games):
        chunk = i * 6 // max(1, games)
        month = month_of(chunk)
        if fixtures:
            fx = fixtures[i] if i < len(fixtures) else fixtures[-1]
            home = 'home' if fx.get('home') else 'away'
            park = park_of(club if fx.get('home') else fx.get('opponent'))
        elif amateur_league:
            home = ('home' if i % 2 == 0 else 'away') if chunk < 2 else 'neutral'   # 주말리그는 오가며, 대회는 중립 구장
            park = 'neutral'
        else:
            home, park = ('home' if i % 2 == 0 else 'away'), 'neutral'
        weather = '돔' if park == 'dome' else _weather(month, prev, r)
        if weather != '돔':
            prev = weather
        wind = (r.choice(('out', 'in')) if weather == '강풍' else '')
        night = pro and r.random() < .78
        crowd = (r.choices(('만원', '보통', '한산'), (.25, .55, .20))[0] if pro else '한산')
        out.append({'month': month, 'home': home, 'park': park, 'weather': weather, 'wind': wind,
                    'time': '야간' if night else '주간', 'crowd': crowd})
    return out


def _weather_k(env: dict) -> float:
    k = WEATHER_K.get(env['weather'], 0.0)
    if env['weather'] == '강풍':
        k += 2.0 if env.get('wind') == 'out' else -2.0
    return k


def run_env(env: dict) -> float:
    """득점 환경(k) — 양수면 타자에게 유리(구장 몫 + 날씨 몫)."""
    return PARK_K.get(env['park'], 0.0) + _weather_k(env)


def delta(role: str, env: dict, routine: str = DEFAULT_ROUTINE) -> dict:
    """이 경기에서 내 능력치에 더할 값 — 루틴이 맞으면 손해가 줄어든다."""
    k_park = PARK_K.get(env['park'], 0.0)
    if routine == 'park' and env['home'] == 'home':
        k_park *= 1.5
    k_w = _weather_k(env)
    harmful = k_w < 0 if role == 'batter' else k_w > 0                 # 투수는 득점 환경이 오르면 손해
    if routine == 'weather' and harmful and env['weather'] in ('비', '한파', '강풍'):
        k_w *= .5
    k = k_park + k_w
    edge = HOME_EDGE if env['home'] == 'home' else -HOME_EDGE if env['home'] == 'away' else 0.0
    if routine == 'travel' and env['home'] == 'away':
        edge = -HOME_EDGE * .5
    if role == 'batter':
        out = {'power': k, 'contact': k * .5 + edge, 'eye': edge}
    else:
        out = {'velocity': -k * .75, 'breaking': -k * .75, 'control': edge, 'mental': edge}
        if env['weather'] == '폭염':
            out['stamina'] = -3.0
    main = ('contact', 'power') if role == 'batter' else ('control', 'mental')
    steady = ('contact', 'eye') if role == 'batter' else ('control', 'mental')
    if routine == 'heat':
        if env['weather'] == '폭염':
            out = {key: max(0.0, v) for key, v in out.items()}
        if env['month'] in (7, 8):
            for key in main:
                out[key] = out.get(key, 0.0) + .5
    if routine == 'weather' and env['weather'] in ('흐림', '비', '한파', '강풍'):
        for key in steady:
            out[key] = out.get(key, 0.0) + .5
    if routine == 'night':
        bump = .6 if env['time'] == '야간' else -1.0
        for key in (('contact', 'eye') if role == 'batter' else ('control', 'mental')):
            out[key] = out.get(key, 0.0) + bump
    if routine == 'balance':
        out = {key: (v * .75 if v < 0 else v) for key, v in out.items()}
    return {key: round(v, 2) for key, v in out.items() if v}


def apply(stats: dict, d: dict) -> dict:
    if not d:
        return stats
    return {key: (float(v) + d.get(key, 0.0) if key in d else v) for key, v in stats.items()}


# ───────────────────────────── 조건별 성적
def buckets(env: dict) -> list:
    """이 경기가 들어갈 칸들 — 홈/원정, 낮/밤, 날씨, 구장 성향."""
    out = [{'home': '홈', 'away': '원정', 'neutral': '중립 경기(대회)'}[env['home']], env['time'],
           PARK_LABEL.get(env['park'], '보통 구장')]
    if env['weather'] != '돔':                                # 돔은 구장 칸으로만 센다(한 경기를 두 번 세지 않게)
        out.insert(2, env['weather'])
    if env.get('month') in (7, 8):
        out.append('여름(7·8월)')
    if env.get('crowd') == '만원':
        out.append('만원 관중')
    if env['weather'] == '강풍':
        out.append('강풍(뒷바람)' if env.get('wind') == 'out' else '강풍(맞바람)')
    return out


def add_split(store: dict, env: dict, line: dict) -> dict:
    from . import rookie_league as L
    for key in buckets(env):
        store[key] = L.add(store.get(key, {}), line)
        store[key]['g_env'] = store[key].get('g_env', 0) + 1
    return store


SPLIT_ORDER = ('홈', '원정', '중립 경기(대회)', '주간', '야간', '맑음', '흐림', '비', '폭염', '한파', '강풍', '강풍(뒷바람)',
               '강풍(맞바람)', '돔 구장', '타자 친화 구장', '투수 친화 구장', '보통 구장', '여름(7·8월)', '만원 관중')


def split_rows(role: str, splits: dict) -> list:
    """화면용 — 칸마다 경기 수와 한 줄 기록."""
    from . import rookie_league as L
    rows = []
    for key in SPLIT_ORDER:
        t = (splits or {}).get(key)
        if not t:
            continue
        line = L.bat_summary(t) if role == 'batter' else L.pit_summary(t)
        view = L.line_view(role, t)
        rows.append({'key': key, 'games': t.get('g_env', 0), 'line': line,
                     'rate': view.get('avg_text') if role == 'batter' else view.get('era_text'),
                     'rate_label': '타율' if role == 'batter' else '평균자책점'})
    return rows


# ───────────────────────────── 시즌 루틴 고르기 — 비시즌 화면의 '올 시즌 예보'
def forecast(c, code: str, games: int, fixtures=()) -> dict:
    """비시즌에 루틴을 고를 근거 — 내 구장 성향, 원정·야간 비율, 폭염·비 예상 경기 수(지난 경기와 같은 방식의 기대값)."""
    probs = [MONTH_WEATHER[month_of(j)] for j in range(6)]
    per_chunk = games / 6
    rain = round(sum(p[2] for p in probs) * per_chunk)
    heat = round(sum(p[3] for p in probs) * per_chunk)
    away = sum(1 for f in fixtures if not f.get('home')) if fixtures else games // 2
    return {'park': PARK_LABEL[park_of(getattr(c, 'club', ''))], 'away': away, 'games': games,
            'night': round(games * .78) if fixtures else 0, 'rain': rain, 'heat': heat}


ROLE_HINT = {}


def routine_choices(selected: str = '', role: str = 'batter') -> list:
    sel = selected if selected in ROUTINES else DEFAULT_ROUTINE
    return [{'key': k, 'label': v[0], 'hint': ROLE_HINT.get((k, role), v[1]), 'checked': k == sel} for k, v in ROUTINES.items()]


# ───────────────────────────── 미디어데이·기자회견(큰 경기 직전)
MEDIA = {   # 효과는 기존 수치(자신감·감독 신뢰·인기)로만 — 우승 확률을 직접 바꾸지 않는다
    'humble': ('차분하게 각오를 다질게요', '자신감 +3 · 감독 신뢰 +2', {'confidence': 3}, 2),
    'bold': ('우승을 선언할게요', '인기 +6 · 자신감 +5 — 결과에 따라 기사 반응이 크게 갈려요', {'fame': 6, 'confidence': 5}, 0),
    'team': ('동료들에게 공을 돌릴게요', '감독 신뢰 +5 · 인기 +1', {'fame': 1}, 5),
    'quiet': ('말을 아낄게요', '변화가 거의 없어요 · 인기 −2', {'fame': -2}, 0),
}


def media_view(stage: str, scope: str) -> dict:
    title = '대표팀 기자회견' if scope == 'intl' else '미디어데이'
    text = (f"{stage}을 앞두고 기자들이 모였어요. 대표팀의 각오를 한마디 해 달래요." if scope == 'intl'
            else f"{stage}을 앞둔 미디어데이예요. 마이크가 내 앞에 놓였어요. 어떤 각오를 말할까요?")
    return {'what': 'mediaday', 'title': title, 'text': text, 'stage': stage, 'scope': scope,
            'choices': [{'key': k, 'label': v[0], 'hint': v[1]} for k, v in MEDIA.items()]}


def media_title(choice: str, name: str, stage: str) -> str:
    return {'humble': f"{name}, {stage} 앞두고 ‘한 경기씩 최선을’",
            'bold': f"{name}, {stage} 앞두고 ‘우승은 우리 것’ 선언",
            'team': f"{name} ‘동료들 덕분에 여기까지’…{stage} 출사표",
            'quiet': f"{name}, {stage} 미디어데이서 말 아껴"}.get(choice, '')


def decorate_series(c, doc: dict) -> dict:
    """시리즈 기록의 경기마다 환경을 붙인다(가을·국제대회는 10~11월 날씨). 결과는 바꾸지 않는다 — 전광판 표시용."""
    r = _rng(c, f"series:{doc.get('kind')}:{doc.get('key')}")
    prev = None
    month = 11 if doc.get('kind') == 'intl' and doc.get('key') == 'premier12' else 10 if doc.get('kind') == 'post' else 8
    for rd in doc.get('rounds') or []:
        for g in rd.get('games') or []:
            club = (doc.get('team') or {}).get('code') if g.get('home') == 'us' else (rd.get('opponent') or {}).get('code')
            park = park_of(club or '') if doc.get('kind') == 'post' else 'neutral'
            weather = '돔' if park == 'dome' else _weather(month, prev, r)
            prev = weather if weather != '돔' else prev
            g['env'] = {'weather': weather, 'wind': r.choice(('out', 'in')) if weather == '강풍' else '',
                        'time': '야간' if doc.get('kind') == 'post' and r.random() < .8 else '주간',
                        'park': park, 'crowd': '만원' if doc.get('kind') != 'amateur' else '보통'}
    return doc


# ───────────────────────────── 조건부 특성(2026-10-25) — 환경에 따라 오르고 내리는 숨은 특성
# 기존 특성 추첨(roll_traits)과 따로, 커리어 파생 난수로 붙인다(기존 추첨 분포·시즌 난수 순서 불변).
# 효과는 주요 능력 두 개(타자 컨택·파워, 투수 제구·변화구)에 같은 값. 경기당 기대 가치는 작게(하네스로 맞춤).
COND_TRAITS = {   # 코드: (이름, 설명, [(조건, 값)…])
    'rain_man': ('비 오는 날의 사나이', '비 오는 날 +3 · 맑은 날 −0.5', (('weather:비', 3.0), ('weather:맑음', -.5))),
    'summer_man': ('여름 사나이', '7·8월 +2 · 4월 −2.5', (('month:7', 2.0), ('month:8', 2.0), ('month:4', -2.5))),
    'home_tiger': ('안방 호랑이', '홈 경기 +2 · 원정 경기 −1.5', (('home:home', 2.0), ('home:away', -1.5))),
    'road_reaper': ('원정 저승사자', '원정 경기 +2 · 홈 경기 −1.5', (('home:away', 2.0), ('home:home', -1.5))),
    'night_owl': ('야행성', '야간 경기 +1 · 주간 경기 −3', (('time:야간', 1.0), ('time:주간', -3.0))),
    'dome_kid': ('돔구장 체질', '돔 구장 +1 · 바깥 구장 −0.3', (('park:dome', 1.0), ('park:open', -.3))),
    'big_stage': ('만원 관중 체질', '만원 관중 앞 +2.5 · 한산한 경기 −2.5', (('crowd:만원', 2.5), ('crowd:한산', -2.5))),
    'cold_weak': ('추위에 약함', '한파 경기 −4', (('weather:한파', -4.0),)),
    'heat_weak': ('더위에 약함', '폭염 경기 −3', (('weather:폭염', -3.0),)),
    'october': ('가을 야구 사나이', '가을야구 결승의 결정적 순간·시리즈 +4', ()),
    'global': ('국제대회 체질', '국제대회 경기·결승 +3', ()),
}
BIG_TRAITS = {'october': ('post', 4.0), 'global': ('intl', 3.0)}
COND_WEIGHT = {'cold_weak': .8, 'heat_weak': .8, 'october': .6, 'global': .6}
COND_EXCLUSIVE = ({'home_tiger', 'road_reaper'},)
REVEAL_BUCKET = {'rain_man': '비', 'summer_man': '여름(7·8월)', 'home_tiger': '홈', 'road_reaper': '원정',
                 'night_owl': '야간', 'dome_kid': '돔 구장', 'big_stage': '만원 관중', 'cold_weak': '한파',
                 'heat_weak': '폭염'}
REVEAL_MIN_GAMES = 8


def main_stats(role: str) -> tuple:
    return ('contact', 'power') if role == 'batter' else ('control', 'breaking')


def _match(cond: str, env: dict) -> bool:
    kind, value = cond.split(':', 1)
    if kind == 'month':
        return env['month'] == int(value)
    if kind == 'park':
        return (env['park'] == 'dome') if value == 'dome' else (env['park'] != 'dome')
    return env.get(kind) == value


def cond_delta(role: str, env: dict, traits) -> dict:
    """이 경기에서 조건부 특성이 더할 값."""
    total = 0.0
    for t in traits or ():
        for cond, value in (COND_TRAITS.get(t) or ('', '', ()))[2]:
            if _match(cond, env):
                total += value
    return {k: total for k in main_stats(role)} if total else {}


def big_delta(role: str, scope: str, traits) -> dict:
    """큰 경기(scope 'post' 가을야구 결승·'intl' 국제대회)에서 특성이 더할 값."""
    total = sum(v for t, (s, v) in BIG_TRAITS.items() if s == scope and t in (traits or ()))
    return {k: total for k in main_stats(role)} if total else {}


def merge(*deltas) -> dict:
    out = {}
    for d in deltas:
        for k, v in (d or {}).items():
            out[k] = round(out.get(k, 0.0) + v, 2)
    return {k: v for k, v in out.items() if v}


def roll_cond(c) -> list:
    """조건부 특성 추첨 — 45%는 하나, 10%는 둘(같은 커리어면 언제 불러도 같다)."""
    r = random.Random(f'cond-trait:{getattr(c, "pk", 0)}:{getattr(c, "name", "")}')
    n = r.choices((0, 1, 2), (.45, .45, .10))[0]
    pool = list(COND_TRAITS)
    got = []
    while len(got) < n and pool:
        t = r.choices(pool, [COND_WEIGHT.get(x, 1.0) for x in pool])[0]
        pool.remove(t)
        if any(ex <= {t, *got} for ex in COND_EXCLUSIVE):
            continue
        got.append(t)
    return got


def ensure_traits(c) -> list:
    """스위치를 켠 뒤 첫 시즌에 한 번 — 새 선수도 기존 선수도 같은 확률. 붙은 특성은 숨은 특성(c.traits)에 더한다."""
    flags = dict(c.flags or {})
    if flags.get('cond_rolled'):
        return []
    got = [t for t in roll_cond(c) if t not in (c.traits or [])]
    c.traits = list(c.traits or []) + got
    flags['cond_rolled'] = True
    c.flags = flags
    return got


def reveal(c, splits: dict, totals: dict) -> list:
    """시즌 끝 — 조건이 충분히 쌓인 숨은 조건부 특성을 실제 기록과 함께 드러낸다. [(코드, 문장)]"""
    from . import rookie_league as L
    out = []
    seen = set(c.traits_seen or [])
    for t in c.traits or ():
        bucket = REVEAL_BUCKET.get(t)
        if t in seen or not bucket:
            continue
        line = (splits or {}).get(bucket) or {}
        if line.get('g_env', 0) < REVEAL_MIN_GAMES:
            continue
        v, base = L.line_view(c.role, line), L.line_view(c.role, totals or {})
        if c.role == 'batter':
            stat = f"{bucket} 타율 {v.get('avg_text', '-')}(시즌 {base.get('avg_text', '-')})"
        else:
            stat = f"{bucket} 평균자책점 {v.get('era_text', '-')}(시즌 {base.get('era_text', '-')})"
        out.append((t, f"숨은 특성 발견 — {COND_TRAITS[t][0]}: {stat}"))
    return out
