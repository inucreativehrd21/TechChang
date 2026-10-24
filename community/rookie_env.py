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
    from django.conf import settings
    v = getattr(settings, 'ROOKIE_ENV_ENABLED', os.environ.get('ROOKIE_ENV_ENABLED', 'false'))
    return v is True or str(v).lower() == 'true'


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
               '강풍(맞바람)', '돔 구장', '타자 친화 구장', '투수 친화 구장', '보통 구장')


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
