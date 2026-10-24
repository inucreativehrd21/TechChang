"""비공개 시제품: 지속 경쟁자·12개 전용 사건·선택의 실제 효과. AI 호출은 없어요."""
from copy import deepcopy
import hashlib
import secrets

from django.db import transaction
from django.utils import timezone

from . import rookie_modes as Modes
from . import rookie_world as W


class ExtremeError(ValueError):
    pass


# 훈련 보정·부상 위험·신뢰·관계의 교환을 선택 전에 모두 공개해요.
def choice(key, label, training=0, risk=0, trust=0, respect=0, rivalry=0, contest=False):
    return dict(key=key, label=label, training=training, risk=risk, trust=trust,
                respect=respect, rivalry=rivalry, contest=contest)


EVENTS = {
    'school_joint': dict(phase='school', title='동기와 합동 훈련', rival='school', choices=[
        choice('push', '함께 한계에 도전해요', .12, .02, respect=4, contest=True), choice('pace', '몸 상태에 맞춰 훈련해요', respect=2)]),
    'school_starter': dict(phase='school', title='공개 주전 경쟁', rival='school', choices=[
        choice('compete', '정면으로 경쟁해요', .08, .02, rivalry=5, contest=True), choice('team', '팀 훈련을 도와요', trust=1, respect=3)]),
    'school_promise': dict(phase='school', title='결승 전 약속', rival='school', choices=[
        choice('extra', '함께 남아 준비해요', .10, .03, respect=4, contest=True), choice('rest', '충분히 쉬고 만나기로 해요', respect=1)]),
    'pro_partner': dict(phase='pro', title='훈련 파트너 선택', rival='pro', choices=[
        choice('pair', '프로 동기와 집중 훈련해요', .12, .02, respect=4), choice('solo', '내 페이스로 준비해요', .04)]),
    'pro_research': dict(phase='pro', title='함께 연구하는 새 접근', rival='pro', choices=[
        choice('research', '실험하며 경쟁해요', .15, .03, rivalry=4, contest=True), choice('steady', '검증된 방식을 함께 다듬어요', .04, respect=2)]),
    'pro_spotlight': dict(phase='pro', title='구단 공개 쇼케이스', rival='pro', choices=[
        choice('show', '동기와 함께 도전해요', .06, .02, rivalry=4, contest=True), choice('support', '이번엔 동료를 도와요', trust=1, respect=4)]),
    'overseas_arrival': dict(phase='overseas', title='같은 무대에 선 경쟁자', rival='overseas', choices=[
        choice('challenge', '새 무대에서 승부해요', .08, .02, rivalry=5, contest=True), choice('learn', '상대의 준비 방식을 배워요', .04, respect=3)]),
    'overseas_adapt': dict(phase='overseas', title='현지 적응 동행', rival='overseas', choices=[
        choice('join', '새 훈련에 함께 적응해요', .12, .02, respect=5), choice('routine', '익숙한 루틴부터 지켜요', .03)]),
    'overseas_lead': dict(phase='overseas', title='대표팀 공동 리더', rival='overseas', choices=[
        choice('lead', '훈련까지 함께 이끌어요', .08, .03, trust=2, respect=4), choice('share', '동료에게 역할을 나눠요', trust=1, respect=2)]),
    'veteran_last': dict(phase='veteran', title='경쟁자와 마지막 맞대결', rival='pro', choices=[
        choice('duel', '마지막 승부를 준비해요', .10, .04, rivalry=5, contest=True), choice('salute', '서로의 커리어를 응원해요', respect=6)]),
    'veteran_mentor': dict(phase='veteran', title='후배 멘토링', rival='school', choices=[
        choice('mentor', '내 훈련을 나눠 후배를 도와요', -.10, trust=3, respect=5), choice('focus', '올해는 내 몸에 집중해요', .04)]),
    'veteran_title': dict(phase='veteran', title='마지막 우승을 위한 캠프', rival='pro', choices=[
        choice('allin', '동료와 마지막 캠프를 열어요', .15, .05, respect=4, contest=True), choice('manage', '몸을 관리하며 준비해요', .02, respect=2)]),
}
NAMES = ('이도윤', '정시우', '강지호', '서준서', '한서진', '오도현', '유건우', '신주원', '차민준', '임지후', '장하준', '백서우')


def initialize(c, rng):
    if not Modes.is_extreme(c):
        return
    c.potential = min(99, c.potential + Modes.POTENTIAL_BONUS)
    c.stats = {k: min(99.0, round(v + Modes.START_BONUS, 1)) for k, v in c.stats.items()}
    names = rng.sample(NAMES, 3)
    c.flags = dict(c.flags, extreme={
        'version': 1, 'updated_year': c.year, 'history': [], 'last_events': {}, 'season': {},
        'rules': {'training': Modes.TRAIN_MULTIPLIER, 'opponent': Modes.OPPONENT_BONUS},
        'rivals': [dict(id=key, name=names[i], level=round(34 + i * 3 + rng.uniform(0, 5), 1),
                        potential=rng.randint(82, 96), respect=0, rivalry=0, wins=0, losses=0)
                   for i, key in enumerate(('school', 'pro', 'overseas'))],
    })


def phase(c):
    if c.age >= 33:
        return 'veteran'
    if not W.is_pro(c.league):
        return 'school'
    return 'overseas' if W.system_of(c.league) in ('mlb', 'npb', 'cpbl') else 'pro'


def offer(c, rng):
    if not Modes.is_extreme(c):
        return None
    state = deepcopy((c.flags or {}).get('extreme') or {})
    if not state.get('rivals'):
        raise ExtremeError('익스트림 저장 상태를 확인해 주세요.')
    if (state.get('pending') or {}).get('year') == c.year:
        return event_view(c)
    # 새로고침·계획 재생성으로 한 시즌에 여러 사건을 얻지 않아요.
    if any(record['year'] == c.year for record in state.get('history', [])):
        return None
    last = state.get('last_events') or {}
    pool = [key for key, event in EVENTS.items() if event['phase'] == phase(c) and c.year - last.get(key, -3) >= 3]
    if not pool:
        return None
    key = rng.choice(pool)
    nonce = rng.getrandbits(96)
    state['pending'] = dict(key=key, year=c.year, id=hashlib.sha256(f'{c.pk}:{c.user_id}:{c.year}:{key}:{nonce}'.encode()).hexdigest()[:32])
    c.flags = dict(c.flags, extreme=state)
    return event_view(c)


def event_view(c):
    state = (c.flags or {}).get('extreme') or {}
    pending = state.get('pending')
    if not pending:
        return None
    event = deepcopy(EVENTS[pending['key']])
    rival = next(r for r in state['rivals'] if r['id'] == event['rival'])
    event.update(id=pending['id'], key=pending['key'], year=pending['year'], rival=deepcopy(rival),
                 success_percent=round(max(.2, min(.8, .5 + (c.ovr - rival['level']) / 60)) * 100))
    event['success_effects'] = '성공하면 능력치 2개 최대 +3, 감독 신뢰 +4 추가'
    event['failure_effects'] = '실패하면 능력치 2개 최대 −4, 이번 시즌 훈련 보정 −35%, 부상 위험 +6%p, 감독 신뢰 −7 추가'
    return event


def apply_choice(c, event_id, choice_key, rng):
    if not Modes.is_extreme(c):
        raise ExtremeError('익스트림 커리어에서만 선택할 수 있어요.')
    if c.retired_at or (c.pending or {}).get('kind') != 'plan':
        raise ExtremeError('지금은 비시즌 이벤트에 답할 차례가 아니에요.')
    state = deepcopy((c.flags or {}).get('extreme') or {})
    pending = state.get('pending') or {}
    if pending.get('year') != c.year or not secrets.compare_digest(str(pending.get('id', '')), str(event_id)):
        raise ExtremeError('이미 처리했거나 바뀐 장면이에요. 현재 화면을 다시 확인해 주세요.')
    event = EVENTS[pending['key']]
    picked = next((x for x in event['choices'] if x['key'] == choice_key), None)
    if picked is None:
        raise ExtremeError('이 장면의 선택지를 골라 주세요.')
    rival = next(r for r in state['rivals'] if r['id'] == event['rival'])
    season = state.setdefault('season', {})
    before_training, before_risk = season.get('training', 0), season.get('risk', 0)
    season['training'] = max(-.2, min(.25, before_training + picked['training']))
    season['risk'] = max(0, min(.12, before_risk + picked['risk']))
    relation_changes = {}
    for field in ('respect', 'rivalry'):
        before = rival[field]
        rival[field] = max(-100, min(100, rival[field] + picked[field]))
        relation_changes[field] = rival[field] - before
    trust = picked['trust']
    success = None
    stat_changes = []
    if picked['contest']:
        probability = max(.2, min(.8, .5 + (c.ovr - rival['level']) / 60))
        success = rng.random() < probability
        rival['wins' if success else 'losses'] += 1
        trust += 4 if success else -7
        from . import rookie as R, rookie_lite as X
        keys = rng.sample(list(c.stats), min(2, len(c.stats)))
        for key in keys:
            old = float(c.stats[key])
            value = round(max(old, min(X.stat_pot(c, key), old + 3)) if success else max(25, old - 4), 1)
            c.stats = dict(c.stats, **{key: value})
            delta = round(value-old, 1)
            label = next(lab for k, lab, _ in R.ROLES[c.role]['stats'] if k == key)
            stat_changes.append(dict(key=key, label=label, before=old, after=value, delta=delta))
            X._note(c, key, delta, '익스트림 도전 성공' if success else '익스트림 도전 실패')
        c.ovr = R.overall(c.role, c.stats)
        c.best_ovr = max(c.best_ovr, c.ovr)
        if not success:
            season['training'] = max(-.35, before_training-.35)
            season['risk'] = min(.12, season['risk']+.06)
    before_trust = c.flags.get('trust', 50)
    after_trust = max(0, min(100, before_trust + trust))
    record = dict(year=c.year, key=pending['key'], choice=choice_key, rival=rival['id'], success=success,
                  training=round(season['training'] - before_training, 4), risk=round(season['risk'] - before_risk, 4),
                  trust=after_trust - before_trust, stats=stat_changes, **relation_changes)
    state['history'] = (state.get('history', []) + [record])[-120:]
    state.setdefault('last_events', {})[pending['key']] = c.year
    state.pop('pending', None)
    c.flags = dict(c.flags, extreme=state, trust=after_trust)
    return record


@transaction.atomic
def resolve(career_id, user, event_id, choice_key, rng):
    """행 잠금 뒤 다시 읽어 중복 제출·낡은 탭의 선택을 거절해요."""
    from .models import LiteCareer
    if not Modes.allowed(user):
        raise ExtremeError('익스트림 모드는 비공개 검증 중이에요.')
    c = LiteCareer.objects.select_for_update().get(pk=career_id, user=user, mode=Modes.EXTREME)
    result = apply_choice(c, event_id, choice_key, rng)
    changed = LiteCareer.objects.filter(pk=c.pk, mode=Modes.EXTREME, year=c.year, retired_at__isnull=True,
                                        flags__extreme__pending__id=event_id).update(flags=c.flags, stats=c.stats, ovr=c.ovr,
                                                                                  best_ovr=c.best_ovr, updated_at=timezone.now())
    if changed != 1:
        raise ExtremeError('이미 처리했거나 바뀐 장면이에요. 현재 화면을 다시 확인해 주세요.')
    return result


def complete_year(c):
    if not Modes.is_extreme(c):
        return
    state = deepcopy(c.flags['extreme'])
    if state.get('updated_year', 0) < c.year:
        for year in range(state.get('updated_year', c.year - 1) + 1, c.year + 1):
            age = c.age - (c.year - year)
            gain = 4.0 if age <= 22 else 2.0 if age <= 28 else .5 if age <= 32 else -.8
            for rival in state['rivals']:
                rival['level'] = round(max(25, min(rival['potential'], rival['level'] + gain)), 1)
        state['updated_year'] = c.year
        state['season'] = {}
    c.flags = dict(c.flags, extreme=state)
