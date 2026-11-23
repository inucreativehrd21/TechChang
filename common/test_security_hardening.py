"""2026-11-24 보안 점검 회귀 검사 — 로그인 실패 제한, 비밀번호 재설정 링크, 포트폴리오 링크 주소, allauth 화면 닫힘."""
import re

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.core.cache import cache, caches
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from common import login_throttle
from common.models import Profile


def member(username='member1', password='Right-pass-2026', email='member1@example.test', verified=True):
    user = User.objects.create_user(username, email=email, password=password)
    Profile.objects.update_or_create(user=user, defaults={'is_email_verified': verified})
    return user


UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'


class LoginThrottleTests(TestCase):
    def setUp(self):
        caches['throttle'].clear()
        cache.clear()           # 보안 미들웨어의 의심 점수·IP 차단도 테스트마다 비워요
        self.user = member()
        self.url = reverse('common:login')

    def post(self, password, username='member1', ip='198.51.100.7'):
        return self.client.post(self.url, {'username': username, 'password': password}, REMOTE_ADDR=ip,
                                HTTP_USER_AGENT=UA)

    def test_account_is_locked_after_repeated_failures_even_with_the_right_password(self):
        for _ in range(login_throttle.ACCOUNT_LIMIT):
            self.assertEqual(self.post('wrong').status_code, 200)
        response = self.post('Right-pass-2026', ip='203.0.113.9')   # 다른 IP 에서 맞는 비밀번호여도
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, '로그인 시도가 너무 많아요', status_code=429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unknown_account_gets_the_same_lock_message(self):
        for _ in range(login_throttle.ACCOUNT_LIMIT):
            self.post('wrong', username='nobody-here')
        self.assertEqual(self.post('x', username='NOBODY-here').status_code, 429)

    def test_success_clears_account_failures(self):
        for _ in range(login_throttle.ACCOUNT_LIMIT - 1):
            self.post('wrong')
        self.assertEqual(self.post('Right-pass-2026').status_code, 302)
        self.client.logout()
        for _ in range(login_throttle.ACCOUNT_LIMIT - 1):
            self.post('wrong')
        self.assertEqual(self.post('Right-pass-2026').status_code, 302)

    def test_ip_limit_covers_many_accounts(self):
        for i in range(login_throttle.IP_LIMIT):
            self.post('wrong', username=f'user{i}')
        self.assertEqual(self.post('Right-pass-2026').status_code, 429)
        self.assertEqual(self.post('Right-pass-2026', ip='192.0.2.50').status_code, 302)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SITE_BASE_URL='https://techchang.com')
class PasswordResetTests(TestCase):
    def setUp(self):
        caches['throttle'].clear()
        cache.clear()
        self.user = member()
        self.url = reverse('common:password_reset')

    def request(self, username='member1', email='member1@example.test', ip='198.51.100.7', **extra):
        return self.client.post(self.url, {'username': username, 'email': email}, REMOTE_ADDR=ip, follow=True,
                                HTTP_USER_AGENT=UA, **extra)

    def test_request_does_not_change_password_and_hides_whether_account_matches(self):
        known = self.request()
        unknown = self.request(username='member1', email='other@example.test')
        self.assertContains(known, '일치하는 인증된 계정이 있으면')
        self.assertContains(unknown, '일치하는 인증된 계정이 있으면')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Right-pass-2026'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['member1@example.test'])

    def test_link_uses_fixed_host_and_sets_a_new_password_once(self):
        self.request(HTTP_HOST='testserver', HTTP_X_FORWARDED_HOST='evil.example')
        link = re.search(r'https://\S+', mail.outbox[0].body).group(0)
        self.assertTrue(link.startswith('https://techchang.com/common/password/reset/'))
        path = link.replace('https://techchang.com', '')
        page = self.client.get(path, follow=True, HTTP_USER_AGENT=UA)       # 토큰을 세션으로 옮기고 set-password 주소로 넘어가요
        self.assertTrue(page.context['validlink'])
        form_url = page.redirect_chain[-1][0]
        done = self.client.post(form_url, {'new_password1': 'Brand-new-pass-77', 'new_password2': 'Brand-new-pass-77'},
                                HTTP_USER_AGENT=UA)
        self.assertRedirects(done, reverse('common:login'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-new-pass-77'))
        again = self.client.get(path, follow=True, HTTP_USER_AGENT=UA)
        self.assertFalse(again.context['validlink'])

    def test_unverified_account_gets_no_mail(self):
        member('member2', email='member2@example.test', verified=False)
        self.request(username='member2', email='member2@example.test')
        self.assertEqual(len(mail.outbox), 0)

    def test_requests_are_rate_limited(self):
        from common import views
        for _ in range(views.RESET_ACCOUNT_PER_HOUR):
            self.request()
        response = self.client.post(self.url, {'username': 'member1', 'email': 'member1@example.test'},
                                    REMOTE_ADDR='198.51.100.7', HTTP_USER_AGENT=UA)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), views.RESET_ACCOUNT_PER_HOUR)


class PortfolioLinkTests(TestCase):
    def call(self, value):
        from community.views.portfolio_views import _http_url
        request = RequestFactory().post('/', {'project_url': value})
        request.session = 'session'
        request._messages = FallbackStorage(request)
        return _http_url(request, 'project_url')

    def test_only_http_links_are_kept(self):
        self.assertEqual(self.call('https://github.com/me/app'), 'https://github.com/me/app')
        self.assertEqual(self.call('  http://example.com/a  '), 'http://example.com/a')
        for bad in ('javascript:alert(document.cookie)', 'JaVaScRiPt:alert(1)', 'data:text/html,<script>1</script>',
                    '//evil.example/x', 'vbscript:msgbox(1)'):
            with self.subTest(bad=bad):
                self.assertEqual(self.call(bad), '')
        self.assertEqual(self.call(''), '')


class AllauthClosedTests(TestCase):
    def test_parallel_signup_login_and_reset_screens_are_gone(self):
        for path in ('/accounts/signup/', '/accounts/login/', '/accounts/password/reset/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, HTTP_USER_AGENT=UA).status_code, 404)


class CspTemplateRuleTests(TestCase):
    """CSP 차단 모드(2026-11-24) — 템플릿에 nonce 없는 인라인 스크립트·인라인 이벤트 속성·javascript: 주소가 없어야 해요.
    비활성 게임(틱택토·끝말잇기)은 다시 켜기 전에 바꿔야 하므로 제외해요."""
    SKIP = ('tictactoe', 'wordchain')

    def test_templates_follow_csp_rules(self):
        from pathlib import Path
        from django.conf import settings
        script = re.compile(r'<script(?![^>]*\bsrc=)(?![^>]*\bnonce=)(\s[^>]*)?>')
        handler = re.compile(r'\son(click|change|submit|load|error|input|mouseover|mouseout|focus|blur|keyup|keydown)\s*=')
        bad = []
        for path in Path(settings.BASE_DIR, 'templates').rglob('*.html'):
            if any(k in path.name for k in self.SKIP):
                continue
            text = path.read_text(encoding='utf-8')
            for kind, rx in (('script', script), ('handler', handler), ('js-url', re.compile(r'href="javascript:'))):
                for m in rx.finditer(text):
                    bad.append(f'{path.relative_to(settings.BASE_DIR)}:{text.count(chr(10), 0, m.start()) + 1} {kind}')
        self.assertEqual(bad, [])

    def test_shared_action_script_is_on_every_page(self):
        for ua in (UA, 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'):
            response = self.client.get('/', HTTP_USER_AGENT=ua)
            self.assertContains(response, 'js/csp-actions.js')
