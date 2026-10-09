"""약관·처리방침 페이지, 가입 동의 기록, 카카오 회원 동의 게이트, 탈퇴 시 개인정보 파기."""
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from common import legal
from common.management.commands.send_log_report import mask_personal
from common.models import EmailVerification, KakaoUser, Profile
from community.models import Category, Portfolio, Question

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'


class LegalPagesTests(TestCase):
    def test_pages_render_on_pc_and_mobile_with_required_sections(self):
        for ua in (PC, MOBILE):
            privacy = self.client.get('/privacy/', HTTP_USER_AGENT=ua).content.decode()
            for must in ('개인정보 보호책임자', '문승현', '국외 이전', 'Oracle', '싱가포르', '파기', '쿠키', '1833-6972'):
                self.assertIn(must, privacy)
            terms = self.client.get('/terms/', HTTP_USER_AGENT=ua).content.decode()
            self.assertIn('만 14세 미만은 회원으로 가입할 수 없습니다', terms)

    def test_old_versions_stay_readable_and_noindex(self):
        html = self.client.get('/privacy/20260607/', HTTP_USER_AGENT=PC).content.decode()
        self.assertIn('지난 버전', html)
        self.assertIn('noindex', html)
        self.assertEqual(self.client.get('/terms/19990101/').status_code, 404)

    def test_pending_terms_show_the_version_in_force(self):
        with mock.patch('django.utils.timezone.localdate', return_value=date(2026, 10, 12)):
            self.assertEqual(legal.in_force('terms'), '20260607')
            html = self.client.get('/terms/', HTTP_USER_AGENT=PC).content.decode()
        self.assertIn('2026년 10월 16일부터 적용', html)
        with mock.patch('django.utils.timezone.localdate', return_value=date(2026, 10, 16)):
            self.assertEqual(legal.in_force('terms'), '20261016')

    def test_footer_links_privacy_policy_in_bold(self):
        html = self.client.get('/', HTTP_USER_AGENT=PC).content.decode()
        self.assertIn('<a href="/privacy/"><strong>개인정보 처리방침</strong></a>', html)


class SignupConsentTests(TestCase):
    def _post(self, **agree):
        EmailVerification.objects.create(email='new@example.com', code='12345678', is_verified=True,
                                         verified_at=timezone.now())
        data = {'username': 'newbie', 'email': 'new@example.com', 'password1': 'Str0ng-pass!9',
                'password2': 'Str0ng-pass!9', **agree}
        return self.client.post('/common/signup/', data, HTTP_USER_AGENT=PC)

    def test_signup_without_required_agreements_is_rejected(self):
        self._post(agree_terms='1', agree_privacy='1')          # 만 14세 확인 누락
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_signup_records_consent_version(self):
        self._post(agree_age='1', agree_terms='1', agree_privacy='1')
        profile = User.objects.get(username='newbie').profile
        self.assertIsNotNone(profile.terms_agreed_at)
        self.assertEqual(profile.terms_version, legal.consent_version())

    def test_signup_page_shows_three_required_boxes_and_no_marketing(self):
        html = self.client.get('/common/signup/', HTTP_USER_AGENT=PC).content.decode()
        for name in ('agree_age', 'agree_terms', 'agree_privacy'):
            self.assertIn(f'name="{name}"', html)
        self.assertNotIn('마케팅', html)
        self.assertIn('동의하지 않을 권리', html)


class KakaoConsentGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('kakao_123', password='x')
        Profile.objects.get_or_create(user=self.user)
        self.client.force_login(self.user)

    def test_kakao_member_without_consent_is_sent_to_consent_page(self):
        res = self.client.get('/series/', HTTP_USER_AGENT=PC)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res['Location'].startswith('/common/consent/?next='))
        self.assertEqual(self.client.get('/privacy/', HTTP_USER_AGENT=PC).status_code, 200)   # 문서는 볼 수 있다

    def test_consent_submit_records_and_unblocks(self):
        res = self.client.post('/common/consent/', {'agree_age': '1', 'agree_terms': '1', 'agree_privacy': '1',
                                                     'next': '/series/'}, HTTP_USER_AGENT=PC)
        self.assertEqual(res['Location'], '/series/')
        self.user.profile.refresh_from_db()
        self.assertIsNotNone(self.user.profile.terms_agreed_at)
        self.assertEqual(self.client.get('/series/', HTTP_USER_AGENT=PC).status_code, 200)

    def test_partial_consent_is_refused(self):
        self.client.post('/common/consent/', {'agree_terms': '1'}, HTTP_USER_AGENT=PC)
        self.user.profile.refresh_from_db()
        self.assertIsNone(self.user.profile.terms_agreed_at)


class WithdrawalTests(TestCase):
    def setUp(self):
        self.cat = Category.objects.create(name='HRD')

    def test_withdrawal_destroys_personal_data(self):
        user = User.objects.create_user('alice', email='alice@example.com', password='pw-123456!')
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.nickname, profile.is_email_verified = '앨리스', True
        profile.save()
        Portfolio.objects.create(user=user, display_name='Alice Kim', email='alice@work.example')
        q = Question.objects.create(author=user, category=self.cat, subject='질문', content='본문',
                                    create_date=timezone.now())
        self.client.force_login(user)
        self.client.post('/common/account/delete/', {'password': 'pw-123456!', 'confirm_delete': '회원탈퇴'},
                         HTTP_USER_AGENT=PC)
        user.refresh_from_db()
        self.assertEqual((user.username, user.email, user.is_active), (f'withdrawn_{user.id}', '', False))
        self.assertFalse(user.has_usable_password())
        self.assertIsNone(Profile.objects.get(user=user).nickname)
        self.assertFalse(Portfolio.objects.filter(user=user).exists())
        q.refresh_from_db()
        self.assertTrue(q.is_deleted)
        self.assertFalse(User.objects.filter(email='alice@example.com').exists())

    def test_kakao_member_can_withdraw_without_password(self):
        user = User.objects.create_user('kakao_777', email='k@kakao.user', password='random')
        Profile.objects.get_or_create(user=user)
        Profile.objects.filter(user=user).update(terms_agreed_at=timezone.now())   # 동의를 마친 카카오 회원
        KakaoUser.objects.create(kakao_id=777, nickname='카카오', email='k@example.com', access_token='tok')
        self.client.force_login(user)
        page = self.client.get('/common/account/delete/', HTTP_USER_AGENT=PC).content.decode()
        self.assertNotIn('name="password"', page)
        self.client.post('/common/account/delete/', {'confirm_delete': '회원탈퇴'}, HTTP_USER_AGENT=PC)
        user.refresh_from_db()
        self.assertEqual(user.username, f'withdrawn_{user.id}')
        self.assertFalse(KakaoUser.objects.filter(kakao_id=777).exists())

    def test_purge_command_cleans_legacy_withdrawals_and_old_verifications(self):
        legacy = User.objects.create_user('deleted_9_bob', email='deleted_9_bob@example.com', is_active=False)
        ev = EmailVerification.objects.create(email='x@example.com', code='1')
        EmailVerification.objects.filter(pk=ev.pk).update(created_at=timezone.now() - timedelta(days=2))
        out = StringIO()
        call_command('purge_personal_data', '--withdrawn', stdout=out)
        legacy.refresh_from_db()
        self.assertEqual((legacy.username, legacy.email), (f'withdrawn_{legacy.id}', ''))
        self.assertFalse(EmailVerification.objects.filter(pk=ev.pk).exists())


class LogMaskingTests(TestCase):
    def test_ip_and_email_are_masked_before_ai_analysis(self):
        line = 'ERROR login failed for bob@example.com from 203.0.113.7 and 2001:db8::1 via fe80:0:0:0:1:2:3:4'
        masked = mask_personal(line)
        self.assertNotIn('bob@example.com', masked)
        self.assertNotIn('203.0.113.7', masked)
        self.assertNotIn('fe80:0:0:0:1:2:3:4', masked)
        self.assertIn('[email]', masked)
