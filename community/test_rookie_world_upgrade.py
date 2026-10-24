"""공개 모드·회원 비교·전 리그 기록·일일 리포트의 사용자 경로와 기록 보존 검사."""
from copy import deepcopy
from datetime import timedelta
import random
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from . import rookie_fan_reactions as Fans
from . import rookie_lite as X
from . import rookie_extreme as E
from . import rookie_peers as Peers
from . import rookie_reports as Reports
from . import rookie_league as L
from . import rookie_world as W
from . import rookie_world_hub as Hub
from .models import LiteCareer, LiteSeason, RookieGame, RookieSeasonStat
from .test_rookie_lite import member, new, PC, MOBILE
from .test_rookie_league import player


class WorldReadTests(SimpleTestCase):
    def fake(self):
        return SimpleNamespace(pk=21, flags={}, year=2, pending={'kind': 'review', 'year': 1}, club='lg', league='hs')

    def test_all_leagues_advance_even_when_player_is_in_school_without_mutating_player(self):
        p = self.fake()
        before, rng = deepcopy(p.__dict__), random.getstate()
        for code in W.LEAGUES:
            data = Hub.world(p, code)
            self.assertTrue(data['fixtures'], code)
            rows = data['table']['rows']
            self.assertEqual(sum(row['w'] for row in rows), sum(row['l'] for row in rows))
            self.assertEqual(sum(row['rf'] for row in rows), sum(row['ra'] for row in rows))
            self.assertTrue(all(row['g'] == data['table']['games'] for row in rows), code)
        self.assertEqual(p.__dict__, before)
        self.assertEqual(random.getstate(), rng)

    def test_team_player_stats_conserve_box_scores_and_are_reproducible(self):
        data = Hub.world(self.fake(), 'kbo1')
        a = Hub.team_stats(data, 'lg')
        self.assertEqual(a, Hub.team_stats(data, 'lg'))
        team = next(row for row in data['table']['rows'] if row['club'] == 'lg')
        bats = [p['totals'] for p in a if p['role'] == 'batter']
        pits = [p['totals'] for p in a if p['role'] == 'pitcher']
        self.assertEqual(sum(t.get('r', 0) for t in bats), team['rf'])
        self.assertEqual(sum(t.get('r', 0) for t in pits), team['ra'])
        self.assertEqual(sum(t.get('w', 0) for t in pits), team['w'])
        self.assertEqual(sum(t.get('l', 0) for t in pits), team['l'])
        self.assertEqual(sum(t.get('outs', 0) for t in pits), team['g'] * 27)
        for t in bats:
            self.assertTrue(0 <= t.get('hr', 0) <= t.get('h', 0) <= t.get('ab', 0) <= t.get('pa', 0))
        for t in pits:
            self.assertLessEqual(t.get('so', 0), t.get('outs', 0))
            self.assertLessEqual(t.get('hr', 0), t.get('h', 0))
            self.assertEqual(t.get('bf', 0), t.get('outs', 0) + t.get('h', 0) + t.get('bb', 0))

    def test_future_scores_are_not_exposed_and_different_league_is_independent(self):
        p = self.fake()
        p.year, p.pending = 1, {'kind': 'plan'}
        self.assertEqual(Hub.world(p, 'mlb')['fixtures'], [])
        self.assertTrue(all(not row['totals'] for row in Hub.team_stats(Hub.world(p, 'mlb'), 'nyy')))

    def test_fan_bank_has_192_original_bodies_and_avoids_twelve_year_repeats(self):
        self.assertGreaterEqual(sum(len(pool) for pool in Fans.BANK.values()), 192)
        for topic in Fans.BANK:
            keys = [Fans._pick(topic, 'same-career', year, 0)[1] for year in range(1, 13)]
            self.assertEqual(len(set(keys)), 12, topic)


class DatabaseRecordTests(TestCase):
    def setUp(self):
        cache.clear()

    def season(self, c, age=18, ovr=55, year=1):
        return LiteSeason.objects.create(career=c, age=age, year=year, league='hs', club=c.club, games=30,
                    ovr_end=ovr, war=3, totals=dict(g=30, pa=120, ab=100, h=35, d=5, t=0, hr=4, bb=20, so=15, rbi=20))

    def test_member_comparisons_use_real_same_age_role_and_exclude_self_and_other_modes(self):
        mine, peer = new('본인'), new('다른회원')
        self.season(mine)
        actual = self.season(peer)
        inactive = new('비활성')
        self.season(inactive)
        inactive.user.is_active = False
        inactive.user.save()
        wrong = new('다른유형', role='pitcher', position='SP')
        self.season(wrong)
        rows = Peers.comparisons(mine)
        self.assertEqual([r['player_id'] for r in rows], [peer.pk])
        self.assertEqual(rows[0]['age'], actual.age)
        self.assertEqual(rows[0]['metrics'][0]['peer'], '.350')
        self.assertEqual(rows[0]['url'], f'/rookie/lite/c/{peer.pk}/')
        self.assertEqual(rows, Peers.comparisons(mine))

    def test_peer_comparison_does_not_invent_a_member_when_pool_is_empty(self):
        self.assertEqual(Peers.comparisons(new('혼자')), [])

    def test_daily_report_uses_saved_batter_numbers_and_no_extra_games(self):
        p = player('리포트타자')
        day = timezone.localdate() - timedelta(days=1)
        season = L.get_season(1)
        RookieGame.objects.create(player=p, season=season, league='kbo1', day=day, no=1, opponent='kt',
            team_runs=6, opp_runs=2, summary='4타수 2안타', line=dict(g=1, pa=5, ab=4, h=2, hr=1, bb=1, so=1, rbi=3))
        before = p.games.count()
        report = Reports.daily(p, day)
        self.assertIn('4타수 2안타', report['summary'])
        self.assertIn('1홈런', report['summary'])
        self.assertEqual(report['metrics'][0], ('타율', '.500'))
        self.assertTrue(report['strengths'])
        self.assertEqual(p.games.count(), before)

    def test_pitcher_report_and_no_appearance_do_not_infer_unrecorded_causes(self):
        p = player('리포트투수', role='pitcher', position='SP')
        day = timezone.localdate() - timedelta(days=1)
        empty = Reports.daily(p, day)
        self.assertIn('출장 기록이 없습니다', empty['summary'])
        RookieGame.objects.create(player=p, season=L.get_season(1), league='kbo1', day=day, no=1, opponent='kt',
            summary='6이닝', line=dict(g=1, outs=18, h=4, bb=2, so=7, er=1, r=1, np=90, bf=24))
        report = Reports.daily(p, day)
        self.assertIn('6이닝', report['summary'])
        self.assertIn('7탈삼진', report['summary'])
        self.assertEqual(report['metrics'][1], ('평균자책점', '1.50'))
        self.assertTrue(any('볼넷 2개' in text for text in report['tasks']))

    def test_report_page_requires_login_and_never_uses_someone_elses_player(self):
        p = player('리포트페이지')
        other = player('남의리포트')
        client = Client(HTTP_USER_AGENT=PC)
        self.assertEqual(client.get('/rookie/report/').status_code, 302)
        client.force_login(p.user)
        response = client.get(f'/rookie/report/?p={other.pk}&day=9999-12-31')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['report']['player'].pk, p.pk)
        self.assertLess(response.context['report']['day'], timezone.localdate())

    def test_world_page_shows_kbo_while_member_is_in_little_league(self):
        p = player('리그관전', league='little')
        client = Client(HTTP_USER_AGENT=MOBILE)
        client.force_login(p.user)
        response = client.get('/rookie/world/?lg=kbo1&club=lg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['lg'], 'kbo1')
        self.assertEqual(len(response.context['batters']), 12)
        self.assertTrue(response.context['data']['fixtures'])


@override_settings(ROOKIE_EXTREME_ENABLED=True, ROOKIE_EXTREME_PREVIEW=False)
class PublicExtremeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=PC)

    def create_guest(self):
        page = self.client.get('/rookie/extreme/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '익스트림 모드')
        self.assertContains(page, '/rookie/extreme/new/')
        fields = dict(name='새도전', role='batter', position_batter='SS', style_batter='contact',
                      region='서울', team='lg', mode='lite')
        self.assertEqual(self.client.post('/rookie/extreme/new/', fields).status_code, 403)
        self.csrf = self.client.cookies['csrftoken'].value
        self.client.post('/rookie/extreme/new/', fields, HTTP_X_CSRFTOKEN=self.csrf)
        c = LiteCareer.objects.get(mode='extreme')
        self.assertTrue(c.guest)
        self.assertIsNone(c.user_id)
        return c

    def test_guest_public_play_csrf_event_replay_and_all_public_views(self):
        c = self.create_guest()
        event = E.event_view(c)
        data = dict(action='extreme_event', event_id=event['id'], choice=event['choices'][0]['key'])
        self.client.post('/rookie/extreme/act/', data, HTTP_X_CSRFTOKEN=self.csrf)
        c.refresh_from_db()
        before = deepcopy(c.flags)
        self.client.post('/rookie/extreme/act/', data, HTTP_X_CSRFTOKEN=self.csrf)
        c.refresh_from_db()
        self.assertEqual(c.flags, before)
        page = self.client.get('/rookie/extreme/')
        self.assertContains(page, 'data-rl-flow')
        self.assertNotContains(page, 'data-extreme-pending')
        for suffix in ('hall/', 'today/', 'cards/', f'c/{c.pk}/'):
            self.assertEqual(self.client.get('/rookie/extreme/' + suffix).status_code, 200, suffix)
        self.assertEqual(self.client.get('/rookie/extreme/world/?lg=kbo1').status_code, 404)
        self.assertEqual(self.client.get(f'/rookie/lite/c/{c.pk}/').status_code, 404)
        user = member('연결회원')
        lite = X.create(user, name='기존선수', role='batter', position='SS', style='contact', region='서울', team='lg')
        self.client.force_login(user)
        self.client.get('/rookie/extreme/')
        c.refresh_from_db()
        lite.refresh_from_db()
        self.assertEqual(c.user_id, user.pk)
        self.assertEqual(lite.mode, 'lite')
        self.assertIsNone(lite.retired_at)
        self.assertEqual(self.client.get(f'/rookie/extreme/c/{lite.pk}/').status_code, 404)

    def test_public_flag_off_keeps_routes_hidden_even_for_staff(self):
        user = member('켜짐꺼짐')
        user.is_staff = True
        user.save()
        self.client.force_login(user)
        with override_settings(ROOKIE_EXTREME_ENABLED=False):
            self.assertEqual(self.client.get('/rookie/extreme/').status_code, 404)
            self.assertEqual(self.client.get('/rookie/extreme/hall/').status_code, 404)

    def test_lite_and_extreme_world_are_hidden_and_direct_access_is_disabled(self):
        from .views import rookie_world_views
        for version in ('desktop', 'mobile'):
            cache.clear()
            self.client.cookies['force_version'] = version
            for mode in ('lite', 'extreme'):
                for suffix in ('', 'hall/', 'today/', 'cards/'):
                    page = self.client.get('/rookie/' + mode + '/' + suffix)
                    self.assertEqual(page.status_code, 200)
                    self.assertNotContains(page, '/rookie/' + mode + '/world/')
                    self.assertNotContains(page, '전체 리그·구단')
        with mock.patch.object(rookie_world_views.Hub, 'world') as world:
            for mode in ('lite', 'extreme'):
                self.assertEqual(self.client.get('/rookie/' + mode + '/world/?lg=mlb').status_code, 404)
            world.assert_not_called()
        page = self.client.get('/rookie/')
        self.assertContains(page, '/rookie/world/')

    def test_extreme_guest_cannot_control_another_guest_or_lite_career(self):
        c = self.create_guest()
        other = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=PC)
        other.get('/rookie/extreme/')
        event = E.event_view(c)
        other.post('/rookie/extreme/act/', dict(action='extreme_event', event_id=event['id'], choice=event['choices'][0]['key']),
                   HTTP_X_CSRFTOKEN=other.cookies['csrftoken'].value)
        c.refresh_from_db()
        self.assertEqual(E.event_view(c)['id'], event['id'])
