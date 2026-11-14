"""SMTP 한도 초과·잘못된 주소·실패 후 반복 요청을 검증해요."""
from smtplib import SMTPAuthenticationError, SMTPDataError
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import EmailVerification


@override_settings(DEBUG=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailDeliveryFailureTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.defaults['HTTP_USER_AGENT'] = 'Mozilla/5.0'
        self.admin = User.objects.create_user('delivery-admin', email='owner@example.test', is_staff=True)
        self.client.force_login(self.admin)
        self.routes = ('common:send_verification_email', 'common:send_profile_verification_email')

    def post_email(self, route, value):
        return self.client.post(reverse(route), {'email': value}, content_type='application/json')

    def test_invalid_addresses_never_reach_smtp_or_create_codes(self):
        with patch('common.views.send_mail') as smtp:
            for route in self.routes:
                for address in ('01012345678', 'nickname', 'missing@', 'name@example..com', None, 123):
                    with self.subTest(route=route, address=address):
                        self.assertEqual(self.post_email(route, address).status_code, 400)
            smtp.assert_not_called()
        self.assertFalse(EmailVerification.objects.exists())

    def test_invalid_json_shape_is_rejected(self):
        for route in self.routes:
            for payload in ([], None, 'email@example.com'):
                with self.subTest(route=route, payload=payload):
                    response = self.client.post(reverse(route), payload, content_type='application/json')
                    self.assertEqual(response.status_code, 400)

    def test_quota_failure_is_clear_and_repeated_requests_are_throttled(self):
        for route in self.routes:
            with self.subTest(route=route):
                cache.clear()
                with patch('common.views.send_mail', side_effect=SMTPDataError(
                        550, b'5.4.5 Daily user sending limit exceeded')) as smtp:
                    response = self.post_email(route, 'new@example.test')
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()['error_code'], 'email_sending_limit')
                    self.assertIn('발송 한도', response.json()['message'])
                    self.assertNotIn('code', response.json())
                    self.assertFalse(EmailVerification.objects.exists())
                    self.assertEqual(self.post_email(route, 'new@example.test').status_code, 429)
                    # 같은 IP에서 수신 주소만 바꾸어도 바로 재시도할 수 없어요.
                    self.assertEqual(self.post_email(route, 'other@example.test').status_code, 429)
                    self.assertEqual(smtp.call_count, 1)

    def test_other_smtp_errors_are_not_reported_as_quota_errors(self):
        for route in self.routes:
            with self.subTest(route=route):
                cache.clear()
                with patch('common.views.send_mail', side_effect=SMTPAuthenticationError(535, b'auth failed')) as smtp:
                    response = self.post_email(route, 'new@example.test')
                    self.assertEqual(response.status_code, 500)
                    self.assertNotIn('발송 한도', response.json()['message'])
                    self.assertEqual(self.post_email(route, 'new@example.test').status_code, 429)
                    self.assertEqual(smtp.call_count, 1)
                self.assertFalse(EmailVerification.objects.exists())

    def test_delivery_can_recover_after_cooldown(self):
        for route in self.routes:
            with self.subTest(route=route):
                cache.clear()
                with patch('common.views.send_mail', side_effect=OSError('unavailable')):
                    self.assertEqual(self.post_email(route, 'new@example.test').status_code, 500)
                cache.clear()
                response = self.post_email(route, 'new@example.test')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['success'])
                self.assertTrue(EmailVerification.objects.filter(email='new@example.test').exists())
                EmailVerification.objects.all().delete()

    @override_settings(DEBUG=True)
    def test_quota_failure_never_returns_a_debug_code(self):
        with patch('common.views.send_mail', side_effect=SMTPDataError(550, b'5.4.5 Daily user sending limit exceeded')):
            response = self.post_email('common:send_verification_email', 'new@example.test')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('code', response.json())
