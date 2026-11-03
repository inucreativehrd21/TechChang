"""연구실 기능 스위치 — 관리 화면(/lab/admin/ 설정 탭)에서 켜고 끈다.

값을 정하는 순서: 서버 .env(같은 이름의 환경변수) → 관리 화면에서 바꾼 값(LabSwitch) → 기본값.
.env 에 적힌 값은 서버 운영자가 일부러 고정한 것이라 화면에서 바꿀 수 없게 보여 준다. 파일럿 스크립트·테스트도
환경변수로 켜므로 이 순서를 지켜야 한다.

제작 작업(office_publish·office_revise 등)은 실행마다 새 프로세스라 바꾼 값이 다음 실행부터 반영된다.
DB 를 못 읽으면(마이그레이션 전·DB 없는 테스트) 기본값을 쓴다 — 스위치 하나 때문에 제작이 멈추지 않게.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TRUE = ('1', 'true', 'yes', 'on')
FALSE = ('0', 'false', 'no', 'off')
CACHE_SECONDS = 10


@dataclass(frozen=True)
class Switch:
    key: str
    env: str
    kind: str                     # bool | choice | int
    default: object
    label: str
    help: str
    group: str
    choices: tuple = ()           # choice: ((값, 이름), ...)
    minimum: int = 0
    maximum: int = 0
    needs_b: bool = False         # B 프로필에서만 쓰인다
    needs_genres: bool = False    # 튜토리얼 틀(장르)이 켜져 있어야 쓰인다
    env_only: str = ''            # 비어 있지 않으면 화면에서 못 바꾼다 — 그 이유
    warn: str = ''                # 켜거나 바꿀 때 확인 문구
    unit: str = ''


GROUPS = (
    ('mode', '제작 방식', '칼럼을 어떤 구성으로 만들지 정해요. 바꾸면 다음 제작부터 적용돼요.'),
    ('gate', 'B안 사실 검증', '독립 검증(Codex)이 근거를 어떻게 확인할지 정해요. 제작 방식이 B일 때만 쓰여요.'),
    ('tutorial', '코딩 튜토리얼 품질 장치', '실행 근거를 먼저 만들고 반복 오류를 끝까지 고치게 하는 장치예요.'),
    ('ops', '운영 안전장치', '멈춘 작업 복구와 동시 실행 같은 운영 설정이에요.'),
)

SWITCHES = (
    Switch('profile', 'OFFICE_MODEL_PROFILE', 'choice', 'a', '제작 프로필',
           'A는 지금 운영 중인 방식이에요. B는 Codex가 원고를 독립 검증해요(한 편에 Codex 약 20만~40만 토큰).',
           'mode', choices=(('a', 'A · 운영 기본'), ('b', 'B · 독립 검증'), ('legacy', '이전 방식')),
           warn='B로 바꾸면 다음 제작부터 Codex 독립 검증을 써요(한 편에 약 20만~40만 토큰). 바꿀까요?'),
    Switch('genres', 'OFFICE_GENRES', 'bool', False, '장르별 구성(코딩=튜토리얼)',
           '코딩 칼럼을 "어디서 막히나·판단 기준·실행 예제" 튜토리얼 틀로 써요. 끄면 모든 분야가 기존 데이터 틀이에요.',
           'mode', warn='켜면 다음 코딩 칼럼부터 구성이 튜토리얼로 바뀌어요. 켤까요?'),
    Switch('grounded_check', 'OFFICE_GROUNDED_CHECK', 'bool', True, '원장 대조 검증',
           '웹 검색 대신 확인된 인용·받은 문서·실행 결과(원장)와 대조해 사실을 판정해요. 끄면 예전 웹 검증이에요.',
           'gate', needs_b=True),
    Switch('source_fetch', 'OFFICE_SOURCE_FETCH', 'bool', True, '공식 문서 직접 받기',
           '원고가 기대는 공식 문서를 서버가 받아 원장에 넣어요(https·공인 주소만, 한 편 최대 6개).',
           'gate', needs_b=True),
    Switch('grounded_web_max', 'OFFICE_GROUNDED_WEB_MAX', 'int', 0, '원장 밖 주장 웹 확인 개수',
           '원장에 없는 주장 중 웹으로 더 확인할 개수예요. 하나당 Codex 입력이 크게 늘어서 기본은 0이에요.',
           'gate', minimum=0, maximum=10, needs_b=True, unit='개'),
    Switch('run_max_codex_tokens', 'OFFICE_RUN_MAX_CODEX_TOKENS', 'int', 1_000_000, '한 편당 Codex 입력 상한',
           '한 번의 제작에서 Codex 입력이 이만큼을 넘으면 멈추고 보류해요. 0이면 상한 없음이에요.',
           'gate', minimum=0, maximum=5_000_000, needs_b=True, unit='토큰'),
    Switch('run_first', 'OFFICE_RUN_FIRST', 'bool', True, '사실 검증 전에 실행 예제 고치기',
           '실행할 수 없는 예제·실패한 테스트·단정 문장이 있으면 사실 검증에 들어가기 전에 한 번 고쳐요.',
           'tutorial', needs_b=True, needs_genres=True),
    Switch('settle_leftovers', 'OFFICE_SETTLE_LEFTOVERS', 'bool', True, '패치 뒤 남은 틀린 문장 다시 고치기',
           '편집 패치 뒤에도 검증에서 틀림·원장 밖으로 판정된 문장이 그대로 남았으면 그 문장만 한 번 더 고쳐요.',
           'tutorial', needs_b=True),
    Switch('hedge_reject', 'OFFICE_HEDGE_REJECT', 'bool', True, '추론으로 약하게 바꾸는 수정 거절',
           '근거 없는 문장을 "필자의 추론", "~로 보입니다"로 바꾸는 패치를 받지 않아요. 근거로 바꾸거나 지워야 해요.',
           'tutorial'),
    Switch('code_run', 'OFFICE_CODE_RUN', 'bool', False, '본문 코드 실행 검증',
           '본문의 모델·테스트 코드를 임시 앱에서 실제로 실행해 결과를 근거로 써요.',
           'tutorial', env_only='모델이 쓴 코드를 격리 없이 실행해서 화면에서는 켤 수 없어요. 로컬 파일럿에서만 써요.'),
    Switch('orphan_recover', 'OFFICE_ORPHAN_RECOVER', 'bool', True, '끊긴 재작성 자동 복구',
           '배포 재시작 등으로 "재작성 중"에 멈춘 원고를 10분마다 찾아 검수 대기로 되돌리고 같은 지시로 다시 돌려요.',
           'ops'),
    Switch('parallel', 'OFFICE_PARALLEL', 'bool', True, '검증·평론 동시 실행',
           '사실 검증과 평론처럼 서로 기다릴 필요 없는 단계를 함께 돌려 제작 시간을 줄여요.', 'ops'),
    Switch('max_workers', 'OFFICE_MAX_WORKERS', 'int', 3, '동시 실행 수',
           '동시에 돌리는 단계 수의 최대값이에요. 구독 한도에 자주 걸리면 줄여요.',
           'ops', minimum=1, maximum=6, unit='개'),
)
BY_KEY = {s.key: s for s in SWITCHES}
_cache: dict = {'at': 0.0, 'rows': {}}


def _parse(spec: Switch, raw):
    """문자열 → 스위치 값. 해석할 수 없으면 None."""
    text = str(raw).strip().lower()
    if spec.kind == 'bool':
        return True if text in TRUE else False if text in FALSE else None
    if spec.kind == 'choice':
        return text if text in {c for c, _ in spec.choices} else None
    try:
        n = int(text.replace(',', '').replace('_', ''))
    except ValueError:
        return None
    return n if spec.minimum <= n <= spec.maximum else None


def _rows() -> dict:
    now = time.monotonic()
    if now - _cache['at'] < CACHE_SECONDS:
        return _cache['rows']
    rows = {}
    try:
        from .models import LabSwitch
        rows = {r.key: r for r in LabSwitch.objects.select_related('updated_by')}
    except Exception as exc:  # noqa: BLE001 — DB 를 못 읽으면 기본값으로(마이그레이션 전·DB 없는 테스트)
        logger.debug('스위치 DB 읽기 실패 — 기본값 사용: %s', exc)
        return {}
    _cache.update(at=now, rows=rows)
    return rows


def clear_cache():
    _cache.update(at=0.0, rows={})


def resolve(key: str) -> tuple:
    """(값, 출처) — 출처는 'env'·'admin'·'default'."""
    spec = BY_KEY[key]
    raw = os.environ.get(spec.env)
    if raw is not None and raw.strip() != '':
        value = _parse(spec, raw)
        if value is not None:
            return value, 'env'
        logger.warning('환경변수 %s=%r 를 해석할 수 없어 무시해요', spec.env, raw)
    if not spec.env_only:
        row = _rows().get(key)
        value = _parse(spec, row.value) if row else None
        if value is not None:
            return value, 'admin'
    return spec.default, 'default'


def get(key: str):
    return resolve(key)[0]


def set_value(key: str, raw, user=None):
    """관리 화면에서 값을 바꾼다. 서버 .env 로 고정됐거나 화면에서 못 바꾸는 스위치면 ValueError."""
    from .models import LabSwitch
    spec = BY_KEY[key]
    if spec.env_only:
        raise ValueError(spec.env_only)
    if resolve(key)[1] == 'env':
        raise ValueError(f'서버 설정 파일(.env)의 {spec.env} 로 고정돼 있어요.')
    value = _parse(spec, raw)
    if value is None:
        raise ValueError(f'{spec.label} 값이 올바르지 않아요.')
    stored = ('on' if value else 'off') if spec.kind == 'bool' else str(value)
    LabSwitch.objects.update_or_create(key=key, defaults={'value': stored, 'updated_by': user})
    clear_cache()
    logger.info('연구실 스위치 변경: %s=%s (by %s)', key, stored, getattr(user, 'username', '-'))
    return value


def reset(key: str):
    from .models import LabSwitch
    LabSwitch.objects.filter(key=key).delete()
    clear_cache()


def panel() -> list[dict]:
    """관리 화면 설정 탭 — 묶음별 스위치와 지금 값·출처·쓰임 여부."""
    profile_b = get('profile') == 'b'
    genres_on = bool(get('genres'))
    rows = _rows()
    groups = []
    for gkey, title, intro in GROUPS:
        items = []
        for spec in (s for s in SWITCHES if s.group == gkey):
            value, source = resolve(spec.key)
            idle = []
            if spec.needs_b and not profile_b:
                idle.append('제작 프로필이 B일 때만 쓰여요')
            if spec.needs_genres and not genres_on:
                idle.append('장르별 구성이 켜져 있어야 쓰여요')
            row = rows.get(spec.key) if source == 'admin' else None
            items.append({
                'spec': spec, 'value': value, 'source': source, 'idle': ' · '.join(idle),
                'changed': value != spec.default, 'row': row,
                'locked': spec.env_only or (f'서버 설정 파일(.env)의 {spec.env} 로 고정돼 있어요.'
                                            if source == 'env' else ''),
                'default_label': value_label(spec, spec.default), 'value_label': value_label(spec, value),
            })
        groups.append({'key': gkey, 'title': title, 'intro': intro, 'items': items})
    return groups


def summary() -> str:
    """관리 화면 위쪽 한 줄 — 지금 제작 방식."""
    profile = dict(BY_KEY['profile'].choices).get(get('profile'), get('profile'))
    return f'{profile} · 장르별 구성 {"켜짐" if get("genres") else "꺼짐"}'


def value_label(spec: Switch, value) -> str:
    if spec.kind == 'bool':
        return '켜짐' if value else '꺼짐'
    if spec.kind == 'choice':
        return dict(spec.choices).get(value, str(value))
    return f'{value:,}{spec.unit}'
