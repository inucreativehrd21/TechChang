"""승인 자산의 바이트 지문과 비공개 보관본. 모델에 파일 접근을 열지 않는다."""
import hashlib
import os
import re
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit
from django.conf import settings
from .execution import commit_guard

MAX_BYTES = 25 * 1024 * 1024


def safe_path(root, relative):
    root = Path(root).absolute()
    part = Path(relative)
    target = root / part
    if (root.resolve() != root or part.is_absolute() or '..' in part.parts
            or target.resolve().parent != target.absolute().parent
            or not target.resolve().is_relative_to(root) or target.is_symlink()):
        raise ValueError('산출물 경로가 허용된 저장 경계를 벗어났어요.')
    return target


def atomic_write(path, data, *, private=False):
    path = Path(path).absolute()
    with commit_guard():
        if path.resolve() != path:
            raise ValueError('산출물 경로에 심볼릭 링크를 사용할 수 없어요.')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o755)
        temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                                  0o600 if private else 0o644), 'wb') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def manifest(draft, *, strict=False):
    prefix = settings.MEDIA_URL
    paths = {draft.chart_path} if draft.chart_path else set()
    image_urls = re.findall(r'!\[[^\]]*\]\(([^\s)]+)', draft.content or '')
    image_urls += re.findall(r'<img\b[^>]*\bsrc=[\"\']([^\"\']+)', draft.content or '', re.I)
    for url in image_urls:
        if url.startswith(prefix):
            paths.add(unquote(urlsplit(url[len(prefix):]).path))
        else:
            if strict:
                raise ValueError('승인할 이미지는 관리되는 미디어 저장소에 보관해야 해요.')
            paths.add('external:'+url)
    if len(paths) > 20:
        raise ValueError('승인 산출물 파일 수가 상한을 넘었어요.')
    result = []
    for relative in sorted(paths):
        try:
            path = safe_path(settings.MEDIA_ROOT, relative)
            with path.open('rb') as file:
                data = file.read(MAX_BYTES+1)
            if len(data) > MAX_BYTES:
                raise ValueError('승인 파일 크기가 상한을 넘었어요.')
            result.append({'path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)})
        except (OSError, ValueError) as exc:
            if strict:
                raise ValueError('승인 산출물 파일이 없거나 읽을 수 없어요.') from exc
            result.append({'path': relative, 'unavailable': True})
    return result


def archive(entries):
    root = Path(settings.BASE_DIR, 'logs/private-lab/artifacts')
    for entry in entries:
        source = safe_path(settings.MEDIA_ROOT, entry['path'])
        with source.open('rb') as file:
            data = file.read(MAX_BYTES+1)
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('승인 중 산출물 파일이 바뀌었어요. 다시 확인해 주세요.')
        target = safe_path(root, entry['sha256'])
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('보관된 승인 파일이 손상됐어요.')
        else:
            atomic_write(target, data, private=True)


def verify_archive(entries):
    root = Path(settings.BASE_DIR, 'logs/private-lab/artifacts')
    for entry in entries:
        try:
            path = safe_path(root, entry['sha256'])
            with path.open('rb') as file:
                data = file.read(MAX_BYTES+1)
            if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                return False
        except (OSError, ValueError, KeyError):
            return False
    return True


def store_chart(data):
    relative = 'columns/'+hashlib.sha256(data).hexdigest()+'.png'
    target = safe_path(settings.MEDIA_ROOT, relative)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError('동일 지문의 이미지 파일이 손상됐어요.')
    else:
        atomic_write(target, data)
    return relative
