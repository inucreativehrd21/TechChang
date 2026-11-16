"""관리자 인증 메일은 최초 한 번과 명시적인 재발송 요청에만 발송해요."""
import time
from smtplib import SMTPDataError
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .views import ADMIN_OTP_CODE_TTL_SECONDS, ADMIN_OTP_WINDOW_SECONDS


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='no-reply@example.test',
)
class AdminOTPDeliveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.defaults['HTTP_USER_AGENT'] = 'Mozilla/5.0'
        self.clock = self.enterContext(patch('time.time', return_value=time.time()))
        self.enterContext(patch('common.views._admin_otp_recipient', return_value='admin@example.test'))
        self.admin = User.objects.create_user('otp-admin', is_staff=True)
        self.client.force_login(self.admin)
        self.url = reverse('common:admin_otp')

    def advance(self, seconds):
        self.clock.return_value += seconds

    def test_refresh_and_expired_code_never_resend(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        original_code = self.client.session['admin_otp_pending']['code']
        for elapsed in (20, 65, ADMIN_OTP_CODE_TTL_SECONDS + 1):
            self.advance(elapsed)
            self.client.get(self.url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.client.session['admin_otp_pending']['code'], original_code)

    def test_research_admin_polling_redirects_cannot_resend(self):
        self.enterContext(override_settings(LAB_OPERATOR_IDS=[self.admin.pk]))
        for _ in range(5):
            response = self.client.get(reverse('office:admin_activity'), follow=True)
            self.assertContains(response, '관리자 2차 인증')
            self.advance(65)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_button_sends_once_and_keeps_cooldown(self):
        self.client.get(self.url)
        self.client.post(self.url, {'action': 'resend'}, follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.advance(61)
        self.client.post(self.url, {'action': 'resend'}, follow=True)
        self.assertEqual(len(mail.outbox), 2)
        self.advance(61)
        self.client.get(self.url)
        self.assertEqual(len(mail.outbox), 2)

    def test_expired_code_verification_requires_manual_resend(self):
        self.client.get(self.url)
        code = self.client.session['admin_otp_pending']['code']
        self.advance(ADMIN_OTP_CODE_TTL_SECONDS + 1)
        self.client.post(self.url, {'action': 'verify', 'code': code}, follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('admin_otp_until', self.client.session)
        self.client.post(self.url, {'action': 'resend'}, follow=True)
        self.assertEqual(len(mail.outbox), 2)

    def test_success_then_authentication_expiry_requires_manual_resend(self):
        self.client.get(self.url)
        code = self.client.session['admin_otp_pending']['code']
        self.client.post(self.url, {'action': 'verify', 'code': code})
        self.assertGreater(self.client.session['admin_otp_until'], self.clock.return_value)
        self.assertNotIn('admin_otp_pending', self.client.session)
        self.advance(ADMIN_OTP_WINDOW_SECONDS + 1)
        self.client.get(self.url)
        self.assertEqual(len(mail.outbox), 1)
        self.client.post(self.url, {'action': 'resend'}, follow=True)
        self.assertEqual(len(mail.outbox), 2)

    def test_failed_first_send_is_not_automatically_retried(self):
        with patch('common.views.send_mail', side_effect=OSError('SMTP unavailable')) as send:
            self.client.get(self.url)
            self.advance(61)
            self.client.get(self.url)
            self.assertEqual(send.call_count, 1)
        self.client.post(self.url, {'action': 'resend'}, follow=True)
        self.assertEqual(len(mail.outbox), 1)

    def test_failed_send_also_throttles_manual_resends_and_explains_quota(self):
        with patch('common.views.send_mail', side_effect=SMTPDataError(
                550, b'5.4.5 Daily user sending limit exceeded')) as smtp:
            response = self.client.get(self.url)
            self.assertContains(response, '메일 발송 한도')
            self.assertNotIn('admin_otp_pending', self.client.session)
            response = self.client.post(self.url, {'action': 'resend'}, follow=True)
            self.assertContains(response, '60초')
            self.assertEqual(smtp.call_count, 1)
            self.advance(61)
            self.client.post(self.url, {'action': 'resend'}, follow=True)
            self.assertEqual(smtp.call_count, 2)
            self.advance(61)
            self.client.get(self.url)
            self.assertEqual(smtp.call_count, 2)
            self.assertNotIn('admin_otp_until', self.client.session)

    def test_legacy_pending_or_sent_sessions_do_not_auto_resend(self):
        for key, value in (
            ('admin_otp_sent_at', self.clock.return_value - 700),
            ('admin_otp_pending', {'code': 'old-code', 'exp': self.clock.return_value - 1}),
        ):
            with self.subTest(key=key):
                self.client.logout()
                self.client.force_login(self.admin)
                session = self.client.session
                session[key] = value
                session.save()
                self.client.get(self.url)
                self.assertEqual(len(mail.outbox), 0)
                session = self.client.session
                session.pop(key)
                session.save()

    def test_wrong_codes_and_attempt_limit_do_not_auto_resend(self):
        self.client.get(self.url)
        self.advance(61)
        for _ in range(6):
            self.client.post(self.url, {'action': 'verify', 'code': 'invalid'}, follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('admin_otp_pending', self.client.session)
        self.assertNotIn('admin_otp_until', self.client.session)

    def test_ip_change_cannot_verify_or_auto_resend(self):
        self.client.get(self.url)
        code = self.client.session['admin_otp_pending']['code']
        self.advance(61)
        self.client.post(self.url, {'action': 'verify', 'code': code},
                         REMOTE_ADDR='192.0.2.8', follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('admin_otp_until', self.client.session)

    def test_new_login_session_can_send_first_code(self):
        self.client.get(self.url)
        self.client.logout()
        self.client.force_login(self.admin)
        self.client.get(self.url)
        self.assertEqual(len(mail.outbox), 2)

    def test_unauthorized_requests_and_head_do_not_send(self):
        self.client.head(self.url)
        self.assertEqual(len(mail.outbox), 0)
        self.client.logout()
        self.client.get(self.url)
        self.assertEqual(len(mail.outbox), 0)
        user = User.objects.create_user('otp-member')
        self.client.force_login(user)
        self.client.get(self.url)
        self.assertEqual(len(mail.outbox), 0)

    def test_desktop_and_mobile_explain_manual_resend(self):
        for version in ('desktop', 'mobile'):
            with self.subTest(version=version):
                self.client.cookies['force_version'] = version
                response = self.client.get(self.url)
                self.assertContains(response, '처음 한 번만 자동 발송해요')
                self.assertContains(response, 'name="action" value="resend"')
        self.assertEqual(len(mail.outbox), 1)


class AdminOTPExpiryTests(TestCase):
    """OTP 인증 시간이 지나면 모든 관리 화면·동작·폴링이 재인증으로 간다(2026-11-16: 회원·IP·포트폴리오·연구실
    관리는 로그인만 확인해서 시간이 지나도 계속 쓸 수 있었다)."""

    def setUp(self):
        self.client.defaults['HTTP_USER_AGENT'] = 'Mozilla/5.0'
        self.clock = self.enterContext(patch('time.time', return_value=time.time()))
        self.admin = User.objects.create_superuser('otp-expiry', password='x')
        self.client.force_login(self.admin)
        session = self.client.session
        session['admin_otp_until'] = self.clock.return_value + ADMIN_OTP_WINDOW_SECONDS
        session['admin_otp_ip'] = '127.0.0.1'
        session.save()

    def expire(self):
        self.clock.return_value += ADMIN_OTP_WINDOW_SECONDS + 1

    def test_every_admin_screen_requires_otp_after_the_window(self):
        pages = [reverse('common:admin_dashboard'), reverse('common:admin_user_list'),
                 reverse('common:admin_blocked_ip_list'), reverse('common:admin_portfolio_approval'), '/lab/admin/']
        for url in pages:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.expire()
        for url in pages:
            response = self.client.get(url)
            self.assertRedirects(response, reverse('common:admin_otp'), fetch_redirect_response=False, msg_prefix=url)
            self.assertEqual(self.client.session['admin_otp_next'], url)

    def test_open_page_knows_how_long_the_otp_lasts(self):
        response = self.client.get(reverse('common:admin_user_list'))
        self.assertContains(response, f'data-otp-left="{ADMIN_OTP_WINDOW_SECONDS}"')
        self.assertContains(response, 'data-otp-url="/common/admin/otp/"')

    def test_expired_action_is_not_processed_and_returns_to_the_screen(self):
        from .models import BlockedIP
        self.expire()
        response = self.client.post(reverse('common:admin_block_ip'), {'ip_address': '203.0.113.9'},
                                    HTTP_REFERER='http://testserver/common/admin/ip/list/?page=2')
        self.assertRedirects(response, reverse('common:admin_otp'), fetch_redirect_response=False)
        self.assertFalse(BlockedIP.objects.filter(ip_address='203.0.113.9').exists())
        self.assertEqual(self.client.session['admin_otp_next'], '/common/admin/ip/list/?page=2')

    def test_foreign_referer_falls_back_to_dashboard(self):
        self.expire()
        self.client.post(reverse('common:admin_block_ip'), {'ip_address': '203.0.113.9'},
                         HTTP_REFERER='https://evil.example/phish')
        self.assertEqual(self.client.session['admin_otp_next'], reverse('common:admin_dashboard'))

    def test_polling_gets_json_instead_of_a_redirect(self):
        self.expire()
        for url, headers in ((reverse('common:server_live_logs'), {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}),
                             ('/lab/admin/activity.json', {'HTTP_ACCEPT': 'application/json'})):
            response = self.client.get(url, **headers)
            self.assertEqual(response.status_code, 403, url)
            self.assertTrue(response.json()['otp_required'])

    def test_otp_bound_to_another_ip_is_refused(self):
        response = self.client.get(reverse('common:admin_user_list'), REMOTE_ADDR='198.51.100.7')
        self.assertRedirects(response, reverse('common:admin_otp'), fetch_redirect_response=False)
