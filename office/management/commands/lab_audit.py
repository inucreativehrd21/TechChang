"""감사 기록 검증·비공개 내보내기·격리된 SQLite 복원 시험."""
import json
import sqlite3
import tempfile
import base64
import hashlib
from contextlib import closing
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.dateparse import parse_datetime
from office.models import AuditEvent
from office.audit import verify, event_digest
from django.db import transaction
from office.models import AuditHead


class Command(BaseCommand):
    help = '감사 해시 체인을 검증하고 선택적으로 비공개 백업과 복원 시험을 해요.'

    def add_arguments(self, parser):
        parser.add_argument('--export', action='store_true')
        parser.add_argument('--restore-check', action='store_true')

    def handle(self, *args, **opts):
        with transaction.atomic():
            AuditHead.objects.select_for_update().filter(pk=1).first()
            if not verify():
                raise CommandError('감사 기록 해시 체인이 일치하지 않아요.')
            rows = list(AuditEvent.objects.values())
        assets = {}
        for row in rows:
            for asset in row['payload'].get('snapshot', {}).get('assets', []):
                sha = asset.get('sha256')
                if not sha or sha in assets:
                    continue
                from office.artifacts import safe_path
                try:
                    raw = safe_path(Path(settings.BASE_DIR, 'logs/private-lab/artifacts'), sha).read_bytes()
                except (OSError, ValueError) as exc:
                    raise CommandError('승인 자산 보관본이 누락됐어요.') from exc
                if hashlib.sha256(raw).hexdigest() != sha or len(raw) != asset['size']:
                    raise CommandError('승인 자산 보관본이 손상됐어요.')
                assets[sha] = base64.b64encode(raw).decode('ascii')
        bundle = {'count': len(rows), 'head': rows[-1]['digest'] if rows else '', 'events': rows, 'assets': assets}
        data = json.dumps(bundle, default=str, ensure_ascii=False)
        if opts['export']:
            root = Path(settings.BASE_DIR, 'logs/private-lab')
            if root.resolve() != root.absolute():
                raise CommandError('비공개 백업 경로에는 심볼릭 링크를 사용할 수 없어요.')
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            import os
            import uuid
            path = root / f'audit-{uuid.uuid4()}.json'
            with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf-8') as file:
                file.write(data)
            self.stdout.write(str(path))
        if opts['restore_check']:
            # 운영 DB에는 쓰지 않는다. 실제 별도 파일 DB에 복원한 뒤 다시 읽고 검증한다.
            with tempfile.TemporaryDirectory(prefix='lab-restore-') as directory:
                for sha, encoded in json.loads(data)['assets'].items():
                    restored_asset = Path(directory, sha)
                    restored_asset.write_bytes(base64.b64decode(encoded, validate=True))
                    if hashlib.sha256(restored_asset.read_bytes()).hexdigest() != sha:
                        raise CommandError('복원한 승인 파일 지문이 다릅니다.')
                with closing(sqlite3.connect(str(Path(directory, 'audit.sqlite3')))) as db:
                    db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
                    exported = json.loads(data)
                    db.executemany('INSERT INTO events VALUES (?, ?)', [(r['sequence'], json.dumps(r)) for r in exported['events']])
                    db.commit()
                    restored = [json.loads(row[0]) for row in db.execute('SELECT payload FROM events ORDER BY seq')]
                previous = ''
                for raw in restored:
                    raw['created_at'] = parse_datetime(raw['created_at'])
                    event = AuditEvent(**raw)
                    if event.previous_digest != previous or event.digest != event_digest(event):
                        raise CommandError('복원한 감사 기록이 원본과 다릅니다.')
                    previous = event.digest
                if len(restored) != exported['count'] or previous != exported['head']:
                    raise CommandError('복원한 감사 기록의 개수 또는 마지막 해시가 다릅니다.')
        self.stdout.write(f'감사 기록 {len(rows)}건 검증 완료')
