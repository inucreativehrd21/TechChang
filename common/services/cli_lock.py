"""CLI 인증 저장소를 공유하는 프로세스 사이의 유한 대기 잠금."""
from contextlib import contextmanager
import os
from pathlib import Path
import time

from .cli_errors import ProviderUnavailable


@contextmanager
def codex_lock(timeout=1200):
    root = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex-techchang')))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / 'techchang.lock'
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise ProviderUnavailable('Codex 실행 잠금 대기 시간이 초과됐어요.', provider='codex', kind='busy')
                time.sleep(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
