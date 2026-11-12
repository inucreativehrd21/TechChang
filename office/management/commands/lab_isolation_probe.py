"""외부 요청이 비공개 경로를 읽을 수 없는지 본문을 받지 않고 확인한다."""
from urllib.parse import urljoin, urlparse
import requests
from django.core.management.base import BaseCommand, CommandError

PATHS = ['/.env', '/.git/config', '/logs/office_jobs.log', '/logs/lab-runs/',
         '/logs/private-lab/', '/backups/', '/scratchpad/', '/lab/admin/activity.json']


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--base-url', required=True)

    def handle(self, *args, **opts):
        base = opts['base_url'].rstrip('/')
        parsed = urlparse(base)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise CommandError('http/https 사이트 주소를 입력해 주세요.')
        failed = []
        for path in PATHS:
            for method in ('HEAD', 'GET'):
                with requests.request(method, base+path, allow_redirects=False, timeout=10, stream=True,
                                      headers={'User-Agent': 'Mozilla/5.0 LabIsolationCheck'}) as response:
                    location = urlparse(urljoin(base, response.headers.get('Location', '')))
                    denied = response.status_code in (403, 404, 410)
                    login = (response.status_code in (301, 302, 303) and location.netloc == parsed.netloc
                             and 'login' in location.path)
                    self.stdout.write(f'{method} {response.status_code} {path}')
                    if not denied and not login:
                        failed.append(method+' '+path)
        if failed:
            raise CommandError('차단을 확인하지 못한 경로: '+', '.join(failed))
