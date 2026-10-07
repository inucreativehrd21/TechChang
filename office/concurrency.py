"""연구실 단계의 동시 실행 도우미.

같은 원고를 독립적으로 읽는 단계(검증·평론·차트 등)를 동시에 돌린다. 원칙:
- 결과는 끝난 순서와 무관하게 **넘긴 순서대로** 돌려준다 (기록·로그 순서가 매번 같게).
- 한 작업이 실패해도 나머지는 계속한다. 실패를 어떻게 다룰지는 호출부가 정한다.
- 각 작업은 호출 시점의 ContextVar(호출 꼬리표 등)를 그대로 물려받는다.
  ThreadPoolExecutor 는 ContextVar 를 워커로 옮겨 주지 않으므로 copy_context() 로 감싼다.
- 다음 경우에는 그냥 순서대로 돈다:
  OFFICE_PARALLEL=0 / spool 모드(로컬 세션이 한 번에 하나씩 답하는 게 기본) 이면서
  OFFICE_SPOOL_PARALLEL=1 이 아님 / 작업이 하나뿐.
워커는 DB 에 쓰지 않는다 — 결과만 돌려주고, 기록은 메인 스레드가 한다 (SQLite 잠금·연결 누수 방지).
"""
from __future__ import annotations

import contextvars
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Outcome:
    key: str
    ok: bool
    value: Any = None
    error: str = ''
    seconds: float = 0.0


def parallel_enabled() -> bool:
    if os.environ.get('OFFICE_PARALLEL', '1') == '0':
        return False
    if os.environ.get('OFFICE_AGENT_SPOOL') and os.environ.get('OFFICE_SPOOL_PARALLEL') != '1':
        return False
    return True


def max_workers() -> int:
    try:
        return max(1, int(os.environ.get('OFFICE_MAX_WORKERS', '3')))
    except ValueError:
        return 3


def _run(key: str, fn: Callable[[], Any]) -> Outcome:
    started = time.monotonic()
    try:
        value = fn()
        return Outcome(key, True, value, '', round(time.monotonic() - started, 1))
    except Exception as ex:  # noqa: BLE001 — 실패는 결과로 돌려준다
        return Outcome(key, False, None, f'{type(ex).__name__}: {ex}'[:300], round(time.monotonic() - started, 1))


def fan_out(tasks: dict[str, Callable[[], Any]], *, workers: int | None = None) -> dict[str, Outcome]:
    """tasks 를 (가능하면) 동시에 실행하고 {key: Outcome} 을 tasks 의 순서대로 돌려준다."""
    if not tasks:
        return {}
    if len(tasks) == 1 or not parallel_enabled():
        return {k: _run(k, fn) for k, fn in tasks.items()}

    n = min(workers or max_workers(), len(tasks))
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix='office') as pool:
        futures = {k: pool.submit(contextvars.copy_context().run, _run, k, fn) for k, fn in tasks.items()}
        return {k: futures[k].result() for k in tasks}
