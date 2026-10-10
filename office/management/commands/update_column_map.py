"""칼럼 지도 갱신 — 요약이 없거나 본문이 바뀐 연구팀 칼럼의 소주제·키워드·요약을 다시 만든다(office.digest).

    python manage.py update_column_map                  # 비었거나 낡은 항목 모두
    python manage.py update_column_map --question 114   # 한 편만
    python manage.py update_column_map --import sum.json  # 미리 만든 요약 들여오기(모델 호출 없음)
    python manage.py update_column_map --dry-run        # 갱신할 글만 보여 주기

칼럼이 저장되면 office.signals 가 --settle 15 로 띄운다. 한 번 발행에 저장이 여러 번 일어나도
잠깐 기다렸다가 한꺼번에 처리하고, 이미 돌고 있으면 새로 띄운 쪽은 그냥 끝낸다(잠금 파일).
"""
import json
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from office import digest

LOCK = 'column_map.lock'
LOCK_STALE = 30 * 60      # 이보다 오래된 잠금은 죽은 프로세스가 남긴 것으로 본다


class Command(BaseCommand):
    help = '칼럼 지도(소주제·키워드·요약)를 갱신합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--question', type=int)
        parser.add_argument('--import', dest='import_file', default='')
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--settle', type=int, default=0, help='시작 전 기다릴 초(연속 저장을 모은다)')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        out = self.stdout.write
        if opts['import_file']:
            with open(opts['import_file'], encoding='utf-8') as f:
                rows = json.load(f)
            out(self.style.SUCCESS(f"들여옴 {digest.import_items(rows)}편 (입력 {len(rows)}편)"))
            return
        if opts['dry_run']:
            todo = digest.pending(opts['question'])
            out(f'갱신할 글 {len(todo)}편')
            for q in todo:
                out(f'  #{q.pk} {q.subject[:50]}')
            return

        lock = os.path.join(settings.BASE_DIR, 'logs', LOCK)
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        if os.path.exists(lock) and time.time() - os.path.getmtime(lock) > LOCK_STALE:
            os.remove(lock)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            out('이미 갱신 중입니다 — 끝냅니다.')
            return
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            if opts['settle']:
                time.sleep(opts['settle'])
            res = digest.refresh(only_id=opts['question'], limit=opts['limit'], out=out)
            out(self.style.SUCCESS(f"칼럼 지도 갱신 {res['done']}편"
                                   + (f", 실패 {len(res['failed'])}편 {res['failed']}" if res['failed'] else '')
                                   + (f", 남음 {res['left']}편" if res['left'] else '')))
        finally:
            try:
                os.remove(lock)
            except OSError:
                pass
