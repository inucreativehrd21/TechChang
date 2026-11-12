"""읽기 전용 연구실 기준선 보고서. 모델·메일·공개 원고를 변경하지 않는다."""
import json
from datetime import timedelta
from pathlib import Path
from django.core.management.base import BaseCommand
from django.utils import timezone
from office.models import StageRun, HumanReview, JobRequest, AuditEvent
from office.lab_metrics import summarize, measured_sum


class Command(BaseCommand):
    help = '최근 StageRun의 첫 심사·재심·모델 사용량을 비공개 JSON으로 집계해요.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--output', required=True)

    def handle(self, *args, **opts):
        rows = list(StageRun.objects.filter(created_at__gte=timezone.now()-timedelta(days=opts['days'])).values(
            'run_id', 'seq', 'stage', 'output', 'calls', 'seconds', 'error', 'draft_id', 'draft__status'))
        report = summarize(rows)
        by_track = {}
        for track in ('research', 'practical', ''):
            run_ids = {r['run_id'] for r in report['runs'] if r['column_track'] == track}
            by_track[track or 'legacy'] = summarize([r for r in rows if str(r['run_id']) in run_ids])
        report['editorial_tracks'] = by_track
        report['generated_at'] = timezone.now().isoformat()
        report['days'] = opts['days']
        approved_ids = set(AuditEvent.objects.filter(action__in=['approved', 'exception_approved'],
                          created_at__gte=timezone.now()-timedelta(days=opts['days'])).values_list('draft_id', flat=True))
        draft_calls = {draft_id: [] for draft_id in approved_ids if draft_id is not None}
        # 기간 안에 승인된 원고의 전체 시도 비용을 포함한다. 앞선 실패가 기간 밖이라고 빠지면 안 된다.
        for row in StageRun.objects.filter(draft_id__in=draft_calls).values('draft_id', 'calls'):
            draft_calls[row['draft_id']].extend(row.get('calls') or [])
        report['approved_draft_usage'] = [{'draft_id': draft_id, 'recorded_calls': len(calls),
             'known_input_tokens': measured_sum(calls, 'input_tokens'),
             'unknown_usage_calls': sum(c.get('input_tokens') is None for c in calls),
             'has_call_measurements': bool(calls)}
             for draft_id, calls in draft_calls.items()]
        report['limitations'].append('승인 표본은 기간 안에 한 번이라도 승인된 원고예요. 이후 취소·수정 여부와 별도로 전체 기록된 시도 비용을 포함해요.')
        from statistics import median
        reviews = list(HumanReview.objects.filter(created_at__gte=timezone.now()-timedelta(days=opts['days'])))
        report['human_review'] = {'sample_size': len(reviews),
            'approved': sum(r.approved for r in reviews),
            'median_minutes': median(r.review_minutes for r in reviews) if reviews else None,
            'median_usefulness': median(r.usefulness for r in reviews) if reviews else None,
            'major_factual_errors': sum(sum(e.get('severity') == 'major' for e in r.factual_errors) for r in reviews),
            'corrections': sum(r.corrected_after_publish for r in reviews)}
        jobs = list(JobRequest.objects.filter(created_at__gte=timezone.now()-timedelta(days=opts['days'])))
        waits = [(j.started_at-j.created_at).total_seconds() for j in jobs if j.started_at]
        report['jobs'] = {'sample_size': len(jobs), 'median_wait_seconds': median(waits) if waits else None,
                          'max_wait_seconds': max(waits) if waits else None,
                          'states': {state: sum(j.status == state for j in jobs) for state, _ in JobRequest.ST_CHOICES}}
        path = Path(opts['output']).resolve()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        path.chmod(0o600)
        self.stdout.write(f"표본 {report['sample_size']}회 / 첫 심사 통과 {report['first_pass_count']}회 / {path}")
