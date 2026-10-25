"""대회 선택 전에는 이후 기록을 숨기고, 실제 POST로 결산에 도착하면 공개한다."""
import random
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from . import rookie_lite as X
from .models import LiteSeason
from .test_rookie_lite import MOBILE, PC, new


@override_settings(ROOKIE_EXTREME_ENABLED=True, ROOKIE_ENV_ENABLED=False)
class TournamentFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.c = new('대회흐름')
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.c.user)

    def scene(self, league, moments, mode='lite'):
        c = self.c
        c.mode = mode
        c.league, c.club = league, 'lg' if league == 'kbo1' else '덕수고'
        self.s = LiteSeason.objects.create(
            career=c, year=c.year, age=c.age, league=league, club=c.club, games=100, war=7,
            totals={'g': 100, 'pa': 400, 'ab': 350, 'h': 120, 'hr': 31}, champion=True,
            team_of=10 if league == 'kbo1' else 0, team_rank=1, team_w=80, team_l=20,
            months=[dict(label=label, line=f'아직공개하면안되는기록{i}', w=10, l=5)
                    for i, label in enumerate(X._chunks(league))],
            awards=[dict(kind='ring', label='미래대회 우승'), dict(kind='mvp', label='미래 최우수선수')],
            press=[dict(tag='미래기사', title='시즌이 모두 끝난 뒤의 기사')])
        c.pending = dict(kind='decision', what='moment', year=c.year, i=0, done=[], moments=moments)
        c.save()
        return f'/rookie/{mode}/'

    def moment(self, kind, key='', when=''):
        title = X.INTL[key]['name'] if kind == 'intl' else key or '한국시리즈'
        return X.make_moment(self.c, kind, title + ' 결승', when, random.Random(2), key=key)

    def assert_no_final_results(self, response):
        for text in ('미래대회 우승', '미래 최우수선수', '시즌이 모두 끝난 뒤의 기사', '80승 20패'):
            self.assertNotContains(response, text)
        self.assertEqual(response.context['seasons'], [])

    def test_high_school_final_hides_current_and_later_tournaments_and_public_awards(self):
        url = self.scene('hs', [self.moment('amateur', '황금사자기')])
        for ua in (PC, MOBILE):
            with self.subTest(ua=ua):
                r = self.client.get(url, HTTP_USER_AGENT=ua)
                self.assert_no_final_results(r)
                self.assertEqual(len(r.context['season'].months), 2)
                self.assertContains(r, '아직공개하면안되는기록1')
                for i in range(2, 6):
                    self.assertNotContains(r, f'아직공개하면안되는기록{i}')
                public = self.client.get(f'{url}c/{self.c.pk}/', HTTP_USER_AGENT=ua)
                self.assertNotContains(public, '미래대회 우승')
                self.assertNotContains(public, '미래 최우수선수')
        self.s.refresh_from_db()
        self.assertTrue(self.s.champion)  # 화면용 처리로 저장된 결과를 지우지 않는다.
        self.assertEqual(len(self.s.months), 6)

    def test_international_boundaries_on_both_modes_and_templates(self):
        for mode in ('lite', 'extreme'):
            for key, count in (('wbc', 0), ('olympics', 4), ('asian', 5), ('premier12', 6)):
                self.c.seasons.all().delete()
                url = self.scene('kbo1', [self.moment('intl', key, X.INTL[key]['month'])], mode)
                for ua in (PC, MOBILE):
                    with self.subTest(mode=mode, key=key, ua=ua):
                        r = self.client.get(url, HTTP_USER_AGENT=ua)
                        self.assert_no_final_results(r)
                        self.assertEqual(len(r.context['season'].months) if r.context['season'] else 0, count)
                        for i in range(count, 6):
                            self.assertNotContains(r, f'아직공개하면안되는기록{i}')

    def test_post_reveals_only_finished_moment_then_final_review(self):
        url = self.scene('kbo1', [self.moment('intl', 'wbc', '3월'), self.moment('series', when='10월')])
        response = self.client.get(url, HTTP_USER_AGENT=MOBILE)
        self.assert_no_final_results(response)
        for i in range(2):
            cache.clear()
            self.c.refresh_from_db()
            current = self.c.pending['moments'][i]
            with mock.patch.object(X, 'play_moment', return_value=dict(
                    ok=True, text='끝내기 안타!', final=True, line='1타수 1안타', outcome='1B')):
                response = self.client.post(url + 'act/', dict(action='decide', what='moment',
                    choice=current['choices'][0][0]), follow=True, HTTP_USER_AGENT=MOBILE,
                    HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
            self.assertEqual(response.status_code, 200)
            self.c.refresh_from_db()
            if i == 0:
                self.assertEqual(self.c.pending['what'], 'moment')
                self.assert_no_final_results(response)
                self.assertContains(response, 'WBC 우승')
            else:
                self.assertEqual(self.c.pending['kind'], 'review')
                self.assertContains(response, '미래대회 우승')
                self.assertContains(response, '시즌이 모두 끝난 뒤의 기사')
                self.assertEqual(len(response.context['seasons']), 1)

    @override_settings(ROOKIE_ENV_ENABLED=True)
    def test_media_day_waits_for_its_own_moment(self):
        moments = [self.moment('amateur', '황금사자기'), self.moment('intl', 'premier12', '11월')]
        pending = dict(kind='decision', what='moment', year=1, i=0, done=[], moments=moments)
        self.assertEqual(X.moment_step(pending)['what'], 'moment')
        pending['i'] = 1
        media = X.moment_step(pending)
        self.assertEqual(media['what'], 'mediaday')
        self.assertEqual(media['stage'], '프리미어12 결승')
        self.assertEqual(X.moment_step(media['then'])['what'], 'moment')
        url = self.scene('kbo1', moments)
        self.c.pending = media
        self.c.save()
        response = self.client.get(url, HTTP_USER_AGENT=MOBILE)
        self.assert_no_final_results(response)
        self.assertContains(response, '바로 기자회견으로')
        self.assertContains(response, '프리미어12 결승')
        self.assertContains(response, 'name="what" value="mediaday"')

    def test_finished_season_queues_finals_in_calendar_order(self):
        c = self.c
        c.pending = dict(kind='plan', event=None, intl=[])
        rng = random.Random(11)
        half = X.start_season(c, ['contact', 'power'], 'normal', '', {}, rng)
        moments = [self.moment('intl', 'premier12', '11월'), self.moment('amateur', '황금사자기'),
                   self.moment('intl', 'wbc', '3월')]
        with mock.patch.object(X, 'moments_for', return_value=moments), mock.patch.object(X, 'TOURNAMENTS', {}):
            X.finish_season(c, half, rng)
        self.assertEqual([m['key'] for m in c.pending['moments']], ['wbc', '황금사자기', 'premier12'])
