"""정식·라이트 공용 자신감·대화·협상. 기존 JSON 필드를 쓰며 영구 능력치는 바꾸지 않는다.

자신감은 타격 접근·제구와 멘탈 ±1.25, 자기 관리는 훈련 효율 ±7.5%로 제한한다.
상호작용의 결과와 원인을 최근 기록에 남기고, 자신감은 주기마다 50으로 수렴한다.
"""
import secrets
import random

from . import rookie_sim as M
from . import rookie_world as W
from . import rookie_contracts as Contracts
from . import rookie_universe as Universe

LABELS = {'confidence': '자신감', 'trust': '감독 신뢰', 'discipline': '자기 관리', 'fame': '인기', 'intl_rep': '국제무대 평판'}


def clamp(n, lo=0, hi=100):
    return max(lo, min(hi, n))


def field(p):
    return 'flags' if hasattr(p, 'flags') else 'career'


def state(p):
    return dict(getattr(p, field(p), None) or {})


def put(p, data):
    # 시즌 진행 코드가 들고 있는 같은 JSON dict 참조도 함께 갱신한다.
    current = getattr(p, field(p), None)
    if isinstance(current, dict) and current is not data:
        current.clear()
        current.update(data)
        data = current
    setattr(p, field(p), data)


def value(p, key):
    return float(state(p).get(key, 0 if key in ('fame', 'intl_rep') else 50))


def change(p, reason, **deltas):
    data = state(p)
    changes = []
    for key, amount in deltas.items():
        before = value(p, key)
        after = round(clamp(before + amount), 1)
        data[key] = after
        actual = round(after - before, 1)
        if actual:
            changes.append(f'{LABELS[key]} {actual:+g}')
    text = reason + (' — ' + ' · '.join(changes) if changes else '')
    data['story_log'] = (list(data.get('story_log') or []) + [text])[-8:]
    put(p, data)
    return text


def bonus(p):
    # 팬의 응원은 자신감이 무너졌을 때 작은 완충만 제공한다. 인기 자체가 능력치가 되지는 않는다.
    raw = (value(p, 'confidence') - 50) / 40
    support = min(.25, value(p, 'fame') / 400) if raw < 0 else 0
    return round(clamp(raw + support, -1.25, 1.25), 2)


def game_stats(p, stats):
    boost = bonus(p)
    affected = ('contact', 'eye') if p.role == 'batter' else ('control', 'mental')
    return {key: clamp(float(v) + (boost if key in affected else 0), 1, 110) for key, v in stats.items()}


def training_mult(p):
    return 1 + (value(p, 'discipline') - 50) * .0015


def recover(p):
    data = state(p)
    if 'confidence' in data:
        data['confidence'] = round(50 + (float(data['confidence']) - 50) * .55, 1)
    for key in ('trust', 'discipline'):
        if key in data:
            data[key] = round(50 + (float(data[key]) - 50) * .90, 1)
    put(p, data)


def view(p):
    from . import rookie_development as Development
    from . import rookie_pitching as Pitching
    return dict(confidence=round(value(p, 'confidence')), trust=round(value(p, 'trust')),
                discipline=round(value(p, 'discipline')), fame=round(value(p, 'fame')),
                bonus=f'{bonus(p):+g}', training=round((training_mult(p) - 1) * 100),
                history=list(reversed(state(p).get('story_log') or []))[:4], pitching=Pitching.view(p),
                promise=state(p).get('story_promise'), contract=Contracts.summary(p),
                contract_income=state(p).get('mlb_contract_income', 0), development=Development.view(p),
                universe=Universe.view(p), standings=Universe.current_table(p) if getattr(p, 'pk', None) else None)


CHOICES = {
    'manager': [('team_work', '맡은 역할에서 증명할게요', '신뢰', '팀의 믿음을 얻지만, 더 큰 역할을 요구할 자신감은 한발 접어요'),
                ('request_role', '더 중요한 역할을 맡겨 주세요', '도전', '기회를 앞당길 수 있지만, 준비가 부족하면 신뢰까지 잃어요'),
                ('extra_work', '추가 훈련 계획을 세울게요', '준비', '훈련 루틴을 다지는 대신, 당장 실력을 증명할 자신감은 낮아져요')],
    'interview': [('team', '동료와 코치 덕분이에요', '동료', '팀의 신뢰를 얻는 대신, 내 존재감과 자신감은 한발 접어요'),
                  ('ambition', '다음에는 제가 증명할게요', '선언', '관심을 내 쪽으로 모아요. 다음 성적이 약속을 못 받치면 여론도 돌아서요'),
                  ('blame', '더 많은 기회를 받아야 해요', '압박', '주목받고 내 입장을 드러내지만, 감독과의 관계와 훈련 리듬을 내줘요')],
    'conduct': [('rest', '회복과 훈련 일정을 지킬게요', '루틴', '생활 리듬을 챙기지만, 관심이 줄고 실전에 대한 자신감도 잠시 식어요'),
                ('fans', '팬 행사에 다녀올게요', '교감', '응원과 활력을 얻는 대신, 준비하던 훈련 일정이 밀려요'),
                ('night', '원정 뒤풀이에 참여할게요', '해방감', '화제와 기분 전환은 크지만, 생활 리듬과 감독의 믿음을 걸어야 해요')],
    'rival': [('together', '같이 훈련하며 서로 도울게요', '공조', '관계와 훈련은 좋아져요. 경쟁자를 가까이 보며 자신감이 흔들릴 수 있어요'),
              ('challenge', '훈련에서 정면으로 겨뤄 볼게요', '승부', '앞서면 자신을 증명하지만, 지면 감독의 평가와 자신감도 내려가요'),
              ('blame_rival', '경쟁자의 약점을 공개할게요', '견제', '여론을 움직여 내 존재감을 키우지만, 동료와 감독의 신뢰를 잃어요')],
    'highlight_bat': [('fast', '직구를 노릴게요', '타이밍', '빠른 공에 스윙을 맞춰요. 구종이 바뀌면 크게 헛돌 수 있어요'),
                      ('break', '변화구를 기다릴게요', '기다림', '떨어지는 공을 끝까지 봐요. 빠른 공이 들어오면 배트가 늦어요'),
                      ('short', '짧게 끊어 칠게요', '컨택', '배트에 맞힐 여지를 늘려요. 타구가 짧아 주자를 묶어 둘 수도 있어요')],
    'highlight_pit': [('fast', '직구로 승부할게요', '구위', '존 안에서 빠르게 승부해요. 타이밍을 읽히면 장타를 맞을 수 있어요'),
                      ('break', '변화구로 유인할게요', '낙차', '배트가 따라 나오기를 기다려요. 참아 버리면 볼카운트가 어려워져요'),
                      ('edge', '낮은 코너를 공략할게요', '제구', '정타를 피할 코스로 승부해요. 조금만 벗어나도 볼넷으로 이어질 수 있어요')],
}


def choices(p, kind):
    key = 'highlight_' + ('bat' if p.role == 'batter' else 'pit') if kind == 'highlight' else kind
    return CHOICES[key]


def highlight_report(p, read):
    if p.role == 'batter':
        return ('최근엔 직구로 카운트를 잡았어요. 결정구까지 같은 패턴일지는 몰라요.' if read == 'fast' else
                '최근엔 변화구를 먼저 보여 줬어요. 빠른 공을 숨기고 있을 수도 있어요.')
    return ('변화구에 타이밍을 맞춰 뒀어요. 빠른 공도 가운데 몰리면 길게 보낼 수 있어요.' if read == 'fast' else
            '빠른 공에 스윙이 크게 나와요. 낮은 공을 쫓지만 실투는 놓치지 않아요.')


def encounter_view(p, event):
    """이전 저장 장면도 선택 키·결과를 보존한 채 최신 설명으로 보여 준다."""
    kind = event.get('kind')
    if kind not in ('manager', 'interview', 'conduct', 'rival', 'highlight'):
        return event
    view = dict(event, choices=[dict(key=k, label=l, tone=t, hint=h) for k, l, t, h in choices(p, kind)])
    if kind == 'highlight':
        sit = '동점, 2사 2루예요.' if p.role == 'batter' else '한 점 앞선 8회, 2사 2루예요.'
        view['text'] = sit + ' 한 번의 승부가 흐름을 바꿀 수 있어요. ' + highlight_report(p, event.get('read'))
    return view


def encounter(p, kind, rng):
    key = 'highlight_' + ('bat' if p.role == 'batter' else 'pit') if kind == 'highlight' else kind
    opponent = None
    if kind == 'rival':
        opponent = Universe.rival_report(p, p.league, 'down')
        title, text, background, read = (f'{opponent["name"]} 선수와 다시 만났어요',
            f'{opponent["line"]}. 같은 자리의 경쟁자예요. 지난 대화를 기억하고 있어요. 어떻게 경쟁할까요?', 'manager-office', '')
    elif kind == 'highlight':
        read = 'fast' if rng.random() < .5 else 'break'
        scout = highlight_report(p, read)
        title = '8회, 균형을 깰 기회' if p.role == 'batter' else '8회, 한 점 차 리드를 지켜야 해요'
        situation = '동점, 2사 2루예요.' if p.role == 'batter' else '한 점 앞선 8회, 2사 2루예요.'
        text = situation + ' 이번 승부가 경기의 흐름을 바꿀 수 있어요. ' + scout
        background = 'finals-stadium'
    elif kind == 'manager':
        title, text, background, read = '감독실에서의 면담', '앞으로 어떤 역할을 맡고 싶은지 이야기해 봐요. 지금의 실력과 준비 상태를 함께 보고 결정할게요.', 'manager-office', ''
    elif kind == 'interview':
        title, text, background, read = '경기 뒤 기자 인터뷰', '기자가 최근의 활약과 앞으로의 목표를 물어요. 팬과 감독 모두 이 답을 듣고 있어요.', 'press-room', ''
    else:
        title, text, background, read = '원정 경기 전날', '내일 중요한 경기가 있어요. 회복 일정을 지킬지, 팬 행사를 갈지, 동료의 밤늦은 약속에 따라갈지 정해요.', 'manager-office', ''
    if kind == 'manager' and getattr(p, 'club', None):
        profile = Universe.coach(p)
        text += f' 이 감독은 {profile["label"]}이에요. {profile["text"]}'
    return dict(id=secrets.token_hex(8), kind=kind, title=title, text=text, background=background, read=read, rival=opponent,
                choices=[dict(key=k, label=l, tone=t, hint=h) for k, l, t, h in CHOICES[key]])


def resolve(p, event, choice, rng):
    if choice not in {c['key'] for c in event['choices']}:
        raise ValueError('화면에 있는 선택지 가운데 하나를 골라 주세요.')
    kind = event['kind']
    if kind == 'rival':
        rival = event['rival']
        if choice == 'together':
            text = change(p, f'{rival["name"]} 선수와 함께 훈련했어요. 경쟁자의 준비를 보며 자신도 돌아봤어요', discipline=10, trust=3, confidence=-3)
        elif choice == 'challenge':
            chance = clamp(.5 + (p.ovr - W.level(p.league) - rival['z'] * 7) / 24 + bonus(p) * .015, .15, .85)
            ok = rng.random() < chance
            text = change(p, f'{rival["name"]} 선수와 훈련 승부에서 ' + ('앞섰어요' if ok else '밀렸어요'),
                          confidence=7 if ok else -6, trust=3 if ok else -2)
        else:
            text = change(p, '경쟁자를 향한 공개 발언으로 관계가 나빠졌어요', fame=6, trust=-14, confidence=3)
        Universe.remember(p, rival['id'], 'blame' if choice == 'blame_rival' else choice, text)
        return text
    if kind == 'highlight':
        # 타석 모형으로 승부한다. 공식 경기 통계와 별개인 개인 승부 장면이며 이후 경기력에 연결한다.
        stats, lvl = game_stats(p, p.stats), W.level(p.league)
        if p.role == 'batter':
            probs = M.pa_probs(stats, {k: lvl + 3 for k in M.PIT}, risp=True)
            read = event['read'] if rng.random() < .7 else ('break' if event['read'] == 'fast' else 'fast')
            mult = {'SO': .55, 'HR': .45, '1B': 1.25} if choice == 'short' else \
                   ({'HR': 2, '2B': 1.5, '1B': 1.35, 'SO': .65} if choice == read else {'SO': 1.5, 'HR': .45, '1B': .7})
            probs = {k: v * mult.get(k, 1) for k, v in probs.items()}
            total = sum(probs.values())
            outcome = M._pick({k: v / total for k, v in probs.items()}, rng)
            ok = outcome in ('1B', '2B', '3B', 'HR', 'BB', 'HBP')
            result = {'HR': '앞서가는 2점 홈런을 날렸어요!', '1B': '적시타로 주자를 불러들였어요!', '2B': '외야를 가르는 적시 2루타예요!',
                      '3B': '3루타로 분위기를 바꿨어요!', 'BB': '침착하게 볼넷을 골랐어요.', 'HBP': '출루해 다음 타자에게 기회를 넘겼어요.',
                      'SO': '삼진으로 기회를 놓쳤어요.', 'OUT': '타구가 야수에게 잡혔어요.'}[outcome]
        else:
            mine = dict(stats)
            for k in ('velocity', 'control', 'breaking'):
                mine[k] += 4 if choice == event['read'] else -2 if choice != 'edge' else 0
            probs = M.pa_probs({k: lvl + 3 for k in M.BAT}, mine, risp=True)
            outcome = M._pick(probs, rng)
            ok = outcome in ('SO', 'OUT')
            result = '삼진으로 위기를 넘겼어요!' if outcome == 'SO' else '범타로 한 점 차 리드를 지켰어요!' if ok else '출루를 허용했어요. 위기가 이어져요.'
        return change(p, result, confidence=10 if ok else -8, trust=3 if ok else -2, fame=2 if ok else 0)
    effects = {
        'team_work': dict(trust=12, confidence=-3, discipline=5), 'extra_work': dict(discipline=15, trust=5, confidence=-2),
        'team': dict(trust=10, confidence=-2, fame=-3), 'ambition': dict(confidence=10, fame=8),
        'blame': dict(confidence=5, fame=6, trust=-18, discipline=-8),
        'rest': dict(discipline=12, trust=6, confidence=-2, fame=-3), 'fans': dict(fame=10, confidence=5, discipline=-8),
        'night': dict(fame=14, confidence=8, discipline=-18, trust=-15),
    }
    if choice == 'request_role':
        strict = .1 if Universe.coach(p)['kind'] == 'results' else 0
        ok = rng.random() < clamp(.5 - strict + (p.ovr - W.level(p.league)) * .03 + (value(p, 'confidence') - 50) * .002, .1, .9)
        return change(p, '더 중요한 역할을 준비할 기회를 얻었어요' if ok else '아직 준비가 부족하다는 답을 받았어요',
                      trust=10 if ok else -10, confidence=8 if ok else -6)
    if choice == 'ambition':
        data = state(p)
        data.setdefault('story_promise', {'target': .5, 'label': '평균보다 좋은 성적으로 증명하기'})
        put(p, data)
    label = next(label for key, label, _tone, _hint in choices(p, kind) if key == choice)
    delta = dict(effects[choice])
    style = Universe.coach(p)['kind']
    if style == 'team' and choice in ('blame', 'night'):
        delta['trust'] = delta.get('trust', 0) - 6
    if style == 'development' and choice == 'extra_work':
        delta['trust'] += 5
    return change(p, label, **delta)


def settle_promise(p, performance):
    data = state(p)
    promise = data.pop('story_promise', None)
    if not promise or performance is None:
        return ''
    put(p, data)
    ok = performance >= promise['target']
    return change(p, '공개 약속을 지켰어요' if ok else '공개 약속에 미치지 못했어요',
                  confidence=6 if ok else -12, trust=10 if ok else -8, fame=6 if ok else -4)


def posting_offers(p, rng):
    """관심 구단 세 곳과 조건을 저장한다. 화면을 다시 열어도 제안은 바뀌지 않는다."""
    from . import rookie_balance_rules as B
    eligible = {system: B.overseas_level(p, system) for system in ('mlb', 'npb')}
    eligible = {system: league for system, league in eligible.items() if league}
    if not eligible:
        return []
    pool = [(system, code) for system in eligible for code, _name, _color in W.SYSTEM_TEAMS[system]]
    out = []
    for i in range(3):
        idx = min(len(pool) - 1, int(rng.random() * len(pool)))
        system, club = pool.pop(idx)
        entry = eligible[system]
        _t, recent_war, _games = B.recent(p)
        annual = int(B.annual(p, entry, recent_war, 6) * (.9 + i * .08))
        role = '주전 경쟁' if entry in W.TOP_LEAGUES else '마이너 선발 경쟁' if p.role == 'pitcher' else '마이너 출전 경쟁'
        deal = dict(key=club, team=club, system=system, entry_league=entry,
                    years=B.contract_years(p, recent_war) if entry in W.TOP_LEAGUES else 1,
                    annual=annual, budget=round(annual * 1.12),
                    interest=round(.40 + rng.random() * .16, 2), role=role)
        if system == 'mlb':
            deal.update(split=entry != 'mlb' or (p.ovr < 76 and i == 1), roster_pressure=.10 + .05 * i)
            if entry != 'mlb':
                deal.update(annual=110000, minor_annual=annual, budget=123200)
        out.append(Contracts.terms(deal))
    return out


def deal_chance(p, deal, choice):
    base = deal['interest'] + (p.ovr - W.level(W.SYSTEMS[deal['system']][-1])) * .012
    base += min(.05, value(p, 'fame') * .0005) + min(.05, value(p, 'intl_rep') * .001) + (value(p, 'discipline') - 50) * .0005
    requested = deal['annual'] * (1.2 if choice == 'salary' else .9 if choice == 'compromise' else 1)
    base -= min(.25, max(0, requested / max(1, deal.get('budget', deal['annual'] * 1.15)) - 1) * .6)
    if choice in ('minor_veto', 'veto_discount'):
        # 거부권은 구단의 로스터 운용을 제한하는 큰 요구다. 일반 수락과 확실한 차이를 둔다.
        return clamp(base - (.64 if choice == 'minor_veto' else .36), .03, .3 if choice == 'minor_veto' else .58)
    if choice == 'opt_out':
        return clamp(base - .32, .08, .62)
    return clamp(base + {'accept': .18, 'salary': -.14, 'role': -.12, 'compromise': .26}.get(choice, 0) + deal.get('round', 0) * .035, .12, .95)


def negotiate(p, deal, choice, rng):
    mlb = deal.get('system') == 'mlb' and deal.get('entry_league', 'mlb') == 'mlb'
    if choice not in ('accept', 'salary', 'role', 'compromise', 'leave') + (('minor_veto', 'veto_discount', 'opt_out') if mlb else ()):
        raise ValueError('협상 방식을 골라 주세요.')
    if choice == 'leave':
        return 'failed', deal
    updated = Contracts.terms(deal)
    if choice == 'salary':
        updated['annual'] = round(updated['annual'] * 1.2)
        if updated.get('entry_league', 'mlb') != 'mlb' and updated.get('minor_annual'):
            updated['minor_annual'] = round(updated['minor_annual'] * 1.2)
    elif choice == 'compromise':
        updated['annual'] = round(updated['annual'] * .9)
        if updated.get('entry_league', 'mlb') != 'mlb' and updated.get('minor_annual'):
            updated['minor_annual'] = round(updated['minor_annual'] * .9)
    elif choice == 'role':
        updated['role'] = '핵심 선수' if updated.get('entry_league', 'mlb') in W.TOP_LEAGUES else '마이너 핵심 선수'
    elif choice in ('minor_veto', 'veto_discount'):
        updated['minor_veto'] = True
        if choice == 'veto_discount':
            updated['annual'] = round(updated['annual'] * .65)
    elif choice == 'opt_out':
        updated['player_opt_out'] = True
    if rng.random() < deal_chance(p, deal, choice):
        return 'signed', updated
    # 거절된 권리·인상 요구를 다음 제안에 몰래 포함하지 않는다.
    counter = Contracts.terms(deal)
    counter['round'] = deal.get('round', 0) + 1
    counter['annual'] = round(deal['annual'] * .97)
    counter['last_rejection'] = ('마이너 거부권 요구를 구단이 최종 거절했어요.' if choice == 'minor_veto'
                                 else '요구는 거절됐어요. 권리를 추가하지 않은 수정 연봉을 확인해 주세요.')
    return ('counter' if counter['round'] < 3 and choice != 'minor_veto' else 'failed'), counter


def deal_view(p, deal):
    d = Contracts.terms(deal)
    options = [('accept', '제시한 조건으로 합의할게요', '현재 연봉과 역할로 합의를 시도해요'),
               ('salary', '연봉을 20% 더 원해요', '몸값을 올리는 대신 결렬 위험이 커져요'),
               ('role', '핵심 선수로 기용할 계획을 원해요', '기용 계획을 요구해요. 주전 출전까지 계약으로 보장하지는 않아요'),
               ('compromise', '연봉 10%를 양보할게요', '연봉만 낮춰요. 마이너 거부권은 추가되지 않아요')]
    if d.get('system') == 'mlb' and d.get('entry_league', 'mlb') == 'mlb':
        options += [('minor_veto', '마이너 거부권이 없으면 계약하지 않을게요', '최후통첩이에요. 거절되면 재협상 없이 결렬돼요'),
                    ('veto_discount', '연봉 35%를 낮추고 마이너 거부권을 원해요', '보장액을 크게 양보해도 합의에 실패할 수 있어요'),
                    ('opt_out', '첫 시즌 뒤 옵트아웃 권리를 원해요', '성공하면 남은 보장액을 포기하고 새 계약을 찾을 수 있어요')]
    return dict(d, team_name=W.PRO_TEAM[deal['team']]['name'], background='negotiation-room',
                contract_terms=Contracts.summary(p, d),
                round_no=deal.get('round', 0) + 1,
                choices=[dict(key=k, label=label, hint=hint, chance=round(deal_chance(p, deal, k) * 100))
                         for k, label, hint in options])


def prepare_daily(p, today):
    """정식 판은 하루 한 번 추첨한다. 미결 선택지는 유지하며 새로고침으로 다시 뽑지 않는다."""
    from . import rookie_league as L
    Universe.rivals(p)
    Contracts.roll_full(p, L.season_no(today))
    expired = Contracts.expiry_market(p, random.Random(f'contract-market:{p.pk}:{today}'), today)
    if expired:
        data = state(p)
        data['story_pending'] = dict(expired, id=secrets.token_hex(8))
        put(p, data)
    data = state(p)
    if p.retired_at or p.pending or data.get('story_date') == today.isoformat():
        return
    recover(p)
    data = state(p)
    data['story_date'] = today.isoformat()
    if data.get('story_pending'):
        put(p, data)
        return
    rng = random.Random(f'rookie-story:{p.pk}:{today.isoformat()}')
    # KBO에서 일곱 시즌을 보낸 1군 선수에게 정식 판에서도 포스팅을 제안한다.
    first = next((x for x in data.get('path', []) if W.system_of(x['league']) == 'kbo'), None)
    service = p.age_season - first.get('season', p.age_season) if first else 0
    from . import rookie_pitching as Pitching
    from . import rookie_balance_rules as Balance
    from . import rookie_league as L
    from types import SimpleNamespace
    latest = p.season_stats.order_by('-season__number').first()
    total = latest.totals if latest else {}
    pitch_event = Pitching.offer(p, total, today.toordinal(), today)
    pressure = Balance.retention(p, SimpleNamespace(games=total.get('g', 0)))
    data = state(p)
    if pitch_event:
        data['story_pending'] = dict(pitch_event, id=secrets.token_hex(8))
    elif pressure is not None and rng.random() < pressure:
        data['story_pending'] = dict(Balance.market_event(p, pressure), id=secrets.token_hex(8))
    elif Contracts.can_opt_out(p):
        data['story_pending'] = Contracts.optout_view(p, secrets.token_hex(8))
    elif p.league == 'kbo1' and service >= 7 and p.ovr >= W.level('mlb') - 3 and not data.get('posted'):
        offers = posting_offers(p, rng)
        if offers:
            data['story_pending'] = dict(id=secrets.token_hex(8), kind='posting', offers=offers)
    elif rng.random() < .55:
        kind = rng.choice(['highlight', 'highlight', 'manager', 'interview', 'conduct', 'rival'])
        data['story_pending'] = encounter(p, kind, rng)
    put(p, data)


def daily_view(p):
    event = state(p).get('assignment_pending') or state(p).get('story_pending')
    if not event:
        return None
    if event['kind'] == 'negotiation':
        return dict(deal_view(p, event['deal']), kind='negotiation', id=event['id'])
    if event['kind'] == 'posting':
        return dict(event, background='negotiation-room', title='해외 구단 세 곳에서 관심을 보였어요',
                    offers=[dict(o, team_name=W.PRO_TEAM[o['team']]['name']) for o in event['offers']])
    if event['kind'] == 'pitch_role':
        from . import rookie_pitching as Pitching
        return Pitching.event_view(event)
    return encounter_view(p, event)


def daily_reply(p, event_id, choice, rng, today):
    data = state(p)
    assignment = data.get('assignment_pending')
    event = assignment or data.get('story_pending') or {}
    if not event or event.get('id') != event_id:
        raise ValueError('이미 처리했거나 바뀐 장면이에요. 현재 화면을 다시 확인해 주세요.')
    data['story_date'] = today.isoformat()
    put(p, data)
    kind = event['kind']
    if kind in ('pitch_role', 'career_market'):
        from . import rookie_pitching as Pitching
        from . import rookie_balance_rules as Balance
        previous = p.league
        text = Pitching.resolve(p, event, choice, rng) if kind == 'pitch_role' else Balance.market_reply(p, event, choice, rng)
        if not p.retired_at and p.league != previous:
            from . import rookie_career as C
            p.league_since = today
            C._reset_role(p, today)
            C._path(p, p.league, p.club, today)
        data = state(p)
        data.pop('story_pending', None)
        put(p, data)
        return text
    if kind == 'assignment':
        from . import rookie_career as C
        from . import rookie_league as L
        text = Contracts.assignment_reply(p, choice, rng, L.season_no(today))
        data = state(p)
        data.pop('assignment_pending', None)
        put(p, data)
        if p.league != 'mlb':
            p.league_since = today
            C._reset_role(p, today)
            C._path(p, p.league, p.club, today)
        return text
    if kind == 'contract_optout':
        text = Contracts.optout_reply(p, choice)
        data = state(p)
        data.pop('story_pending', None)
        if choice == 'market':
            from . import rookie_career as C
            p.league, p.club, p.league_since = 'kbo2', p.team, today
            C._reset_role(p, today)
            put(p, data)
            C._path(p, p.league, p.club, today)
            data = state(p)
            data['story_pending'] = dict(id=secrets.token_hex(8), kind='posting', offers=posting_offers(p, rng), origin='optout')
        put(p, data)
        return text
    if kind == 'posting':
        if choice == 'stay':
            data.pop('story_pending', None)
            data['posted'] = True
            put(p, data)
            return '이번에는 KBO에 남기로 했어요.'
        offer = next((o for o in event['offers'] if o['key'] == choice), None)
        if not offer:
            raise ValueError('관심 구단 세 곳 가운데 하나를 골라 주세요.')
        data['story_pending'] = dict(id=secrets.token_hex(8), kind='negotiation', deal=dict(offer, round=0), origin=event.get('origin'))
        put(p, data)
        return '선택한 구단과 협상을 시작해요.'
    if kind == 'negotiation':
        result, deal = negotiate(p, event['deal'], choice, rng)
        if result == 'counter':
            data['story_pending'] = dict(id=secrets.token_hex(8), kind='negotiation', deal=deal, origin=event.get('origin'))
            put(p, data)
            return '구단이 수정 조건을 제시했어요. 다시 조율해 주세요.'
        data.pop('story_pending', None)
        data['posted'] = True
        if result == 'signed':
            from . import rookie_career as C
            target = deal.get('entry_league') or ('npb1' if deal['system'] == 'npb' else 'mlb')
            p.league, p.club, p.league_since = target, deal['team'], today
            from . import rookie_league as L
            data['contract'] = Contracts.signed(deal, L.season_no(today))
            data.pop('mlb_camp_season', None)
            data.pop('mlb_bench_season', None)
            data['trust'] = 65 if deal['role'] == '핵심 선수' else 50
            put(p, data)
            C._reset_role(p, today)
            C._path(p, target, p.club, today)
            return change(p, f'{W.PRO_TEAM[p.club]["name"]}와 해외 계약에 성공했어요', confidence=8)
        put(p, data)
        return change(p, '해외 협상이 결렬됐어요. KBO에 남아 준비해요.', confidence=-6)
    text = resolve(p, event, choice, rng)
    data = state(p)
    data.pop('story_pending', None)
    if choice == 'ambition':
        data['story_promise'].setdefault('since', today.isoformat())
    put(p, data)
    return text
