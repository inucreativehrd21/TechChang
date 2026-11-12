"""끝난 체크포인트와 완료된 파일 응답만 보관 기간 뒤 정리한다."""
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.core.management.base import BaseCommand
from office.models import ColumnDraft
from office.run_context import execution_lock
import json


class Command(BaseCommand):
    help = '기본은 대상 확인만 해요. --apply를 붙여야 완료된 비공개 체크포인트를 지워요.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, choices=range(7, 366), default=30)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **opts):
        root = Path(settings.BASE_DIR, 'logs/lab-runs').absolute()
        if root.resolve() != root:
            raise ValueError('체크포인트 경로에 심볼릭 링크가 있어요. 정리하지 않아요.')
        cutoff = (timezone.now()-timedelta(days=opts['days'])).timestamp()
        for path in root.glob('*.json'):
            if path.is_symlink() or path.resolve().parent != root or path.stat().st_mtime >= cutoff:
                continue
            try:
                with execution_lock(path.with_suffix('.lock')):
                    data = json.loads(path.read_text(encoding='utf-8'))
                    draft_id = data.get('metadata', {}).get('draft_id')
                    if not ColumnDraft.objects.filter(pk=draft_id, status__in=['published', 'rejected']).exists():
                        continue  # 실패·보류 원고의 재개 자료는 자동 삭제하지 않는다.
                    self.stdout.write(f'{"삭제" if opts["apply"] else "대상"}: {path.name}')
                    if opts['apply']:
                        path.unlink()
            except (RuntimeError, ValueError, OSError):
                continue
