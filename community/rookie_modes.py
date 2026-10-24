"""라이트·익스트림의 규칙·저장 경계와 공개·실험실 접근을 정의해요."""
import os
from django.conf import settings

LITE, EXTREME = 'lite', 'extreme'
CHOICES = [(LITE, '라이트 모드'), (EXTREME, '익스트림 모드')]
START_BONUS, POTENTIAL_BONUS, TRAIN_MULTIPLIER, OPPONENT_BONUS = 5.0, 8, 1.35, 5.0


def is_extreme(c):
    return getattr(c, 'mode', LITE) == EXTREME


def preview_enabled():
    configured = getattr(settings, 'ROOKIE_EXTREME_PREVIEW', os.environ.get('ROOKIE_EXTREME_PREVIEW', 'false'))
    return configured is True or str(configured).lower() in ('true', '1')


def public_enabled():
    configured = getattr(settings, 'ROOKIE_EXTREME_ENABLED', os.environ.get('ROOKIE_EXTREME_ENABLED', 'false'))
    return configured is True or str(configured).lower() in ('true', '1')


def allowed(user):
    return bool(preview_enabled() and user and user.is_authenticated and user.is_active and user.is_staff)


def validate_create(user, mode):
    if mode not in dict(CHOICES):
        raise ValueError('플레이 모드를 다시 확인해 주세요.')
    if mode == EXTREME and not (public_enabled() or allowed(user)):
        raise ValueError('익스트림 모드는 비공개 검증 중이에요.')


def opponent_bonus(c):
    if not is_extreme(c):
        return 0.0
    return (((c.flags or {}).get('extreme') or {}).get('rules') or {}).get('opponent', OPPONENT_BONUS)


def training_multiplier(c):
    if not is_extreme(c):
        return 1.0
    effects = ((c.flags or {}).get('extreme') or {}).get('season') or {}
    rules = ((c.flags or {}).get('extreme') or {}).get('rules') or {}
    return rules.get('training', TRAIN_MULTIPLIER) * (1 + max(-.35, min(.25, effects.get('training', 0))))


def injury_extra(c):
    if not is_extreme(c):
        return 0.0
    return max(0, min(.12, (((c.flags or {}).get('extreme') or {}).get('season') or {}).get('risk', 0)))
