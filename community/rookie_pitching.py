"""정식·라이트 공용 투수 보직 전환. 수업과 시험 등판은 정규 기록과 구분한다."""
from datetime import date

from . import rookie_balance_rules as B
from . import rookie_sim as M
from . import rookie_world as W


def eligible(p):
    return p.role == 'pitcher' and not B.state(p).get('army')


def current(p):
    return B.state(p).get('pitch_track', p.position or 'RP')


def view(p):
    if p.role != 'pitcher':
        return None
    data = B.state(p)
    assessment = data.get('pitch_last_assessment')
    return dict(label='선발 투수' if current(p) == 'SP' else '구원 투수',
                course=bool(data.get('starter_course')), history=list(reversed(data.get('pitch_history') or []))[:3],
                assessment=assessment)


def ready(p):
    lvl, s = W.level(p.league), p.stats
    return s['stamina'] >= lvl - 4 and s['mental'] >= lvl - 3 and M.stuff_of(s) >= lvl - 3


def choice(key, label, hint):
    hints = {
        'course': '불펜을 뛰며 선발 준비를 병행해요. 루틴은 쌓지만 당장 자신을 증명할 자신감은 낮아져요',
        'stay': '현재 불펜 역할을 지켜요. 선발 기회를 미루며 자신감은 조금 내줘요',
        'trial': '바로 평가받아 선발 기회를 노려요. 준비가 부족하면 실패 기록과 자신감 저하가 남아요',
        'test': '수업에서 준비한 긴 이닝을 시험해요. 평가에 못 미치면 불펜으로 돌아가요',
        'appeal': '마지막 평가로 선발 자리를 지켜 봐요. 실패하면 불펜 전환에 자신감도 잃어요',
        'accept': '불펜에서 다시 기회를 찾아요. 선발 로테이션의 자리는 내려놔야 해요',
    }
    hint = hints.get(key, hint)
    return dict(key=key, label=label, hint=hint)


def relief_notice(token):
    return dict(kind='pitch_role', background='manager-office', token=token, from_track='SP', mode='relief',
                title='감독의 불펜 전환 통보',
                text='최근 선발 등판의 실점과 이닝 유지가 아쉬워요. 불펜에서 구위를 회복해요. 평가 등판으로 선발 복귀를 요청할 수도 있어요.',
                choices=[choice('accept', '불펜에서 다시 증명할게요', '불펜 전환 후 현재 구위에 맞는 역할로 등판해요'),
                         choice('appeal', '마지막 시험 등판을 부탁드릴게요', '한 차례 5이닝 평가에서 실점을 억제하면 선발 기회를 유지해요')])


def event_view(event):
    return dict(event, choices=[choice(ch['key'], ch['label'], ch.get('hint', '')) for ch in event.get('choices') or []])


def offer(p, totals, token, today=None):
    if not eligible(p):
        return None
    from . import rookie_league as L
    data = dict(B.state(p))
    if data.get('pitch_review_token') == str(token):
        return None
    if data.get('pitch_cooldown_until', 0) > token:
        return None
    project = data.get('starter_course')
    ip = totals.get('outs', 0) / 3
    era = L.pitching(totals)['era'] if ip else 99
    event = None
    if project:
        elapsed = (today.isoformat() > project.get('day', '') and
                   (today - date.fromisoformat(project['day'])).days >= 10) if today else token > project['token']
        if elapsed:
            event = dict(mode='assessment', title='선발 수업의 마지막 평가',
                         text='긴 이닝을 준비해 왔어요. 연습경기 3차례 선발 등판으로 투구 유지력과 실점을 확인해요. 평가 기록은 정규시즌에 더하지 않아요.',
                         choices=[choice('test', '선발 평가 등판을 치를게요', '수업 이수·체력·멘탈과 연습경기 성적으로 전환을 결정해요'),
                                  choice('stay', '불펜 역할에 집중할게요', '수업을 마치고 현재 불펜 보직을 유지해요')])
    elif current(p) == 'RP':
        dominant = ip >= 15 and era <= 2.7 and totals.get('so', 0) >= ip * .75
        if ready(p) or (dominant and p.stats['stamina'] >= W.level(p.league) - 10):
            event = dict(mode='opportunity', title='코치진의 선발 전환 제안',
                         text='불펜에서 보여 준 투구와 체력·멘탈을 보고 선발 가능성을 확인하고 싶어요. 바로 시험 등판을 하거나 선발 수업부터 시작할 수 있어요.',
                         choices=[choice('course', '선발 수업부터 받을게요', '다음 평가까지 불펜에서 뛰며 긴 이닝·구종 배합을 준비해요'),
                                  choice('trial', '시험 선발 등판에 도전할게요', '연습경기 3차례의 내용과 체력으로 판단해요. 준비가 부족하면 실패하기 쉬워요'),
                                  choice('stay', '불펜에서 제 역할을 지킬게요', '현재 역할을 유지해요. 불펜의 성공도 커리어로 인정해요')])
    elif ip >= 25 and (era >= 5.25 or p.stats['stamina'] < W.level(p.league) - 7):
        event = dict(mode='relief', title='감독의 불펜 전환 통보',
                     text='최근 선발 등판의 실점과 이닝 유지가 아쉬워요. 우선 불펜에서 구위를 회복하는 편이 좋겠어요. 충분히 회복하면 다시 선발 기회를 검토해요.',
                     choices=[choice('accept', '불펜에서 다시 증명할게요', '불펜 전환 후 현재 구위에 맞는 역할로 등판해요'),
                              choice('appeal', '마지막 시험 등판을 부탁드릴게요', '한 차례 5이닝 평가에서 실점을 억제하면 선발 기회를 유지해요')])
    if event:
        data['pitch_review_token'] = str(token)
        B.put(p, data)
        return dict(event, kind='pitch_role', background='manager-office', token=token,
                    day=today.isoformat() if today else '', from_track=current(p))
    return None


def set_track(p, track, token, text):
    data = dict(B.state(p))
    data['pitch_track'] = track
    data.pop('starter_course', None)
    data['pitch_cooldown_until'] = token + (1 if hasattr(p, 'flags') else 30)
    history = list(data.get('pitch_history') or [])
    history.append(dict(token=token, track=track, text=text))
    data['pitch_history'] = history[-20:]
    data.pop('pin', None)
    B.put(p, data)
    p.position = track
    if hasattr(p, 'lineup'):
        p.lineup, p.slot = ('sp', M.rotation_rank(p.stats, W.level(p.league))) if track == 'SP' else ('chase', 0)
        p.role_since = date.fromordinal(token)


def resolve(p, event, selected, rng):
    from . import rookie_league as L
    from . import rookie_story as S
    if selected not in [c['key'] for c in event['choices']]:
        raise ValueError('현재 제안에 있는 보직 전환 방법을 골라 주세요.')
    data = dict(B.state(p))
    token = event['token']
    if selected == 'course':
        data['starter_course'] = dict(token=token, day=event.get('day', ''), stamina=p.stats['stamina'])
        data['pitch_cooldown_until'] = token
        B.put(p, data)
        return S.change(p, '선발 수업을 시작했어요. 불펜 등판을 이어가며 다음 평가를 준비해요.', discipline=3, confidence=-2)
    if selected == 'stay':
        data.pop('starter_course', None)
        data['pitch_cooldown_until'] = token + (1 if hasattr(p, 'flags') else 30)
        B.put(p, data)
        return S.change(p, '불펜에서 현재 역할에 집중하기로 했어요. 선발 기회는 잠시 미뤘어요.', confidence=-2)
    if selected == 'accept':
        text = '불펜으로 전환했어요. 현재 구위에 맞는 등판 기회에서 다시 증명해요.'
        set_track(p, 'RP', token, text)
        return text
    stats = dict(p.stats)
    course = event['mode'] == 'assessment'
    completed = course and S.value(p, 'discipline') >= 45
    if completed:
        stats['stamina'] += 1.5
        stats['mental'] += .5
    line = {}
    count = 1 if selected == 'appeal' else 3
    for _ in range(count):
        game = M.starter_game(stats, W.level(p.league), rng)
        line = L.add(line, game['line'])
    ip = line.get('outs', 0) / 3
    era = L.pitching(line)['era'] if ip else 99
    physical = stats['stamina'] >= W.level(p.league) - 5 and stats['mental'] >= W.level(p.league) - 5
    passed = physical and ip >= count * 4.5 and era <= (4.2 if completed else 3.8)
    if selected == 'appeal':
        passed = physical and ip >= 5 and era <= 3.6
    report = f'연습 평가 {count}경기 · {L.ip_text(line.get("outs", 0))}이닝 · ERA {era:.2f}'
    data = dict(B.state(p))
    data['pitch_last_assessment'] = dict(token=token, line=line, passed=passed, practice=True)
    B.put(p, data)
    if passed:
        text = report + ' — 선발 로테이션 기회를 얻었어요.'
        set_track(p, 'SP', token, text)
        return S.change(p, text, confidence=4, trust=2)
    text = report + ' — 긴 이닝 준비가 더 필요해 불펜에서 뛰어요.'
    set_track(p, 'RP', token, text)
    return S.change(p, text, confidence=-2)
