import os
from django.core.management.base import BaseCommand
from django.core.management import call_command
from office.models import JobRequest
from office.security import validate_args
from office.execution import assert_current


class Command(BaseCommand):
    help = '실행기가 발급한 작업 실행 번호로만 내부 명령을 수행해요.'

    def add_arguments(self, parser):
        parser.add_argument('--job', required=True, type=int)
        parser.add_argument('--execution', required=True)

    def handle(self, *args, **opts):
        os.environ.update(LAB_JOB_ID=str(opts['job']), LAB_EXECUTION_ID=opts['execution'],
                          CLAUDE_BACKEND='cli', CLAUDE_CLI_FALLBACK='false',
                          AI_ALLOW_PAID_API='false', OFFICE_CODE_RUN='0')
        assert_current()
        job = JobRequest.objects.get(pk=opts['job'])
        argv = validate_args(job.args)
        call_command(argv[0], *argv[1:])
        assert_current()
