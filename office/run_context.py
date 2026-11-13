"""B안 실행 예산·구독 응답 체크포인트. 원문·프롬프트는 공개하지 않는다."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
import functools

_current = ContextVar('office_run_context', default=None)


class RunBudgetExceeded(RuntimeError):
    pass


class RunContext:
    def __init__(self, *, run_id=None, root=None, dry=False, max_calls=24, max_seconds=2400, max_codex_tokens=None):
        self.run_id = str(uuid.UUID(str(run_id))) if run_id else str(uuid.uuid4())
        self.max_calls, self.max_seconds = max_calls, max_seconds
        # 0 이면 끔. 기본은 v2 파일럿(약 118만) 아래 — 사실 관문이 원장 대조로 바뀌면 낮춘다
        if max_codex_tokens is None:
            from .switches import get
            max_codex_tokens = int(get('run_max_codex_tokens'))   # .env → 관리 화면 설정 → 기본 100만
        self.max_codex_tokens = max_codex_tokens
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.path = Path(root) / (self.run_id + '.json') if root is not None and not dry else None
        self.data = {'version': 1, 'run_id': self.run_id, 'calls': 0, 'spent_seconds': 0,
                     'reused': 0, 'responses': {}, 'metadata': {}}
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('version') != 1 or self.data.get('run_id') != self.run_id:
                raise ValueError('지원하지 않는 연구실 체크포인트예요.')
            from .release import code_fingerprint
            if self.data.get('metadata', {}).get('code_fingerprint') != code_fingerprint():
                raise ValueError('체크포인트와 현재 소스 버전이 달라요. 이전 원고를 확인한 뒤 새 실행을 시작해 주세요.')
        from .release import code_fingerprint
        self.data['metadata']['code_fingerprint'] = code_fingerprint()
        from .model_router import profile
        saved_profile = self.data['metadata'].get('profile')
        if saved_profile and saved_profile != profile():
            raise ValueError('체크포인트의 제작 프로필과 현재 프로필이 달라요.')
        self.data['metadata']['profile'] = profile()
        self.previous_seconds = float(self.data['spent_seconds'])
        self.active_calls = []
        self.previous_calls = list(self.data.get('call_records', []))
        self.recorded_call_ids = set()

    def remaining(self):
        return self.max_seconds - self.previous_seconds - (time.monotonic()-self.started)

    def budget(self):
        """중단 원인과 자동 보완 착수 판단에 같은 잔여 예산을 쓴다."""
        with self.lock:
            return {'calls': self.data['calls'], 'max_calls': self.max_calls,
                    'remaining_calls': max(0, self.max_calls - self.data['calls']),
                    'remaining_seconds': max(0, round(self.remaining(), 2)),
                    'max_seconds': self.max_seconds, 'codex_tokens': self.codex_tokens(),
                    'max_codex_tokens': self.max_codex_tokens}

    def can_start_revision(self, *, calls=9, seconds=600):
        """패치·재검증·도판·평론·3인 심사까지 마칠 여유가 있을 때만 보완한다.

        재시도까지 보장하는 예약은 아니다. 실제 호출의 hard cap은 reserve가 계속 검사한다.
        """
        budget = self.budget()
        return (budget['remaining_calls'] >= calls and budget['remaining_seconds'] >= seconds
                and (not self.max_codex_tokens or budget['codex_tokens'] < self.max_codex_tokens))

    def codex_tokens(self) -> int:
        """이 실행이 Codex 구독에 보낸 입력 토큰(재개 전 기록 포함). 끝난 호출만 센다."""
        return sum(int(c.get('input_tokens') or 0) for c in [*self.previous_calls, *self.active_calls]
                   if isinstance(c, dict) and (c.get('direct_provider') == 'codex' or c.get('backend') == 'codex_cli'))

    def reserve(self):
        from .execution import assert_current
        assert_current()
        with self.lock:
            if self.data['calls'] >= self.max_calls:
                raise RunBudgetExceeded(f"연구실 호출 예산 {self.data['calls']}/{self.max_calls}회를 소진했어요. "
                                        '검증 기준을 낮추지 않고 보류해요.')
            if self.remaining() <= 0:
                raise RunBudgetExceeded(f'연구실 시간 예산 {self.max_seconds}초를 소진했어요. '
                                        '검증 기준을 낮추지 않고 보류해요.')
            if self.max_codex_tokens and self.codex_tokens() >= self.max_codex_tokens:
                # 2026-10-31: 보류된 글 한 편이 Codex 5시간 한도의 절반 가까이를 썼다. 호출 수·시간만으로는 못 막는다.
                raise RunBudgetExceeded(f'Codex 입력 {self.codex_tokens():,}토큰으로 실행 상한'
                                        f'({self.max_codex_tokens:,})에 닿았어요. 검증 기준을 낮추지 않고 보류해요.')
            self.data['calls'] += 1
            self.save()
            return max(1, min(1200, int(self.remaining())))

    def cached(self, signature):
        with self.lock:
            found = self.data['responses'].get(signature)
            if found is not None:
                self.data['reused'] += 1
            return found

    def remember(self, signature, text):
        if not text.strip():
            return
        with self.lock:
            self.data['responses'][signature] = text
            self.save()

    def metadata(self, **values):
        with self.lock:
            self.data['metadata'].update(values)
            self.save()
        if os.environ.get('LAB_JOB_ID') and values.get('draft_id'):
            from .models import JobRequest
            from django.utils import timezone
            JobRequest.objects.filter(pk=os.environ['LAB_JOB_ID'], execution_id=os.environ.get('LAB_EXECUTION_ID'),
                  status='started', lease_until__gt=timezone.now()).update(draft_id=values['draft_id'], checkpoint_run_id=self.run_id)

    def save(self):
        if not self.path:
            return
        self.data['spent_seconds'] = round(self.previous_seconds + time.monotonic()-self.started, 2)
        self.data['call_records'] = self.previous_calls + list(self.active_calls)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        from .artifacts import atomic_write
        atomic_write(self.path, json.dumps(self.data, ensure_ascii=False).encode('utf-8'), private=True)


def current():
    return _current.get()


def signature(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@contextmanager
def execution_lock(path):
    """동일 체크포인트를 두 프로세스가 덮어쓰지 못하게 즉시 거절한다."""
    if path is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0'); handle.flush()
        try:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('같은 연구 실행을 다른 프로세스가 진행 중이에요.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def bounded_run(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from django.conf import settings
        with run_context(root=Path(settings.BASE_DIR)/'logs/lab-runs', dry=kwargs.get('dry', False)):
            return fn(*args, **kwargs)
    return wrapper


@contextmanager
def run_context(*, run_id=None, root=None, dry=False):
    from .model_router import profile
    if current() is not None:
        yield current()
        return
    rid = str(uuid.UUID(str(run_id))) if run_id else str(uuid.uuid4())
    path = Path(root)/(rid+'.lock') if root is not None and not dry else None
    with execution_lock(path):
        context = RunContext(run_id=rid, root=root, dry=dry)
        token = _current.set(context)
        try:
            from common.services.claude import call_tags, track_calls
            with call_tags(run_id=rid, profile=profile()), track_calls(alert=False, filter={'run_id': rid}) as calls:
                context.active_calls = calls
                yield context
        finally:
            with context.lock:
                context.save()
            _current.reset(token)
