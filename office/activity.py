"""비공개 실시간 호출 상태. 프롬프트·추론은 저장하지 않고 관측 실패는 제작에 전파하지 않아요."""
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import time
import uuid

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def root():
    return Path(getattr(settings, 'LAB_ACTIVITY_ROOT', Path(settings.BASE_DIR)/'logs/private-lab/activity'))


def _save(context):
    from .artifacts import atomic_write
    payload = {'run_id': context.run_id, 'metadata': context.data['metadata'],
               'updated_at': timezone.now().isoformat(), 'budget': context.budget(),
               'calls': [{**c, 'result': str(c.get('result') or '')[:240]} for c in context.activity_calls[-120:]]}
    try:
        atomic_write(root()/(context.run_id+'.json'), json.dumps(payload, ensure_ascii=False).encode(), private=True)
    except Exception:  # 관측 실패가 실제 집필·검증을 중단하지 않아요.
        logger.warning('실시간 연구실 상태 저장 실패', exc_info=True)


@contextmanager
def observe(agent, stage, model):
    from .run_context import current
    context = current()
    if context is None or context.path is None:
        yield {}
        return
    now = timezone.now()
    row = {'id': uuid.uuid4().hex, 'agent': agent, 'stage': stage, 'model': model,
           'state': 'running', 'started_at': now.isoformat(), 'ended_at': None, 'result': ''}
    with context.lock:
        if not hasattr(context, 'activity_calls'):
            context.activity_calls = []
        context.activity_calls.append(row)
        _save(context)
    try:
        yield row
    except BaseException:
        row['state'] = 'failed'
        row['result'] = '호출이 완료되지 않았어요. 작업 결과와 감사 기록을 확인해 주세요.'
        raise
    else:
        row['state'] = 'done'
    finally:
        with context.lock:
            row['ended_at'] = timezone.now().isoformat()
            text = str(row.get('result') or '')
            row['result'] = text[:16000]+('\n\n(긴 응답은 앞 16,000자까지 표시해요.)' if len(text) > 16000 else '')
            try:
                from .artifacts import atomic_write
                atomic_write(root()/context.run_id/(row['id']+'.txt'), row['result'].encode('utf-8'), private=True)
            except Exception:
                logger.warning('실시간 연구실 응답 저장 실패', exc_info=True)
            _save(context)


def recent():
    """최근 7일의 관측 파일만 읽어요. 원고 전문 체크포인트는 읽지 않아요."""
    base = root()
    if not base.is_dir():
        return []
    paths = []
    for path in base.glob('*.json'):
        try:
            uuid.UUID(path.stem)
            if not path.is_symlink() and time.time()-path.stat().st_mtime <= 7*86400:
                paths.append(path)
        except (ValueError, OSError):
            continue
    results = []
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(payload, dict) and payload.get('run_id') == path.stem:
                results.append(payload)
        except (OSError, ValueError):
            continue
    return results
