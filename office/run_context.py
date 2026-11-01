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
        self.max_codex_tokens = (int(os.environ.get('OFFICE_RUN_MAX_CODEX_TOKENS', '1000000'))
                                 if max_codex_tokens is None else max_codex_tokens)
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.path = Path(root) / (self.run_id + '.json') if root is not None and not dry else None
        self.data = {'version': 1, 'run_id': self.run_id, 'calls': 0, 'spent_seconds': 0,
                     'reused': 0, 'responses': {}, 'metadata': {}}
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('version') != 1 or self.data.get('run_id') != self.run_id:
                raise ValueError('지원하지 않는 연구실 체크포인트예요.')
        self.previous_seconds = float(self.data['spent_seconds'])
        self.active_calls = []
        self.previous_calls = list(self.data.get('call_records', []))
        self.recorded_call_ids = set()

    def remaining(self):
        return self.max_seconds - self.previous_seconds - (time.monotonic()-self.started)

    def codex_tokens(self) -> int:
        """이 실행이 Codex 구독에 보낸 입력 토큰(재개 전 기록 포함). 끝난 호출만 센다."""
        return sum(int(c.get('input_tokens') or 0) for c in [*self.previous_calls, *self.active_calls]
                   if isinstance(c, dict) and (c.get('direct_provider') == 'codex' or c.get('backend') == 'codex_cli'))

    def reserve(self):
        with self.lock:
            if self.data['calls'] >= self.max_calls or self.remaining() <= 0:
                raise RunBudgetExceeded('연구실 실행 예산을 소진했어요. 검증 기준을 낮추지 않고 보류해요.')
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

    def save(self):
        if not self.path:
            return
        self.data['spent_seconds'] = round(self.previous_seconds + time.monotonic()-self.started, 2)
        self.data['call_records'] = self.previous_calls + list(self.active_calls)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as out:
            os.chmod(temporary, 0o600)
            json.dump(self.data, out, ensure_ascii=False)
        os.replace(temporary, self.path)


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
    if profile() != 'b' or current() is not None:
        yield current()
        return
    rid = str(uuid.UUID(str(run_id))) if run_id else str(uuid.uuid4())
    path = Path(root)/(rid+'.lock') if root is not None and not dry else None
    with execution_lock(path):
        context = RunContext(run_id=rid, root=root, dry=dry)
        token = _current.set(context)
        try:
            from common.services.claude import call_tags, track_calls
            with call_tags(run_id=rid, profile='b'), track_calls(alert=False, filter={'run_id': rid}) as calls:
                context.active_calls = calls
                yield context
        finally:
            with context.lock:
                context.save()
            _current.reset(token)
