"""연구실 위클리 한 호 만들기(office.newsletter). cron: 매주 금요일 10:00.

    python manage.py make_newsletter                 # 오늘 기준(지난 금~어제)으로 만들어 공개
    python manage.py make_newsletter --date 2026-10-16
    python manage.py make_newsletter --dry-run       # 저장하지 않고 카드만 media/newsletter/_dry/ 에
    python manage.py make_newsletter --no-model      # 큐레이터 호출 없이 사실로 만든 기본 문구
"""
from datetime import date
from contextlib import nullcontext
import json

from django.core.management.base import BaseCommand

from office import newsletter


class Command(BaseCommand):
    help = '연구실 위클리(카드뉴스·웹 페이지)를 만듭니다.'

    def add_arguments(self, parser):
        parser.add_argument('--date', default='', help='실행일로 볼 날짜(YYYY-MM-DD)')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--no-model', action='store_true')
        parser.add_argument('--copy-file', default='', help='검토한 위클리 문구 JSON 파일')

    def handle(self, *args, **opts):
        run_date = date.fromisoformat(opts['date']) if opts['date'] else None
        with open(opts['copy_file'], encoding='utf-8') if opts['copy_file'] else nullcontext() as f:
            copy = json.load(f) if opts['copy_file'] else None
        res = newsletter.make(run_date, dry=opts['dry_run'], use_model=not opts['no_model'],
                              copy_override=copy, out=self.stdout.write)
        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('[dry-run] ' + ' '.join(res['cards'])))
        else:
            self.stdout.write(self.style.SUCCESS(f'발행: No.{res.issue_no} {res.title} → /newsletter/{res.slug}/'))
