"""Git HEAD가 같아도 실제 소스가 다르면 실행 버전을 구별한다."""
from functools import lru_cache
import hashlib
from pathlib import Path


def fingerprint_now():
    root = Path(__file__).resolve().parent.parent
    files = []
    for folder in ('office', 'common', 'community', 'config'):
        files.extend((root / folder).rglob('*.py'))
    files.extend((root / 'templates/office').rglob('*.html'))
    files.append(root / 'static/css/admin-office.css')
    files.extend((root / 'static/js').glob('lab-*.js'))
    files.extend(root.glob('requirements*.txt'))
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


@lru_cache(maxsize=1)
def code_fingerprint():
    return fingerprint_now()
