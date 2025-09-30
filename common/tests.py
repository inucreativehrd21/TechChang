from django.test import TestCase, override_settings
from django.urls import reverse
from django.core import mail
from django.core.cache import cache
from .models import EmailVerification


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='no-reply@testserver.local'
)
class EmailVerificationTests(TestCase):
    def setUp(self):
        cache.clear()

    def _post_json(self, url_name, payload):
        return self.client.post(
            reverse(url_name),
            data=payload,
            content_type='application/json'
        )

    def test_send_verification_email_creates_record_and_sends_mail(self):
        response = self._post_json('common:send_verification_email', {'email': 'user@example.com'})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(EmailVerification.objects.filter(email='user@example.com').count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_verify_email_code_success_flow(self):
        self._post_json('common:send_verification_email', {'email': 'user@example.com'})
        verification = EmailVerification.objects.get(email='user@example.com')

        response = self._post_json(
            'common:verify_email_code',
            {'email': 'user@example.com', 'code': verification.code}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        verification.refresh_from_db()
        self.assertTrue(verification.is_verified)
        self.assertIsNotNone(verification.verified_at)

    def test_verify_email_code_attempt_limit(self):
        self._post_json('common:send_verification_email', {'email': 'user@example.com'})
        # Consume allowed attempts with wrong codes
        for remaining in [4, 3, 2, 1]:
            response = self._post_json(
                'common:verify_email_code',
                {'email': 'user@example.com', 'code': '9999'}
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn(str(remaining), response.json()['message'])

        # Final attempt should lock out
        response = self._post_json(
            'common:verify_email_code',
            {'email': 'user@example.com', 'code': '9999'}
        )
        self.assertEqual(response.status_code, 429)
        self.assertFalse(response.json()['success'])
        self.assertFalse(EmailVerification.objects.filter(email='user@example.com', is_verified=False).exists())

    def test_send_verification_email_respects_cooldown(self):
        first = self._post_json('common:send_verification_email', {'email': 'user@example.com'})
        self.assertEqual(first.status_code, 200)

        second = self._post_json('common:send_verification_email', {'email': 'user@example.com'})
        self.assertEqual(second.status_code, 429)

        # fast-forward cooldown manually
        cache.clear()

        third = self._post_json('common:send_verification_email', {'email': 'user@example.com'})
        self.assertEqual(third.status_code, 200)
