"""게임 운영 설정의 권한·원자성·워커 간 반영·기존 관리 조작을 검증해요."""
import time
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from .game_controls import FEATURES, enabled, snapshot_scope
from .models import GameControlState, GameControlChange, Profile


@override_settings(ROOKIE_SERIES_ENABLED=False, ROOKIE_ENV_ENABLED=False, ROOKIE_EXTREME_ENABLED=False, ROOKIE_EXTREME_PREVIEW=False)
class GameControlTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('game-admin', email='admin@example.test', password='test12345', is_staff=True, is_superuser=True)
        Profile.objects.update_or_create(user=self.admin, defaults={'is_email_verified': True})
        self.client.force_login(self.admin)
        self.authenticate_otp()

    def authenticate_otp(self):
        session = self.client.session
        session['admin_otp_until'] = time.time()+1800
        session['admin_otp_ip'] = '127.0.0.1'
        session.save()

    def payload(self, **values):
        data = {f['key']: 'inherit' for f in FEATURES}
        data['revision'] = GameControlState.objects.first().revision if GameControlState.objects.exists() else 0
        data.update(values)
        return data

    def test_no_override_keeps_environment_and_get_does_not_write(self):
        self.assertFalse(enabled('ROOKIE_SERIES_ENABLED'))
        with override_settings(ROOKIE_SERIES_ENABLED=True):
            self.assertTrue(enabled('ROOKIE_SERIES_ENABLED'))
        response = self.client.get(reverse('common:admin_games'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '게임 관리')
        self.assertEqual(GameControlState.objects.count(), 0)

    def test_save_is_persistent_audited_and_reaches_the_game(self):
        data = self.payload(ROOKIE_SERIES_ENABLED='on', ROOKIE_ENV_ENABLED='on')
        self.assertEqual(self.client.post(reverse('common:admin_games'), data).status_code, 302)
        from community import rookie_series, rookie_env
        self.assertTrue(rookie_series.enabled())
        self.assertTrue(rookie_env.enabled())
        state = GameControlState.objects.get(pk=1)
        self.assertEqual(state.revision, 1)
        self.assertEqual(state.updated_by, self.admin)
        self.assertEqual(len(GameControlChange.objects.get().changes), 2)
        self.assertEqual(GameControlChange.objects.get().actor, self.admin)
        self.assertEqual(self.client.get(reverse('common:admin_games')).status_code, 200)

    def test_off_overrides_true_environment_and_inherit_restores_it(self):
        with override_settings(ROOKIE_SERIES_ENABLED=True):
            self.client.post(reverse('common:admin_games'), self.payload(ROOKIE_SERIES_ENABLED='off'))
            self.assertFalse(enabled('ROOKIE_SERIES_ENABLED'))
            self.client.post(reverse('common:admin_games'), self.payload())
            self.assertTrue(enabled('ROOKIE_SERIES_ENABLED'))
            self.assertNotIn('ROOKIE_SERIES_ENABLED', GameControlState.objects.get().overrides)

    def test_invalid_or_stale_save_cannot_partially_change_settings(self):
        bad = self.payload(ROOKIE_ENV_ENABLED='unexpected', ROOKIE_SERIES_ENABLED='on')
        self.assertEqual(self.client.post(reverse('common:admin_games'), bad).status_code, 400)
        self.assertEqual(GameControlState.objects.count(), 0)
        old = self.payload(ROOKIE_ENV_ENABLED='on')
        self.client.post(reverse('common:admin_games'), self.payload(ROOKIE_SERIES_ENABLED='on'))
        response = self.client.post(reverse('common:admin_games'), old)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, '다른 관리자가', status_code=409)
        self.assertEqual(GameControlState.objects.get().overrides, {'ROOKIE_SERIES_ENABLED': True})
        self.assertEqual(GameControlChange.objects.count(), 1)

    def test_schema_must_be_ready_before_enabling(self):
        from .game_admin_views import applied_migrations
        applied = applied_migrations()-{('community','0054_liteseason_env')}
        with patch('common.game_admin_views.applied_migrations', return_value=applied):
            response = self.client.post(reverse('common:admin_games'), self.payload(ROOKIE_ENV_ENABLED='on'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(GameControlState.objects.count(), 0)

    def test_feature_snapshot_is_stable_then_next_request_reads_new_value(self):
        state = GameControlState.objects.create(pk=1, overrides={'ROOKIE_ENV_ENABLED': False})
        with snapshot_scope():
            with self.assertNumQueries(1):
                self.assertFalse(enabled('ROOKIE_ENV_ENABLED'))
                self.assertFalse(enabled('ROOKIE_ENV_ENABLED'))
            GameControlState.objects.filter(pk=state.pk).update(overrides={'ROOKIE_ENV_ENABLED': True})
            self.assertFalse(enabled('ROOKIE_ENV_ENABLED'))
        with snapshot_scope():
            self.assertTrue(enabled('ROOKIE_ENV_ENABLED'))

    def test_permissions_otp_and_csrf_protect_writes(self):
        url = reverse('common:admin_games')
        anonymous = Client()
        self.assertEqual(anonymous.post(url, self.payload()).status_code, 302)
        session = self.client.session
        session.pop('admin_otp_until')
        session.save()
        response = self.client.post(url, self.payload())
        self.assertRedirects(response, reverse('common:admin_otp'), fetch_redirect_response=False)
        self.authenticate_otp()
        response = self.client.post(url, self.payload(), REMOTE_ADDR='192.0.2.8')
        self.assertRedirects(response, reverse('common:admin_otp'), fetch_redirect_response=False)
        self.assertEqual(GameControlState.objects.count(), 0)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        session = strict.session
        session.update({'admin_otp_until':time.time()+1800, 'admin_otp_ip':'127.0.0.1'})
        session.save()
        self.assertEqual(strict.post(url,self.payload()).status_code,403)
        normal = User.objects.create_user('normal',password='password123')
        Profile.objects.update_or_create(user=normal,defaults={'is_email_verified':True})
        self.client.force_login(normal)
        self.assertEqual(self.client.post(url,self.payload()).status_code,302)
        self.assertEqual(GameControlState.objects.count(),0)

    @override_settings(DEBUG=False)
    def test_admin_preview_works_without_making_public_debug_preview_available(self):
        response=self.client.get(reverse('common:admin_game_preview')+'?scene=environment')
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'common/admin_game_preview.html')
        self.assertContains(response,'올 시즌 예보')
        self.assertEqual(self.client.get('/rookie/preview/?scene=environment&rookie_admin_preview=1').status_code,404)
        from community.models import LiteCareer, RookiePlayer
        self.assertEqual(LiteCareer.objects.count()+RookiePlayer.objects.count(),0)

    def test_all_admin_shells_render_on_desktop_and_mobile(self):
        routes=['admin_dashboard','admin_games','admin_user_list','admin_portfolio_approval','admin_blocked_ip_list','server_logs']
        for mobile in (False,True):
            ua='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148' if mobile else 'Mozilla/5.0 Windows NT 10.0 Chrome/130'
            for route in routes:
                response=self.client.get(reverse('common:'+route),HTTP_USER_AGENT=ua)
                self.assertEqual(response.status_code,200,route)
                self.assertContains(response,'admin-dashboard.css')
                self.assertTemplateUsed(response,'base_mobile.html' if mobile else 'base.html')
            self.assertEqual(self.client.get(reverse('office:admin'),HTTP_USER_AGENT=ua).status_code,200)

    def test_password_reset_does_not_clear_profile_or_staff(self):
        target=User.objects.create_user('target',password='before123',email='member@example.test',is_staff=True)
        Profile.objects.update_or_create(user=target,defaults={'nickname':'유지할 별명','rank':'member','is_email_verified':True})
        response=self.client.post(reverse('common:admin_user_detail',args=[target.pk]),{'action':'password','new_password':'after12345','new_password_confirm':'after12345'})
        self.assertEqual(response.status_code,302)
        target.refresh_from_db()
        self.assertTrue(target.check_password('after12345'))
        self.assertTrue(target.is_staff)
        self.assertEqual(target.profile.nickname,'유지할 별명')
        self.assertEqual(target.profile.rank,'member')
