"""
SQLite/MySQL DB 자동 백업 명령어

사용법:
  python manage.py backup_db                          # 기본 (최근 7개 보관)
  python manage.py backup_db --keep 4                 # 최근 4개 보관
  python manage.py backup_db --dest /backups          # 저장 경로 지정
  python manage.py backup_db --email admin@example.com  # 백업 파일 이메일 전송

cron 예시:
  0 3 * * *   ... backup_db --keep 7          # 매일 로컬 백업
  0 3 * * 1   ... backup_db --keep 4 --email admin@example.com  # 주간 + 이메일
"""
import gzip
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'DB를 타임스탬프 파일로 백업하고 오래된 백업을 삭제합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep', type=int, default=7,
            help='보관할 백업 수 (기본: 7개)'
        )
        parser.add_argument(
            '--dest', type=str, default='',
            help='백업 저장 디렉토리 (기본: 프로젝트 루트/backups/)'
        )
        parser.add_argument(
            '--email', type=str, default='',
            help='백업 파일을 이메일로 전송할 주소'
        )

    def handle(self, *args, **options):
        keep = options['keep']
        email_to = options['email']

        # 백업 디렉토리
        backup_dir = Path(options['dest']) if options['dest'] else Path(settings.BASE_DIR) / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        db_config = settings.DATABASES['default']
        engine = db_config['ENGINE']

        if 'mysql' in engine:
            backup_file, pattern = self._backup_mysql(db_config, backup_dir, timestamp)
        else:
            backup_file, pattern = self._backup_sqlite(db_config, backup_dir, timestamp)

        if backup_file is None:
            return

        size_kb = backup_file.stat().st_size // 1024
        self.stdout.write(
            self.style.SUCCESS(
                f'[{datetime.now():%Y-%m-%d %H:%M}] 백업 완료: {backup_file.name} ({size_kb} KB)'
            )
        )

        # 오래된 백업 삭제
        backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = 0
        for old in backups[keep:]:
            old.unlink()
            removed += 1

        if removed:
            self.stdout.write(f'오래된 백업 {removed}개 삭제 (최근 {keep}개 보관)')

        self.stdout.write(f'현재 백업 수: {min(len(backups), keep)}개 → {backup_dir}')

        # 이메일 전송
        if email_to:
            self._send_email(email_to, backup_file, size_kb)

    def _backup_mysql(self, db_config, backup_dir, timestamp):
        """mysqldump로 MySQL 백업 (gzip 압축)"""
        backup_file = backup_dir / f'db_{timestamp}.sql.gz'
        name = db_config.get('NAME', '')
        user = db_config.get('USER', '')
        password = db_config.get('PASSWORD', '')
        host = db_config.get('HOST', '127.0.0.1')
        port = str(db_config.get('PORT', '3306'))

        dump_cmd = [
            'mysqldump',
            f'-u{user}',
            f'-p{password}',
            f'-h{host}',
            f'--port={port}',
            '--single-transaction',
            '--routines',
            '--triggers',
            name,
        ]

        try:
            result = subprocess.run(dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode != 0:
                self.stderr.write(self.style.ERROR(f'mysqldump 오류: {result.stderr.decode()}'))
                return None, None

            with gzip.open(backup_file, 'wb') as f_out:
                f_out.write(result.stdout)

            return backup_file, 'db_*.sql.gz'
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'MySQL 백업 실패: {e}'))
            return None, None

    def _backup_sqlite(self, db_config, backup_dir, timestamp):
        """SQLite 파일 복사"""
        db_path = db_config.get('NAME', '')
        if not db_path or not Path(db_path).exists():
            self.stderr.write(self.style.ERROR(f'DB 파일을 찾을 수 없습니다: {db_path}'))
            return None, None

        backup_file = backup_dir / f'db_{timestamp}.sqlite3'
        shutil.copy2(db_path, backup_file)
        return backup_file, 'db_*.sqlite3'

    def _send_email(self, email_to, backup_file, size_kb):
        """백업 파일을 이메일로 전송"""
        now = datetime.now()
        subject = f'[TechChang] DB 주간 백업 - {now:%Y-%m-%d}'
        body = (
            f'TechChang DB 주간 백업 파일을 첨부합니다.\n\n'
            f'- 날짜: {now:%Y-%m-%d %H:%M}\n'
            f'- 파일: {backup_file.name}\n'
            f'- 크기: {size_kb} KB\n\n'
            f'이 메일은 자동으로 발송되었습니다.'
        )
        try:
            msg = EmailMessage(
                subject=subject,
                body=body,
                to=[email_to],
            )
            msg.attach_file(str(backup_file))
            msg.send()
            self.stdout.write(self.style.SUCCESS(f'이메일 전송 완료 → {email_to}'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'이메일 전송 실패: {e}'))
