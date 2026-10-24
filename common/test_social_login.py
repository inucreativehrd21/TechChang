"""실제 세션·CSRF·콜백을 거치는 계정 연결 검사. 공급자 HTTP만 모의한다."""
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from common.models import Profile, SocialIdentity

PC = 'Mozilla/5.0 Windows NT 10.0 Chrome/130'


@override_settings(KAKAO_REST_API_KEY='client', KAKAO_CLIENT_SECRET='secret',
                   GOOGLE_CLIENT_ID='client', GOOGLE_CLIENT_SECRET='secret')
class SocialLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=PC)
        self.user = User.objects.create_user('original', email='owner@example.com', password='pw123')
        Profile.objects.update_or_create(user=self.user, defaults={'is_email_verified': True,
                                                                  'terms_agreed_at': timezone.now(), 'points': 99})

    def begin(self, provider='kakao', connect=False):
        if connect:
            self.client.force_login(self.user)
            self.client.get('/common/connections/')
            response = self.client.post(f'/common/connections/{provider}/connect/',
                                        HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        else:
            response = self.client.get(f'/common/{provider}/login/?next=/rookie/lite/')
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.url).query)
        self.assertIn('state', query, response.url)
        return query['state'][0]

    def finish(self, state, provider='kakao', identity=('123', 'owner@example.com', '이름', True)):
        with mock.patch('common.social_views._identity', return_value=identity):
            return self.client.get(f'/common/{provider}/callback/', {'code': 'code', 'state': state})

    def test_existing_account_connect_and_subsequent_login_preserve_user_and_points(self):
        state = self.begin(connect=True)
        self.finish(state)
        identity = SocialIdentity.objects.get()
        self.assertEqual(identity.user_id, self.user.pk)
        self.client.logout()
        state = self.begin()
        response = self.finish(state)
        self.assertEqual(response.url, '/rookie/lite/')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        self.assertEqual(Profile.objects.get(user=self.user).points, 99)
        self.assertEqual(User.objects.count(), 1)

    def test_email_match_requires_explicit_connection_without_logging_in(self):
        self.finish(self.begin())
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(SocialIdentity.objects.exists())
        self.assertEqual(User.objects.count(), 1)

    def test_cannot_link_another_members_identity(self):
        other = User.objects.create_user('other')
        SocialIdentity.objects.create(user=other, provider='kakao', subject='123')
        self.finish(self.begin(connect=True))
        self.assertEqual(SocialIdentity.objects.get().user_id, other.pk)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_state_expiry_replay_cancel_and_session_change_make_no_provider_call(self):
        for case in ('mismatch', 'expired', 'cancel', 'session'):
            with self.subTest(case=case):
                state = self.begin(connect=True)
                if case == 'expired':
                    session = self.client.session
                    flow = session['social_kakao']
                    flow['created'] -= 301
                    session['social_kakao'] = flow
                    session.save()
                if case == 'session':
                    self.client.logout()
                data = {'state': 'wrong' if case == 'mismatch' else state, 'code': 'code'}
                if case == 'cancel':
                    data['error'] = 'access_denied'
                with mock.patch('common.social_views._identity') as fetch:
                    self.client.get('/common/kakao/callback/', data)
                    self.client.get('/common/kakao/callback/', data)
                fetch.assert_not_called()

    def test_new_google_member_gets_unusable_password_verified_email_and_consent_gate(self):
        state = self.begin('google')
        self.finish(state, 'google', ('google-1', 'new@example.com', '새회원', True))
        user = SocialIdentity.objects.get().user
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.profile.is_email_verified)
        self.assertIsNone(user.profile.terms_agreed_at)
        self.assertTrue(self.client.get('/rookie/lite/').url.startswith('/common/consent/'))

    def test_google_verifies_id_token_audience_and_nonce(self):
        from common.social_views import _identity
        response = mock.Mock()
        response.json.return_value = {'id_token': 'signed-token'}
        flow = {'callback': 'https://techchang.com/common/google/callback/', 'nonce': 'nonce'}
        with mock.patch('common.social_views.requests.post', return_value=response) as post, \
                mock.patch('google.oauth2.id_token.verify_oauth2_token', return_value={
                    'sub': 'google-1', 'nonce': 'wrong', 'email_verified': True}) as verify:
            with self.assertRaises(ValueError):
                _identity('google', 'code', flow)
            self.assertEqual(verify.call_args.args[2], 'client')
            self.assertEqual(post.call_args.kwargs['timeout'], 15)

    def test_new_members_share_profile_format_and_missing_email_is_not_marked_verified(self):
        for provider in ('google', 'kakao'):
            for has_email in (True, False):
                with self.subTest(provider=provider, has_email=has_email):
                    self.client.logout()
                    subject = f'{provider}-{has_email}' if provider == 'google' else ('321' if has_email else '322')
                    email = f' {provider}@EXAMPLE.COM ' if has_email else ''
                    self.finish(self.begin(provider), provider, (subject, email, ' 이름 ', True))
                    user = SocialIdentity.objects.get(provider=provider, subject=subject).user
                    self.assertEqual(user.email, f'{provider}@example.com' if has_email else '')
                    self.assertFalse(user.has_usable_password())
                    self.assertEqual((user.profile.nickname, user.profile.is_email_verified), ('이름', has_email))
                    self.assertEqual(Profile.objects.filter(user=user).count(), 1)

    def test_connect_requires_post_and_csrf(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/common/connections/kakao/connect/').status_code, 405)
        self.assertEqual(self.client.post('/common/connections/kakao/connect/').status_code, 403)

    def test_open_redirect_is_dropped(self):
        self.client.get('/common/google/login/?next=https://attacker.example/')
        self.assertEqual(self.client.session['social_google']['next'], '/')

    def test_disconnect_requires_password_and_protects_last_login(self):
        self.client.force_login(self.user)
        SocialIdentity.objects.create(user=self.user, provider='google', subject='g')
        self.client.get('/common/connections/')
        token = self.client.cookies['csrftoken'].value
        url = '/common/connections/google/disconnect/'
        self.client.post(url, {'password': 'wrong'}, HTTP_X_CSRFTOKEN=token)
        self.assertTrue(SocialIdentity.objects.exists())
        self.client.post(url, {'password': 'pw123'}, HTTP_X_CSRFTOKEN=token)
        self.assertFalse(SocialIdentity.objects.exists())
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)
        SocialIdentity.objects.create(user=self.user, provider='google', subject='g')
        self.client.get('/common/connections/')
        self.client.post(url, HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertTrue(SocialIdentity.objects.exists())

    def test_google_button_requires_config_on_both_layouts(self):
        for ua in (PC, 'Mozilla/5.0 iPhone Mobile'):
            self.assertContains(self.client.get('/common/login/', HTTP_USER_AGENT=ua), 'Google로 계속하기')
            with override_settings(GOOGLE_CLIENT_SECRET=''):
                self.assertNotContains(self.client.get('/common/login/', HTTP_USER_AGENT=ua), 'Google로 계속하기')

    def test_withdraw_destroys_our_identity(self):
        from common.services.account import withdraw
        SocialIdentity.objects.create(user=self.user, provider='google', subject='g')
        withdraw(self.user)
        self.assertFalse(SocialIdentity.objects.exists())

    def test_legacy_kakao_mapping_preserves_existing_member(self):
        import importlib
        from types import SimpleNamespace
        from django.apps import apps
        from common.models import KakaoUser
        legacy = User.objects.create_user('kakao_777', email='legacy@example.com')
        Profile.objects.update_or_create(user=legacy, defaults={'terms_agreed_at': timezone.now()})
        KakaoUser.objects.create(kakao_id=777, access_token='legacy-token')
        migration = importlib.import_module('common.migrations.0015_socialidentity')
        migration.legacy_kakao(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        identity = SocialIdentity.objects.get(provider='kakao', subject='777')
        self.assertEqual(identity.user_id, legacy.pk)
        self.assertFalse(any('token' in field.name for field in SocialIdentity._meta.fields))
        self.finish(self.begin(), identity=('777', 'legacy@example.com', '', True))
        self.assertEqual(int(self.client.session['_auth_user_id']), legacy.pk)

    def password_login(self, **kwargs):
        self.client.get('/common/login/')
        return self.client.post('/common/login/', {'username': self.user.username, 'password': 'pw123', **kwargs},
                                HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def test_classic_login_prompt_once_per_login_on_pc_and_mobile(self):
        for ua in (PC, 'Mozilla/5.0 iPhone Mobile'):
            with self.subTest(ua=ua):
                self.client.logout()
                self.client.defaults['HTTP_USER_AGENT'] = ua
                response = self.password_login(next='/series/')
                self.assertEqual(response.url, '/series/')
                self.assertContains(self.client.get('/series/'), 'id="account-link-prompt"')
                self.assertNotContains(self.client.get('/series/'), 'id="account-link-prompt"')

    def test_linked_or_failed_login_and_disabled_providers_do_not_prompt(self):
        self.password_login(password='incorrect')
        self.assertNotIn('account_link_prompt_user', self.client.session)
        SocialIdentity.objects.create(user=self.user, provider='google', subject='g')
        self.password_login()
        self.assertNotContains(self.client.get('/series/'), 'id="account-link-prompt"')
        self.client.logout()
        SocialIdentity.objects.all().delete()
        with override_settings(GOOGLE_CLIENT_ID='', KAKAO_REST_API_KEY=''):
            self.password_login()
            self.assertNotIn('account_link_prompt_user', self.client.session)

    def test_connect_page_consumes_prompt_and_allows_unverified_classic_member(self):
        Profile.objects.filter(user=self.user).update(is_email_verified=False)
        self.password_login()
        self.assertContains(self.client.get('/common/email/required/'), 'id="account-link-prompt"')
        self.assertContains(self.client.get('/common/connections/'), 'Google 계정 연결하기')
        self.assertNotIn('account_link_prompt_user', self.client.session)
        state = self.begin('google', connect=True)
        self.finish(state, 'google', ('g', 'different@example.com', '구글 이름', True))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'owner@example.com')
        self.assertFalse(self.user.profile.is_email_verified)  # 다른 이메일을 인증된 것으로 바꾸지 않아요.
        self.assertEqual(self.client.get('/series/').status_code, 200)

    def test_both_providers_keep_profile_password_posts_points_and_both_careers(self):
        from community.models import Category, Question, RookiePlayer, LiteCareer
        profile = Profile.objects.get(user=self.user)
        profile.nickname = '내 닉네임'
        profile.save()
        password = self.user.password
        question = Question.objects.create(author=self.user, category=Category.objects.create(name='연결 검사'),
                                           subject='내 글', content='본문', create_date=timezone.now())
        today = timezone.localdate()
        player = RookiePlayer.objects.create(user=self.user, name='선수', role='batter', team='LG',
                                              last_active=today, settled_through=today, tp=37)
        career = LiteCareer.objects.create(user=self.user, name='커리어', role='batter', position='OF',
                                           style='contact', region='서울', team='LG', flags={'chosen': 'training'})
        for provider, subject in (('google', 'g'), ('kakao', '123')):
            self.finish(self.begin(provider, connect=True), provider, (subject, 'other@example.com', '공급자 이름', True))
            self.client.logout()
            self.finish(self.begin(provider), provider, (subject, 'other@example.com', '공급자 이름', True))
            self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
            self.assertNotIn('account_link_prompt_user', self.client.session)
        self.user.refresh_from_db()
        profile.refresh_from_db()
        question.refresh_from_db()
        player.refresh_from_db()
        career.refresh_from_db()
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(SocialIdentity.objects.filter(user=self.user).count(), 2)
        self.assertEqual((self.user.email, self.user.password), ('owner@example.com', password))
        self.assertEqual((profile.nickname, profile.points), ('내 닉네임', 99))
        self.assertEqual((question.author_id, player.user_id, player.tp, career.user_id, career.flags),
                         (self.user.pk, self.user.pk, 37, self.user.pk, {'chosen': 'training'}))
        self.client.logout()
        self.assertEqual(self.password_login().status_code, 302)

    def test_username_prefix_does_not_grant_social_exemptions_or_delete_others_legacy_data(self):
        from common.models import KakaoUser
        from common.services.account import withdraw
        user = User.objects.create_user('kakao_888', password='real-password')
        KakaoUser.objects.create(kakao_id=888, access_token='historical')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/series/').url, '/common/email/required/')
        Profile.objects.filter(user=user).update(is_email_verified=True)
        self.client.get('/common/account/delete/')
        self.client.post('/common/account/delete/', {'confirm_delete': '회원탈퇴'},
                         HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        user.refresh_from_db()
        self.assertTrue(user.is_active)  # 일반 비밀번호 회원은 접두사와 무관하게 비밀번호 확인이 필요해요.
        withdraw(user)
        self.assertTrue(KakaoUser.objects.filter(kakao_id=888).exists())

    def test_legacy_normalization_fills_only_missing_data_without_changing_password_or_claiming_verification(self):
        import importlib
        from types import SimpleNamespace
        from django.apps import apps
        from common.models import KakaoUser
        migration = importlib.import_module('common.migrations.0016_normalize_account_profiles')
        legacy = User.objects.create_user('kakao_777', email='kakao_777@kakao.user', password='preserved')
        SocialIdentity.objects.create(user=legacy, provider='kakao', subject='777')
        row = KakaoUser.objects.create(kakao_id=777, nickname='카카오 별명', email='old@EXAMPLE.COM',
                                       access_token='old-token', refresh_token='old-refresh')
        original_password = legacy.password
        editor = SimpleNamespace(connection=SimpleNamespace(alias='default'))
        migration.normalize_profiles(apps, editor)
        legacy.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual((legacy.email, legacy.profile.nickname), ('old@example.com', '카카오 별명'))
        self.assertFalse(legacy.profile.is_email_verified)
        self.assertEqual(legacy.password, original_password)
        self.assertEqual((row.access_token, row.refresh_token), ('', None))
        Profile.objects.filter(user=legacy).update(nickname='내가 수정한 이름', points=123)
        migration.normalize_profiles(apps, editor)
        legacy.refresh_from_db()
        self.assertEqual((legacy.profile.nickname, legacy.profile.points), ('내가 수정한 이름', 123))
