"""테크창 삼국지 — 장원 층(설계 7장): 객잔·도감 화면 묶음·장원 건물과 배치·명성·지나가는 거지. 방명록·친구는 samguk_social.

장원 층은 매일 판(경쟁)과 공정성 제약이 다르다: 객잔 손님은 사람마다 다르게 뽑는다(날짜 + 사용자 시드).
대신 힘은 넘어가지 않는다 — 객잔에서 얻은 장수는 도감·장원에만 있고 매일 판에 나오지 않는다(설계 1장 두 층 원칙).
"""
from __future__ import annotations

import hashlib
import random
from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import F

from . import samguk as S
from . import samguk_data as D
from .models import SamgukCodex, SamgukInn, SamgukMember

INN_GUESTS = 3
INN_TIER_WEIGHT = {1: 50, 2: 35, 3: 15}         # ★4·외전·기연은 객잔에 오지 않는다
INN_NEW_SHARE = 0.7                              # 아직 등록 안 한 장수를 이 비율로 먼저 고른다
INN_TRAVELER = 0.2                               # 손님 대신 나그네가 와서 소문을 남길 확률
REUNION_FAME = 3


def _seed(day: date, user_id: int) -> int:
    return int.from_bytes(hashlib.sha256(f'samguk-inn:{day.isoformat()}:{user_id}'.encode()).digest()[:8], 'big')


def recruited_codes(user) -> set:
    return set(SamgukCodex.objects.filter(user=user, first_recruited__isnull=False).values_list('general', flat=True))


def display_general(code):
    """장원 전시에는 외전·기연도 포함해요. 매일 판 후보에는 섞지 않아요."""
    from . import samguk_legends as L
    return D.GENERAL.get(code) or L.HIDDEN.get(code)


def draw_guests(day: date, user_id: int, have: set, level: int = 1) -> list:
    rng = random.Random(_seed(day, user_id))
    weight = {**INN_TIER_WEIGHT, 3: INN_STAR3_BY_LEVEL.get(level, INN_TIER_WEIGHT[3])}
    pool = [g for g in D.GENERALS if g.tier in weight]
    fresh = [g for g in pool if g.code not in have]
    picks: list = []
    while len(picks) < INN_GUESTS_BY_LEVEL.get(level, INN_GUESTS):
        src = fresh if fresh and rng.random() < INN_NEW_SHARE else pool
        src = [g for g in src if g.code not in picks]
        if not src:
            break
        g = rng.choices(src, weights=[weight[x.tier] for x in src])[0]
        picks.append(g.code)
    return picks


def inn_today(user) -> SamgukInn:
    day = S.game_day()
    found = SamgukInn.objects.filter(user=user, day=day).first()
    if found:
        return found
    offers = draw_guests(day, user.pk, recruited_codes(user), inn_level(user))
    traveler = ''
    if random.Random(_seed(day, user.pk) ^ 0x5A5A).random() < INN_TRAVELER and len(offers) > 2:
        offers, traveler = offers[:-1], 'waiting'                # 손님 한 자리에 나그네가 앉는다(설계 7.3)
    try:
        with transaction.atomic():
            return SamgukInn.objects.create(user=user, day=day, offers=offers, traveler_rumor=traveler)
    except IntegrityError:
        return SamgukInn.objects.get(user=user, day=day)


def inn_traveler(user, inn: SamgukInn) -> str | None:
    """나그네가 남긴 소문 — 처음 열 때 한 번 듣고, 그날은 같은 소문을 다시 보여 준다."""
    from .models import SamgukRumor
    if not inn.traveler_rumor:
        return None
    if inn.traveler_rumor == 'waiting':
        from . import samguk_legends as L
        text = L.rumor_for(user, source='inn')
        SamgukInn.objects.filter(pk=inn.pk).update(traveler_rumor='heard' if text else 'none')
        return text or '나그네가 차 한 잔을 비우고 말없이 떠났어요.'
    row = SamgukRumor.objects.filter(user=user, source='inn', heard_on=inn.day).order_by('-level').first()
    return row.text if row else None


def inn_pick(user, code: str) -> dict:
    day = S.game_day()
    with transaction.atomic():
        inn = SamgukInn.objects.select_for_update().filter(user=user, day=day).first()
        if inn is None:
            raise S.GameError('객잔을 먼저 열어 주세요.')
        if inn.picked:
            raise S.GameError('오늘은 이미 손님을 맞았어요. 내일 아침 6시에 새 손님이 와요.')
        if code not in inn.offers:
            raise S.GameError('오늘 객잔에 없는 손님이에요.')
        row, _ = SamgukCodex.objects.select_for_update().get_or_create(user=user, general=code,
                                                                       defaults={'first_seen': day})
        reunion = row.first_recruited is not None
        row.first_recruited = row.first_recruited or day
        row.first_seen = row.first_seen or day
        row.times_recruited += 1
        row.save(update_fields=['first_recruited', 'first_seen', 'times_recruited'])
        inn.picked, inn.reunion = code, reunion
        inn.save(update_fields=['picked', 'reunion'])
        if reunion:
            S.member(user)
            SamgukMember.objects.filter(user=user).update(fame=F('fame') + REUNION_FAME)
    g = D.GENERAL[code]
    text = (f'{g.name}과(와) 다시 만났어요. 명성 +{REUNION_FAME}' if reunion else f'{g.name}이(가) 도감에 올랐어요.')
    if not reunion:
        codex_milestones(user)
    return {'code': code, 'reunion': reunion, 'text': text}


# ── 도감 화면 묶음(설계 6.1) ──────────────────────────────────────────────
def codex_view(user) -> dict:
    rows = {c.general: c for c in SamgukCodex.objects.filter(user=user)}
    groups = []
    seen = got = 0
    for code, label in D.GROUPS.items():
        items = []
        for g in D.by_group(code):
            row = rows.get(g.code)
            state = 'recruited' if row and row.first_recruited else ('seen' if row else 'unknown')
            seen += state != 'unknown'
            got += state == 'recruited'
            items.append({'no': g.no, 'code': g.code, 'state': state, 'tier': g.tier, 'stars': D.TIER_STARS[g.tier],
                          'name': g.name if state != 'unknown' else '???',
                          'hanja': g.hanja if state != 'unknown' else '',
                          'detail': ({'lead': g.lead, 'war': g.war, 'intl': g.intl, 'pol': g.pol,
                                      'skill': D.SKILLS[g.skill][0], 'era': D.ERAS[g.era], 'source': g.source,
                                      'note': g.note, 'times': row.times_recruited, 'unified': row.unified_with,
                                      'first': row.first_recruited} if state == 'recruited' else None)})
        groups.append({'code': code, 'label': label, 'items': items,
                       'got': sum(i['state'] == 'recruited' for i in items), 'total': len(items)})
    from . import samguk_legends as L
    hidden = []
    for gcode, label in L.HIDDEN_GROUPS.items():
        members = [g for g in L.HIDDEN.values() if g.group == gcode]
        mine = [g for g in members if rows.get(g.code) and rows[g.code].first_recruited]
        hidden.append({'code': gcode, 'label': label, 'total': len(members), 'got': len(mine),
                       'items': [{'code': g.code, 'name': g.name, 'hanja': g.hanja, 'stars': D.TIER_STARS[g.tier],
                                  'nation': L.NATION[g.code], 'note': g.note, 'source': g.source} for g in mine]})
    return {'groups': groups, 'seen': seen, 'got': got, 'total': len(D.GENERALS), 'hidden': hidden}


# ── 장원 건물·배치(설계 7.1) ──────────────────────────────────────────────
# 자리 8칸 고정. 1~5 는 건물, 6~8 은 장식. 배치 칸은 본채 단계마다 늘고, 칸이 붙은 건물을 지어야 열린다.
BUILDINGS = {
    'main': {'name': '본채', 'max': 5, 'start': 1},
    'inn': {'name': '객잔', 'max': 3, 'start': 1},
    'pavilion': {'name': '정자', 'max': 3, 'start': 0},
    'library': {'name': '서고', 'max': 3, 'start': 0},
    'training': {'name': '연무장', 'max': 3, 'start': 0},
}
UPGRADE_COST = {'main': 40, 'inn': 30, 'pavilion': 25, 'library': 25, 'training': 25}   # × 다음 단계
DECOR = {
    'garden': ('정원', 20), 'pond': ('연못', 30), 'flag': ('깃발', 15),
    'lantern': ('석등', 20), 'bamboo': ('대나무', 15), 'plum': ('매화', 25),
}
DECOR_SLOTS = ('deco1', 'deco2', 'deco3')
# 배치 칸(그림 좌표는 Codex 가 이 순서에 맞춘다): (칸 이름, 필요한 건물)
PLACE_SLOTS = (
    ('front1', 'main'), ('front2', 'main'), ('pavilion1', 'pavilion'), ('training1', 'training'),
    ('front3', 'main'), ('library1', 'library'), ('pavilion2', 'pavilion'), ('training2', 'training'),
    ('library2', 'library'), ('training3', 'training'), ('pavilion3', 'pavilion'), ('front4', 'main'),
)
PLACE_BY_MAIN = {1: 4, 2: 6, 3: 8, 4: 10, 5: 12}
INN_GUESTS_BY_LEVEL = {1: 3, 2: 4, 3: 4}
INN_STAR3_BY_LEVEL = {1: 15, 2: 15, 3: 25}

FAME_FINISH = 10
FAME_WIN = 20
FAME_TOP10 = 10
CODEX_MILESTONES = (30, 100, 200)
CODEX_MILESTONE_FAME = 20


def manor_state(m: SamgukMember) -> dict:
    st = dict(m.manor or {})
    b = {k: int(st.get('buildings', {}).get(k, v['start'])) for k, v in BUILDINGS.items()}
    return {'buildings': b, 'decor': dict(st.get('decor', {})), 'placed': dict(st.get('placed', {})),
            'milestones': list(st.get('milestones', []))}


def open_slots(st: dict) -> list:
    n = PLACE_BY_MAIN[st['buildings']['main']]
    return [slot for slot, need in PLACE_SLOTS[:n] if st['buildings'][need] >= 1]


def _save_manor(m: SamgukMember, st: dict, fame_delta: int = 0) -> None:
    m.manor = st
    fields = ['manor', 'updated_at']
    if fame_delta:
        m.fame += fame_delta
        fields.append('fame')
    m.save(update_fields=fields)


def upgrade(user, building: str) -> dict:
    if building not in BUILDINGS:
        raise S.GameError('알 수 없는 건물이에요.')
    with transaction.atomic():
        m = SamgukMember.objects.select_for_update().get_or_create(user=user)[0]
        st = manor_state(m)
        cur = st['buildings'][building]
        spec = BUILDINGS[building]
        if cur >= spec['max']:
            raise S.GameError(f'{spec["name"]}은(는) 이미 가장 높은 단계예요.')
        if building != 'main' and cur + 1 > st['buildings']['main']:
            raise S.GameError('본채보다 높게 올릴 수 없어요. 본채를 먼저 올려 주세요.')
        cost = UPGRADE_COST[building] * (cur + 1)
        if m.fame < cost:
            raise S.GameError(f'명성이 모자라요(필요 {cost}, 보유 {m.fame}).')
        st['buildings'][building] = cur + 1
        _save_manor(m, st, -cost)
    return {'building': building, 'level': cur + 1, 'cost': cost,
            'text': f'{spec["name"]}을(를) {cur + 1}단계로 올렸어요.'}


def set_decor(user, slot: str, decor: str) -> dict:
    if slot not in DECOR_SLOTS or (decor and decor not in DECOR):
        raise S.GameError('장식 자리를 다시 골라 주세요.')
    with transaction.atomic():
        m = SamgukMember.objects.select_for_update().get_or_create(user=user)[0]
        st = manor_state(m)
        cost = 0
        if decor:
            cost = DECOR[decor][1]
            if m.fame < cost:
                raise S.GameError(f'명성이 모자라요(필요 {cost}, 보유 {m.fame}).')
            st['decor'][slot] = decor
        else:
            st['decor'].pop(slot, None)
        _save_manor(m, st, -cost)
    return {'text': f'{DECOR[decor][0]}을(를) 놓았어요.' if decor else '장식을 치웠어요.'}


def place(user, slot: str, code: str) -> dict:
    """도감에 등록된 장수를 배치 칸에 세운다(전시만, 효과 없음). code 가 비면 칸을 비운다."""
    with transaction.atomic():
        m = SamgukMember.objects.select_for_update().get_or_create(user=user)[0]
        st = manor_state(m)
        if slot not in open_slots(st):
            raise S.GameError('아직 열리지 않은 자리예요.')
        if code:
            if code not in recruited_codes(user) or display_general(code) is None:
                raise S.GameError('도감에 등록한 장수만 세울 수 있어요.')
            for k, v in list(st['placed'].items()):
                if v == code:
                    st['placed'].pop(k)
            st['placed'][slot] = code
        else:
            st['placed'].pop(slot, None)
        _save_manor(m, st)
    return {'text': f'{display_general(code).name}을(를) 세웠어요.' if code else '자리를 비웠어요.'}


def manor_view(owner) -> dict:
    m = S.member(owner)
    st = manor_state(m)
    placed = []
    for slot in open_slots(st):
        code = st['placed'].get(slot)
        officer = None
        g = display_general(code)
        if g:
            officer = {'code': code, 'name': g.name, 'stars': D.TIER_STARS[g.tier]}
        placed.append({'slot': slot, 'officer': officer})
    buildings = [{'code': k, 'name': v['name'], 'level': st['buildings'][k], 'max': v['max'],
                  'cost': UPGRADE_COST[k] * (st['buildings'][k] + 1) if st['buildings'][k] < v['max'] else None}
                 for k, v in BUILDINGS.items()]
    decor = [{'slot': slot, 'decor': st['decor'].get(slot),
              'name': DECOR[st['decor'][slot]][0] if st['decor'].get(slot) in DECOR else None}
             for slot in DECOR_SLOTS]
    got = SamgukCodex.objects.filter(user=owner, first_recruited__isnull=False).count()
    return {'member': m, 'buildings': buildings, 'placed': placed, 'decor': decor, 'decor_options': DECOR,
            'codex_got': got, 'codex_total': len(D.GENERALS), 'titles': (m.titles or [])[-5:]}


def inn_level(user) -> int:
    return manor_state(S.member(user))['buildings']['inn']


# ── 명성 지급(마감·도감 이정표) ─────────────────────────────────────────────
def fame_for_run(rank: int, players: int) -> int:
    fame = FAME_FINISH
    if rank == 1:
        fame += FAME_WIN
    elif players >= 10 and rank <= max(1, players // 10):
        fame += FAME_TOP10
    return fame


def codex_milestones(user) -> int:
    """도감 이정표(30·100·200·전부)를 처음 넘으면 명성 +20씩. 준 명성을 돌려준다."""
    got = SamgukCodex.objects.filter(user=user, first_recruited__isnull=False).count()
    marks = [n for n in CODEX_MILESTONES + (len(D.GENERALS),) if got >= n]
    with transaction.atomic():
        m = SamgukMember.objects.select_for_update().get_or_create(user=user)[0]
        st = manor_state(m)
        new = [n for n in marks if n not in st['milestones']]
        if not new:
            return 0
        st['milestones'] += new
        _save_manor(m, st, CODEX_MILESTONE_FAME * len(new))
    return CODEX_MILESTONE_FAME * len(new)


# ── 지나가는 거지(설계 7.4) ───────────────────────────────────────────────
BEGGAR_LINES = 3
BEGGAR_ALMS = 2
BEGGAR_QUIET = '요즘은 조용하구먼. 다들 오늘 판에 바쁜가 봐.'


def _gossip_pool(user) -> list:
    """끝난 판·도감·장원처럼 경쟁과 상관없는 소식만. 오늘 판(진행 중) 내용은 절대 넣지 않는다.
    (친구 소식인가, 소식 키, 문장) 목록."""
    from . import samguk_social as SO
    from .models import SamgukDay, SamgukRun
    friends = SO.friend_ids(user)
    hidden = set(SamgukMember.objects.filter(hide_from_beggar=True).values_list('user_id', flat=True))
    today = S.game_day()
    facts = []
    last = SamgukDay.objects.filter(status='closed', date__lt=today).order_by('-date').first()
    if last:
        for run in SamgukRun.objects.filter(day=last, rank__lte=3).select_related('user', 'user__profile'):
            if run.user_id in hidden or run.user_id == user.pk:
                continue
            name = S.display_name(run.user)
            city = D.CITY[run.start_city].name
            text = (f'어제 {name} 나리가 {city}에서 일어나 천하를 먹었다지.' if run.rank == 1 else
                    f'어제 {name} 나리가 {city}에서 시작해 {run.rank}등을 했다더군.')
            facts.append((run.user_id in friends, f'run:{last.date}:{run.user_id}', text))
        if last.faction_scores:
            best = max(last.faction_scores.items(), key=lambda kv: kv[1])
            facts.append((False, f'fac:{last.date}',
                          f'어제는 {D.FACTIONS.get(best[0], best[0])}이(가) 세력 다툼에서 이겼다지.'))
    others = (SamgukMember.objects.exclude(user=user).exclude(user_id__in=hidden)
              .select_related('user', 'user__profile').order_by('-updated_at')[:200])
    for m in others:
        placed = [c for c in (m.manor or {}).get('placed', {}).values() if c in D.GENERAL]
        if placed:
            top = max(placed, key=lambda c: (D.GENERAL[c].tier, c))
            if D.GENERAL[top].tier >= 3:
                facts.append((m.user_id in friends, f'manor:{m.user_id}:{top}',
                              f'{S.display_name(m.user)} 나리 장원에 {D.GENERAL[top].name}이(가) 서 있다더군. '
                              '무서워서 못 지나가겠어.'))
        if m.wins >= 3:
            facts.append((m.user_id in friends, f'wins:{m.user_id}:{m.wins}',
                          f'{S.display_name(m.user)} 나리는 벌써 {m.wins}번이나 천하를 먹었다네.'))
    return facts


def beggar_talk(user, alms: bool = False) -> dict:
    """한마디 듣기(하루 세 번). alms=True 면 명성 2 를 주고 전설 소문을 듣는다."""
    day = S.game_day().isoformat()
    with transaction.atomic():
        m = SamgukMember.objects.select_for_update().get_or_create(user=user)[0]
        b = dict(m.beggar or {})
        if b.get('day') != day:
            b = {'day': day, 'count': 0, 'heard': list(b.get('heard', []))[-200:]}
        if b['count'] >= BEGGAR_LINES:
            raise S.GameError('거지가 오늘은 더 할 말이 없대요. 내일 또 지나간대요.')
        text = None
        if alms:
            if m.fame < BEGGAR_ALMS:
                raise S.GameError(f'동냥할 명성이 모자라요(필요 {BEGGAR_ALMS}).')
            from . import samguk_legends as L
            text = L.rumor_for(user, source='beggar')
            if text:
                m.fame -= BEGGAR_ALMS
        if text is None:
            facts = _gossip_pool(user)
            order = {'run': 0, 'manor': 1, 'wins': 2, 'fac': 3}      # 사람 소식 먼저, 세력 소식은 맨 뒤
            facts.sort(key=lambda f: (not f[0], order.get(f[1].split(':')[0], 9), f[1]))
            fresh = [f for f in facts if f[1] not in b['heard']]
            if fresh:
                _friend, key, text = fresh[0]
                b['heard'].append(key)
            else:
                text = BEGGAR_QUIET
        b['count'] += 1
        m.beggar = b
        m.save(update_fields=['beggar', 'fame', 'updated_at'])
    return {'text': text, 'left': BEGGAR_LINES - b['count']}
