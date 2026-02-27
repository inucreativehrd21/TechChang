"""
SQLite DB 자동 백업 명령어

사용법:
  python manage.py backup_db                 # 기본 (최근 7개 보관)
  python manage.py backup_db --keep 14       # 최근 14개 보관
  python manage.py backup_db --dest /backups # 저장 경로 지정

cron 예시:
  0 3 * * * cd /home/ubuntu/mysite && venv/bin/python manage.py backup_db
"""
import os
import shutil
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'SQLite DB를 타임스탬프 파일로 백업하고 오래된 백업을 삭제합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep', type=int, default=7,
            help='보관할 백업 수 (기본: 7개)'
        )
        parser.add_argument(
            '--dest', type=str, default='',
            help='백업 저장 디렉토리 (기본: 프로젝트 루트/backups/)'
        )

    def handle(self, *args, **options):
        keep = options['keep']

        db_path = settings.DATABASES['default'].get('NAME', '')
        if not db_path or not Path(db_path).exists():
            self.stderr.write(self.style.ERROR(f'DB 파일을 찾을 수 없습니다: {db_path}'))
            return

        db_path = Path(db_path)

        # 백업 디렉토리
        if options['dest']:
            backup_dir = Path(options['dest'])
        else:
            backup_dir = Path(settings.BASE_DIR) / 'backups'

        backup_dir.mkdir(parents=True, exist_ok=True)

        # 타임스탬프 파일명
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_dir / f'db_{timestamp}.sqlite3'

        # 복사
        shutil.copy2(db_path, backup_file)
        size_kb = backup_file.stat().st_size // 1024
        self.stdout.write(
            self.style.SUCCESS(f'[{datetime.now():%Y-%m-%d %H:%M}] 백업 완료: {backup_file.name} ({size_kb} KB)')
        )

        # 오래된 백업 삭제
        backups = sorted(backup_dir.glob('db_*.sqlite3'), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = 0
        for old in backups[keep:]:
            old.unlink()
            removed += 1

        if removed:
            self.stdout.write(f'오래된 백업 {removed}개 삭제 (최근 {keep}개 보관)')

        self.stdout.write(f'현재 백업 수: {min(len(backups), keep)}개 → {backup_dir}')
