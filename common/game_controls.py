"""DB 게임 설정. 워커의 다음 요청에 반영하고 실행 중인 시즌은 같은 값을 써요."""
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from django.conf import settings
from django.db import OperationalError, ProgrammingError

FEATURES = (
    {'key': 'ROOKIE_SERIES_ENABLED', 'label': '시리즈 전광판', 'description': '라이트·익스트림의 가을야구·국제대회·아마 대회를 경기별로 기록하고 다시 보여 줘요.', 'schema': ('community', '0053_liteseason_series')},
    {'key': 'ROOKIE_ENV_ENABLED', 'label': '경기 환경과 조건부 특성', 'description': '날씨·구장·시즌 루틴·미디어데이·조건부 특성 11종을 함께 사용해요.', 'schema': ('community', '0054_liteseason_env')},
    {'key': 'ROOKIE_EXTREME_ENABLED', 'label': '익스트림 공개', 'description': '회원과 손님에게 익스트림 모드를 공개해요. 기존 선수 기록은 유지해요.', 'schema': ('community', '0052_litecareer_mode')},
    {'key': 'ROOKIE_EXTREME_PREVIEW', 'label': '익스트림 관리자 검증', 'description': '관리자가 비공개 익스트림 검증실을 사용할 수 있게 해요. 일반 공개와 별도로 적용해요.', 'schema': ('community', '0052_litecareer_mode')},
)
FEATURE_KEYS = {f['key'] for f in FEATURES}
STORAGE_MIGRATION = ('common', '0017_game_controls')
_state = ContextVar('game_control_snapshot', default=None)


def environment_value(key):
    value = getattr(settings, key, os.environ.get(key, 'false'))
    return value is True or str(value).lower() in (('true', '1') if key.startswith('ROOKIE_EXTREME') else ('true',))


def read_state():
    from .models import GameControlState
    try:
        return GameControlState.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        return None  # 새 저장소 준비 전에는 기존 환경 설정을 사용해요.


def enabled(key):
    if key not in FEATURE_KEYS:
        raise KeyError(key)
    if not getattr(settings, 'GAME_CONTROLS_USE_DB', True):
        return environment_value(key)
    snapshot = _state.get()
    if snapshot is None:
        state = read_state()
        overrides = state.overrides if state else {}
        return overrides[key] if type(overrides.get(key)) is bool else environment_value(key)
    if not snapshot:
        state = read_state()
        overrides = state.overrides if state else {}
        snapshot.update({k: overrides[k] if type(overrides.get(k)) is bool else environment_value(k) for k in FEATURE_KEYS})
    return snapshot[key]


@contextmanager
def snapshot_scope():
    if _state.get() is not None:
        yield
        return
    token = _state.set({})
    try:
        yield
    finally:
        _state.reset(token)


def feature_snapshot(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with snapshot_scope():
            return func(*args, **kwargs)
    return wrapped


class GameControlMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with snapshot_scope():
            return self.get_response(request)
