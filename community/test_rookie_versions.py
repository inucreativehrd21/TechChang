"""명예의 전당의 시작 버전 보존과 PC·모바일 필터 회귀 검사."""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from community import rookie as R, rookie_league as L, rookie_legacy as G
from community import rookie_lite as X, rookie_versions as V
from community.models import LiteCareer, LiteSeason, RookiePlayer, RookieSeasonStat

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'


def member(name):
    return User.objects.create_user(username=name)


def lite(name, version=V.CURRENT, *, retired=True, role='batter', when=None, guest=''):
    c = X.create(None if guest else member(name), name=name, role=role,
                 position='SP' if role == 'pitcher' else 'SS',
                 style='fire' if role == 'pitcher' else 'contact', region='서울', team='lg',
                 guest=guest, rng=random.Random(5))
    if version == 'missing':
        c.flags.pop('game_version')
    else:
        c.flags['game_version'] = version
    LiteSeason.objects.create(career=c, year=1, age=24, league='kbo1', club='lg',
                              games=144, war=5, ovr_end=75,
                              totals={'g': 144, 'pa': 600, 'ab': 500, 'h': 150})
    if retired:
        c.retired_at = when or timezone.now()
        c.pending = {'kind': 'retired'}
    c.save()
    return c


def full(name, version=V.CURRENT, *, retired=True):
    p = R.create(member(name), name=name, role='batter', position='SS', team='lg',
                 region='서울', rng=random.Random(5))
    if version == 'missing':
        p.career.pop('game_version')
    else:
        p.career['game_version'] = version
    p.league, p.club = 'kbo1', 'lg'
    if retired:
        p.retired_at = timezone.now()
    p.save()
    RookieSeasonStat.objects.create(player=p, user=p.user, season=L.get_season(1),
                                   name=name, role='batter', position='SS', team='lg', league='kbo1',
                                   totals={'g': 144, 'pa': 600, 'ab': 500, 'h': 150}, war=5, best_ovr=75)
    return p


class VersionCreationTests(TestCase):
    def test_new_member_and_guest_careers_are_stamped(self):
        p = R.create(member('새정식'), name='새정식', role='batter', team='lg', region='서울')
        c = X.create(member('새라이트'), name='새라이트', role='batter', position='SS',
                     style='contact', region='서울', team='lg')
        g = X.create(None, guest='new-guest', name='새손님', role='batter', position='SS',
                     style='contact', region='서울', team='lg')
        for obj in (p, c, g):
            obj.refresh_from_db()
            self.assertEqual(V.of(obj), '1.1')

    def test_existing_lite_continues_and_retires_in_legacy_version(self):
        c = lite('이전진행', 'missing', retired=False)
        rng = random.Random(31)
        c.year, c.age, c.grade, c.league, c.club = 2, 25, 0, 'kbo1', 'lg'
        c.pending = X.plan_step(c, rng)
        c.pending['event'] = None
        X.run_season(c, X.pick_programs(c, rng), 'normal', '', rng)
        X.retire(c)
        c.save()
        c.refresh_from_db()
        self.assertNotIn('game_version', c.flags)
        self.assertEqual(V.of(c), '1.0')
        self.assertIn(c.pk, [r['c'].pk for r in X.hall(version='1.0')])
        self.assertNotIn(c.pk, [r['c'].pk for r in X.hall()])

    def test_existing_full_retires_and_new_player_gets_current_version(self):
        p = full('이전정식', 'missing', retired=False)
        R.retire(p.user)
        p.refresh_from_db()
        self.assertNotIn('game_version', p.career)
        self.assertIn(p.pk, [r['p'].pk for r in G.league_career('kbo1', retired_only=True, version='1.0')])
        next_player = R.create(p.user, name='다음선수', role='batter', team='lg', region='서울')
        self.assertEqual(V.of(next_player), '1.1')

    def test_claim_guest_keeps_original_version(self):
        owner = member('이관계정')
        for label, version in (('옛손님', 'missing'), ('새손님', '1.1')):
            c = lite(label, version, guest=label)
            self.assertEqual(X.claim_guest(owner, label), 1)
            c.refresh_from_db()
            self.assertEqual(V.of(c), '1.0' if version == 'missing' else '1.1')
            self.assertEqual(c.user, owner)


class HallVersionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.old = lite('옛라이트', 'missing')
        cls.new = lite('새라이트')
        cls.old_full = full('옛정식', 'missing')
        cls.new_full = full('새정식')

    def setUp(self):
        cache.clear()

    def test_lite_filters_before_limit_and_keeps_launch_cutoff(self):
        for version, expected in (('1.0', self.old), ('1.1', self.new), ('bad', self.new), (None, self.new)):
            self.assertEqual([r['c'].pk for r in X.hall(limit=1, version=version)], [expected.pk])
        LiteCareer.objects.filter(pk=self.old.pk).update(created_at=X.HALL_SINCE - timedelta(seconds=1))
        self.assertEqual(X.hall(version='1.0'), [])

    def test_explicit_null_empty_and_missing_versions_are_legacy(self):
        for version in ('1.0', None, ''):
            with self.subTest(version=version):
                LiteCareer.objects.filter(pk=self.old.pk).update(flags={'game_version': version})
                RookiePlayer.objects.filter(pk=self.old_full.pk).update(career={'game_version': version})
                self.assertEqual([r['c'].pk for r in X.hall(version='1.0')], [self.old.pk])
                self.assertEqual([r['p'].pk for r in G.league_career('kbo1', version='1.0')], [self.old_full.pk])
                self.assertEqual([r['c'].pk for r in X.hall(version='1.1')], [self.new.pk])

    def test_full_hall_filters_and_general_career_stays_combined(self):
        for version, expected in (('1.0', self.old_full), ('1.1', self.new_full)):
            self.assertEqual([r['p'].pk for r in G.league_career('kbo1', retired_only=True, limit=1,
                                                              version=version)], [expected.pk])
        self.assertEqual({r['p'].pk for r in G.league_career('kbo1')}, {self.old_full.pk, self.new_full.pk})

    def test_lite_hall_and_lineup_are_separate_on_pc_and_mobile(self):
        for ua, cookie in ((PC, 'desktop'), (MOBILE, 'mobile')):
            self.client.cookies['force_version'] = cookie
            for version, expected, excluded in (('1.0', self.old, self.new), ('1.1', self.new, self.old)):
                with self.subTest(device=cookie, version=version):
                    response = self.client.get('/rookie/lite/hall/', {'version': version}, HTTP_USER_AGENT=ua)
                    self.assertContains(response, f'<option value="{version}" selected>', html=False)
                    self.assertContains(response, expected.name)
                    self.assertNotContains(response, excluded.name)
                    self.assertContains(response, f'/rookie/lite/today/?version={version}&amp;lg=kbo&amp;role=', html=False)
                    self.assertEqual([r['c'].pk for r in response.context['rows']], [expected.pk])
                    self.assertEqual(response.context['lineup']['filled'], 1)
                    self.assertEqual(next(r['r']['c'].pk for r in response.context['lineup']['field'] if r['r']), expected.pk)

    def test_today_combines_version_role_and_day_filters(self):
        start, _ = X.day_bounds()
        yesterday = lite('어제투수', 'missing', role='pitcher', when=start - timedelta(minutes=5))
        today = lite('오늘투수', 'missing', role='pitcher', when=start + timedelta(minutes=5))
        for day, expected in (('1', yesterday), ('', today)):
            response = self.client.get('/rookie/lite/today/',
                                       {'version': '1.0', 'role': 'pitcher', 'lg': 'kbo', 'd': day},
                                       HTTP_USER_AGENT=PC)
            self.assertEqual([r['c'].pk for r in response.context['rows']], [expected.pk])
            self.assertContains(response, '<option value="1.0" selected>', html=False)

    def test_full_hall_lineup_and_links_keep_version_on_pc_and_mobile(self):
        for ua, cookie in ((PC, 'desktop'), (MOBILE, 'mobile')):
            self.client.cookies['force_version'] = cookie
            for version, expected, excluded in (('1.0', self.old_full, self.new_full), ('1.1', self.new_full, self.old_full)):
                with self.subTest(device=cookie, version=version):
                    response = self.client.get('/rookie/records/', {'view': 'hof', 'lg': 'kbo1', 'version': version},
                                               HTTP_USER_AGENT=ua)
                    self.assertContains(response, expected.name)
                    self.assertNotContains(response, excluded.name)
                    self.assertContains(response, f'?view=hof&amp;lg=mlb&amp;version={version}', html=False)
                    self.assertEqual([r['p'].pk for r in response.context['rows']], [expected.pk])
                    self.assertEqual(response.context['lineup']['filled'], 1)

    def test_invalid_version_defaults_to_current_on_all_views(self):
        for path in ('/rookie/lite/hall/', '/rookie/lite/today/', '/rookie/records/'):
            cache.clear()
            response = self.client.get(path, {'version': 'nonsense', 'view': 'hof'}, HTTP_USER_AGENT=PC)
            self.assertEqual(response.context['hall_version'], '1.1')
