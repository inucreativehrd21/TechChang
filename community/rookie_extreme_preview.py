"""운영자 실험실과 로컬 회귀 도구가 함께 쓰는 시제품 진행기예요."""
import hashlib
import json
import random

from . import rookie_extreme as E
from . import rookie_lite as X
from . import rookie_modes as Modes


def token(c):
    data = [c.pk, c.year, c.pending, (c.flags or {}).get('extreme')]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def random_for(c, purpose):
    seed = ((c.flags or {}).get('extreme') or {}).get('seed', (c.flags or {}).get('evaluation_seed', 20261024))
    return random.Random(f'extreme-preview-v1:{seed}:{c.year}:{purpose}')


def advance(c, expected_token, *, allow_lite=False):
    """전용 사건은 직접 답하고 일반 경기·진로는 자동 진행해 다음 비시즌에 멈춰요."""
    if (not Modes.is_extreme(c) and not (allow_lite and c.mode == Modes.LITE)) or c.retired_at or token(c) != expected_token:
        raise E.ExtremeError('이미 처리했거나 바뀐 장면이에요. 현재 화면을 다시 확인해 주세요.')
    if (c.pending or {}).get('kind') != 'plan':
        raise E.ExtremeError('현재 비시즌 화면을 다시 확인해 주세요.')
    if E.event_view(c):
        raise E.ExtremeError('전용 이벤트에 먼저 답해 주세요.')
    from .management.commands.rookie_balance import choose
    rng = random_for(c, 'season')
    first_year = c.year
    for _ in range(100):
        pending = c.pending
        if c.retired_at or (pending.get('kind') == 'plan' and c.year > first_year):
            c.save()
            return
        if pending['kind'] == 'plan':
            event = pending.get('event')
            ordinary_choice = X.EVENTS[event]['choices'][0][0] if event else ''
            X.run_season(c, X.pick_programs(c, rng), 'normal', ordinary_choice, rng,
                         intl={key: 'skip' for key in pending.get('intl') or []})
        elif pending['kind'] == 'review':
            X.next_season(c, rng)
        elif pending['kind'] == 'decision':
            X.decide(c, pending['what'], choose(c, rng, 'playing'), rng)
            c.save()
        else:
            break
    raise E.ExtremeError('진행을 완료하지 못했어요. 저장 상태를 확인해 주세요.')
