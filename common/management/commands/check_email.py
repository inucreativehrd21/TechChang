"""
이메일 인증 모듈 진단 커맨드

발송 없이 설정·SMTP 인증·인코딩·인증 모델 흐름을 단계별로 점검한다.
실제 메일 발송은 --to 를 줄 때만 수행한다(회원가입 인증과 동일한 경로).

사용법 (서버):
    # venv 활성화 후
    python manage.py check_email                 # 발송 없이 진단만
    python manage.py check_email --to me@x.com    # 실제 인증 메일 1통 발송 테스트
    python manage.py check_email --to me@x.com --settings config.settings.prod
"""
from django.core.management.base import BaseCommand
from django.conf import settings


OK = "\033[92mOK\033[0m"
FAIL = "\033[91mFAIL\033[0m"


class Command(BaseCommand):
    help = '이메일 인증 모듈(설정·SMTP·인코딩·인증 모델)을 단계별로 진단합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to', dest='to', default=None,
            help='실제 인증 메일을 발송해 볼 수신 주소 (미지정 시 발송 안 함)',
        )

    def _line(self, label, value):
        self.stdout.write(f"  {label:<16}: {value}")

    def handle(self, *args, **options):
        w = self.stdout.write
        w("")
        w("=" * 60)
        w(" 이메일 인증 모듈 진단")
        w("=" * 60)

        # 1) 설정값 --------------------------------------------------------
        w("\n[1] 이메일 설정")
        pw = settings.EMAIL_HOST_PASSWORD or ''
        self._line("SETTINGS", getattr(settings, 'SETTINGS_MODULE', '?'))
        self._line("DEBUG", settings.DEBUG)
        self._line("BACKEND", settings.EMAIL_BACKEND)
        self._line("HOST", f"{settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        self._line("TLS / SSL", f"{settings.EMAIL_USE_TLS} / {settings.EMAIL_USE_SSL}")
        self._line("HOST_USER", repr(settings.EMAIL_HOST_USER))
        self._line("PASSWORD", f"길이 {len(pw)} {'(설정됨)' if pw else '(비어있음!)'}")
        self._line("FROM", repr(settings.DEFAULT_FROM_EMAIL))
        self._line("TIMEOUT", getattr(settings, 'EMAIL_TIMEOUT', None))

        problems = []
        if not settings.EMAIL_HOST_USER:
            problems.append("EMAIL_HOST_USER 가 비어 있습니다 (.env 의 DJANGO_EMAIL_HOST_USER 확인).")
        if not pw:
            problems.append("EMAIL_HOST_PASSWORD 가 비어 있습니다 (.env 의 DJANGO_EMAIL_HOST_PASSWORD 확인).")
        if 'console' in settings.EMAIL_BACKEND or 'dummy' in settings.EMAIL_BACKEND:
            problems.append(f"EMAIL_BACKEND 가 실제 발송용이 아닙니다: {settings.EMAIL_BACKEND}")
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            problems.append("EMAIL_USE_TLS 와 EMAIL_USE_SSL 이 동시에 True 입니다.")

        # 2) From/Subject 인코딩 (한글 표시명 RFC2047) ---------------------
        w("\n[2] 헤더 인코딩 (한글 표시명)")
        try:
            from django.core.mail import EmailMessage
            m = EmailMessage('[테크창] 이메일 인증 코드', 'body',
                             settings.DEFAULT_FROM_EMAIL, ['dest@example.com'])
            msg = m.message()
            self._line("From", msg['From'])
            self._line("Subject", msg['Subject'])
            w(f"  => {OK} 헤더 생성 성공")
        except Exception as e:
            w(f"  => {FAIL} {type(e).__name__}: {e}")
            problems.append(f"헤더 인코딩 실패: {e}")

        # 3) SMTP 접속·인증 (메일 발송은 안 함) ---------------------------
        w("\n[3] SMTP 접속·인증")
        if 'smtp' in settings.EMAIL_BACKEND:
            from django.core.mail import get_connection
            conn = get_connection()
            try:
                conn.open()
                w(f"  => {OK} SMTP 접속·로그인 성공 (자격증명 유효)")
                conn.close()
            except Exception as e:
                w(f"  => {FAIL} {type(e).__name__}: {e}")
                problems.append(f"SMTP 인증 실패: {type(e).__name__}: {e}")
                self._hint_smtp(e)
        else:
            w("  (SMTP 백엔드가 아니라 건너뜀)")

        # 4) EmailVerification 모델 흐름 (DB) -----------------------------
        w("\n[4] 인증 모델 흐름 (코드 생성 → 검증)")
        try:
            from common.models import EmailVerification
            import secrets
            probe = '__diagnostic__@techchang.test'
            EmailVerification.objects.filter(email=probe).delete()
            code = EmailVerification.generate_code()
            v = EmailVerification.objects.create(email=probe, code=code)
            checks = [
                ("코드 길이", len(code) == EmailVerification.CODE_LENGTH),
                ("만료 아님", not v.is_expired()),
                ("재시도 가능", v.can_retry()),
                ("코드 일치", secrets.compare_digest(v.code, code)),
            ]
            for label, ok in checks:
                w(f"  {label:<12}: {OK if ok else FAIL}")
            v.mark_verified()
            w(f"  인증 완료 저장 : {OK if v.is_verified else FAIL}")
            v.delete()
            if not all(ok for _, ok in checks):
                problems.append("EmailVerification 모델 동작 이상")
        except Exception as e:
            w(f"  => {FAIL} {type(e).__name__}: {e}")
            problems.append(f"인증 모델 오류: {e}")

        # 5) 실제 발송 (opt-in) -------------------------------------------
        to = options['to']
        if to:
            w(f"\n[5] 실제 인증 메일 발송 → {to}")
            try:
                from django.core.mail import send_mail
                code = __import__('common.models', fromlist=['EmailVerification']).EmailVerification.generate_code()
                body = (
                    "안녕하세요! 테크창 이메일 인증 모듈 점검 메일입니다.\n\n"
                    f"테스트 인증코드: {code}\n\n"
                    "이 메일이 정상 수신되면 발송 경로가 정상입니다."
                )
                n = send_mail('[테크창] 이메일 인증 모듈 점검', body,
                              settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
                w(f"  => {OK if n == 1 else FAIL} send_mail 반환 {n} - 수신함(스팸함 포함) 확인")
            except Exception as e:
                w(f"  => {FAIL} {type(e).__name__}: {e}")
                problems.append(f"실제 발송 실패: {type(e).__name__}: {e}")
                self._hint_smtp(e)
        else:
            w("\n[5] 실제 발송 생략 (테스트하려면 --to 주소 지정)")

        # 요약 ------------------------------------------------------------
        w("\n" + "=" * 60)
        if problems:
            w(f" 진단 결과: 문제 {len(problems)}건 발견")
            for i, p in enumerate(problems, 1):
                w(f"   {i}. {p}")
        else:
            w(" 진단 결과: 이상 없음 - 모듈/설정/자격증명 모두 정상")
            w(" 사용자가 여전히 못 받으면 수신측 스팸함 / Gmail 발송 한도를 확인하세요.")
        w("=" * 60 + "\n")

    def _hint_smtp(self, exc):
        """SMTP 예외 유형별 원인 힌트"""
        name = type(exc).__name__
        text = str(exc)
        hints = []
        if 'Authentication' in name or '535' in text or 'Username and Password' in text:
            hints.append("Gmail 앱 비밀번호가 만료/취소됨 → 새 앱 비밀번호 발급 후 서버 .env 갱신.")
            hints.append("2단계 인증이 켜져 있어야 앱 비밀번호를 쓸 수 있습니다.")
        if 'timed out' in text.lower() or 'timeout' in name.lower():
            hints.append("서버에서 smtp.gmail.com:587 아웃바운드가 방화벽/보안그룹에 막혔을 수 있습니다.")
        if 'Name or service not known' in text or 'getaddrinfo' in text:
            hints.append("DNS/네트워크 문제 - 서버에서 smtp.gmail.com 해석 여부 확인.")
        for h in hints:
            self.stdout.write(f"     ↳ 힌트: {h}")
