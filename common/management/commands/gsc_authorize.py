"""
Google Search Console OAuth 2.0 토큰 1회 발급 헬퍼

브라우저가 있는 로컬 PC에서 한 번만 실행해 token.json(refresh token 포함)을 만든다.
이후 그 파일을 서버로 복사하고 .env에 GSC_OAUTH_TOKEN 경로를 지정하면
send_visitor_report 의 cron이 무인으로 토큰을 자동 갱신하며 동작한다.

사전 준비:
  1. GCP Console → API 및 서비스 → 사용자 인증 정보 →
     'OAuth 2.0 클라이언트 ID' 생성 (애플리케이션 유형: 데스크톱 앱)
  2. 발급된 client_secret_*.json 다운로드
  3. 동의 화면(OAuth consent) 게시 상태를 '프로덕션'으로 전환
     (※ '테스트' 상태면 refresh token이 7일 후 만료되어 cron이 끊긴다)
  4. 동의에 사용하는 구글 계정이 Search Console 속성 권한을 가지고 있어야 함

사용법 (로컬):
  pip install google-auth-oauthlib
  python manage.py gsc_authorize --client-secret client_secret_xxx.json --out token.json
  → 브라우저 동의 후 token.json 생성 → 서버로 복사 → .env: GSC_OAUTH_TOKEN=/경로/token.json
"""
import os

from django.core.management.base import BaseCommand, CommandError

SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']


class Command(BaseCommand):
    help = 'GSC OAuth 2.0 토큰(token.json)을 1회 발급합니다. (로컬에서 실행)'

    def add_arguments(self, parser):
        parser.add_argument('--client-secret', required=True,
                            help='GCP에서 받은 OAuth 클라이언트 secret JSON 경로')
        parser.add_argument('--out', default='token.json',
                            help='생성할 토큰 파일 경로 (기본: token.json)')
        parser.add_argument('--no-browser', action='store_true',
                            help='브라우저 자동 실행 대신 콘솔에 URL 출력 (원격 SSH 등)')

    def handle(self, *args, **options):
        client_secret = options['client_secret']
        out = options['out']
        if not os.path.exists(client_secret):
            raise CommandError(f'클라이언트 secret 파일이 없습니다: {client_secret}')

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            raise CommandError(
                'google-auth-oauthlib 가 필요합니다. 설치: pip install google-auth-oauthlib'
            )

        flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
        if options['no_browser']:
            creds = flow.run_console()
        else:
            creds = flow.run_local_server(port=0)

        with open(out, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())

        self.stdout.write(self.style.SUCCESS(f'토큰 발급 완료 → {out}'))
        self.stdout.write('이 파일을 서버로 복사하고 .env에 다음을 추가하세요:')
        self.stdout.write(f'  GSC_OAUTH_TOKEN={os.path.abspath(out)}')
