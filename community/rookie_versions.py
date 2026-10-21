"""정식·라이트 커리어의 시작 버전. 기존 JSON을 읽으며 과거 기록은 수정하지 않아요."""
from django.db.models import Q

CURRENT = '1.1'
LEGACY = '1.0'
CHOICES = ((CURRENT, '1.1'), (LEGACY, '1.0'))


def selected(value):
    return value if value in dict(CHOICES) else CURRENT


def of(player):
    data = (player.flags if hasattr(player, 'flags') else player.career) or {}
    return data.get('game_version') or LEGACY


def filter_by_version(qs, version, field):
    """버전 표식이 없는 기존 커리어도 1.0으로 묶고, 조회 제한 전에 걸러요."""
    key = f'{field}__game_version'
    version = selected(version)
    if version == LEGACY:
        return qs.filter(Q(**{key: LEGACY}) | Q(**{key + '__isnull': True}) |
                         Q(**{key: None}) | Q(**{key: ''}))
    return qs.filter(**{key: version})
