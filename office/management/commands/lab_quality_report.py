"""읽기 전용 연구실 기준선 보고서. 모델·메일·공개 원고를 변경하지 않는다."""
import json
from datetime import timedelta
from pathlib import Path
from django.core.management.base import BaseCommand
from django.utils import timezone
from office.models import StageRun
from office.lab_metrics import summarize


class Command(BaseCommand):
    help = '최근 StageRun의 첫 심사·재심·모델 사용량을 비공개 JSON으로 집계해요.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--output', required=True)

    def handle(self, *args, **opts):
        rows = StageRun.objects.filter(created_at__gte=timezone.now()-timedelta(days=opts['days'])).values(
            'run_id', 'seq', 'stage', 'output', 'calls', 'seconds')
        report = summarize(rows)
        report['generated_at'] = timezone.now().isoformat()
        report['days'] = opts['days']
        path = Path(opts['output']).resolve()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        path.chmod(0o600)
        self.stdout.write(f"표본 {report['sample_size']}회 / 첫 심사 통과 {report['first_pass_count']}회 / {path}")
