from django.core.management.base import BaseCommand, CommandError
from office.models import JobRequest
from office.job_control import cancel, restart


class Command(BaseCommand):
    help = '작업 상태를 확인하거나 명시적으로 취소·다시 실행해요.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['status', 'cancel', 'restart', 'resume'])
        parser.add_argument('--job', type=int, required=True)

    def handle(self, *args, **opts):
        try:
            if opts['action'] == 'cancel':
                cancel(opts['job'])
            elif opts['action'] in ('restart', 'resume'):
                self.stdout.write(f'새 작업: {restart(opts["job"], resume=opts["action"] == "resume").pk}')
            job = JobRequest.objects.get(pk=opts['job'])
            self.stdout.write(f'#{job.pk} {job.get_status_display()} · 원고 {job.business_result or "미연결"} · {job.note}')
        except (ValueError, JobRequest.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
