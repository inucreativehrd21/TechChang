"""로컬 전체 SQLite 스키마·행과 승인 미디어의 독립 복원 시험. 운영 MySQL 검증과 구분한다."""
import hashlib
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import skipUnless
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from .models import ColumnDraft, Meeting
from .test_lab_safety import certified
from .approval import approve


@skipUnless(connection.vendor == 'sqlite', '로컬 SQLite 전체 복원 검사예요. MySQL 복원 검증을 대신하지 않아요.')
class LabRestoreTests(TransactionTestCase):
    def test_entire_database_and_media_restore_without_touching_source(self):
        from .artifacts import atomic_write
        from .audit import verify
        owner = User.objects.create_superuser('restore-owner', '', 'x')
        Meeting.objects.create(week_start=timezone.localdate(), summary='restore fixture')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder, 'source')
            media = root / 'media'
            with override_settings(BASE_DIR=root, MEDIA_ROOT=media):
                atomic_write(media / 'columns/restore.png', b'approved image fixture')
                draft = certified(ColumnDraft.objects.create(topic='data', status='hold', subject='복원 원고',
                    content='복원 본문', chart_path='columns/restore.png', qa_report={'verdict': 'accept', 'score': 90}))
                approve(draft, owner)
                self.assertTrue(verify())
                target = Path(folder, 'restored.sqlite3')
                with closing(sqlite3.connect(target)) as backup:
                    connection.connection.backup(backup)
                restored_media = Path(folder, 'restored-files')
                shutil.copytree(root, restored_media)
                with closing(sqlite3.connect(target)) as restored:
                    tables = [name for (name,) in connection.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")]
                    self.assertEqual(sorted(tables), sorted(name for (name,) in restored.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")))
                    for name in tables:
                        quoted = '"'+name.replace('"', '""')+'"'
                        before = sorted(connection.connection.execute('SELECT * FROM '+quoted).fetchall(), key=repr)
                        after = sorted(restored.execute('SELECT * FROM '+quoted).fetchall(), key=repr)
                        normalize = lambda rows: [[int(v) if isinstance(v, bool) else v for v in row] for row in rows]
                        self.assertEqual(json.dumps(normalize(before), default=str), json.dumps(normalize(after), default=str), name)
                for source in root.rglob('*'):
                    if source.is_file():
                        restored_file = restored_media / source.relative_to(root)
                        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),
                                         hashlib.sha256(restored_file.read_bytes()).digest())
                self.assertTrue(verify())
                self.assertEqual(ColumnDraft.objects.get(pk=draft.pk).content, '복원 본문')
