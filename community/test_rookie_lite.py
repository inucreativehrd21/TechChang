"""야구선수 키우기 라이트(community/rookie_lite.py, 2026-10-18) — 한 판 30분 커리어 시뮬레이터."""
import random

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from common.models import Profile
from community import rookie_lite as X
from community import rookie_world as W
from community.models import LiteCareer, LiteSeason

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


def member(name):
    u = User.objects.create_user(username=name, password='pw12345!', email=f'{name}@example.com')
    pr, _ = Profile.objects.get_or_create(user=u)
    pr.nickname, pr.is_email_verified = name, True
    pr.save()
    return u


def new(name='라이트', role='batter', position='SS', style=None, seed=1):
    style = style or list(X.STYLES[role])[0]
    return X.create(member(name), name=name, role=role, position=position, style=style, region='서울', team='lg',
                    rng=random.Random(seed))


def autoplay(c, rng, max_steps=200):
    """끝까지 아무렇게나 골라 진행 — (시즌 수, 거친 결정 종류)."""
    seasons, seen = 0, set()
    for _ in range(max_steps):
        if c.retired_at:
            break
        pend = c.pending
        if pend['kind'] == 'plan':
            progs = rng.sample([p[0] for p in X.PROGRAMS[c.role]], 2)
            ev = pend.get('event')
            choice = rng.choice([k for k, _l, _h in X.EVENTS[ev]['choices']]) if ev else ''
            X.run_season(c, progs, rng.choice(list(X.INTENSITY)), choice, rng)
            seasons += 1
        elif pend['kind'] == 'review':
            X.next_season(c, rng)
        elif pend['kind'] == 'decision':
            what = pend['what']
            seen.add(what)
            opts = {'draft': (['sign'] if pend.get('offer') else ['develop']) + list(pend.get('abroad') or {}),
                    'military': ['sangmu', 'active'], 'posting': ['mlb', 'npb', 'stay'],
                    'fa': [o['key'] for o in pend.get('offers') or []], 'return': ['kbo', 'stay'],
                    'retire': ['continue'] if c.age < 37 else ['retire']}.get(what, ['retire'])
            X.decide(c, what, rng.choice(opts), rng)
            c.save()
    return seasons, seen


class EngineTests(TestCase):
    def test_create_starts_in_high_school(self):
        c = new()
        self.assertEqual((c.age, c.league, c.grade, c.pending['kind']), (16, 'hs', 1, 'plan'))
        self.assertIn(c.club, [s for r, s in W.schools('hs') if r == '서울'])
        self.assertTrue(X.POT_RANGE[0] <= c.potential <= X.POT_RANGE[1])
        self.assertTrue(30 < c.ovr < 55)
        with self.assertRaises(X.LiteError):
            X.create(c.user, name='둘', role='batter', position='SS', style='power', region='서울', team='lg')
        with self.assertRaises(X.LiteError):
            X.create(member('잘못'), name='x', role='pitcher', position='SS', style='fire', region='서울', team='lg')

    def test_full_career_ends_in_about_twenty_five_seasons(self):
        for seed, role, pos in ((3, 'batter', 'SS'), (4, 'pitcher', 'SP'), (5, 'pitcher', 'RP')):
            c = new(f'끝까지{seed}', role, pos, seed=seed)
            seasons, seen = autoplay(c, random.Random(seed))
            c.refresh_from_db()
            self.assertIsNotNone(c.retired_at)
            self.assertTrue(18 <= seasons <= 28, seasons)                       # 한 판 30분 남짓
            self.assertIn('draft', seen)
            self.assertEqual(LiteSeason.objects.filter(career=c).count(), c.year - 1)
            self.assertTrue(c.peak)

    def test_season_has_months_awards_and_growth(self):
        c = new('시즌', seed=7)
        rng = random.Random(7)
        s = X.run_season(c, ['contact', 'power'], 'normal', 'accept' if c.pending.get('event') else '', rng)
        self.assertEqual(len(s.months), 6)
        self.assertEqual(s.months[2]['label'], '황금사자기')
        self.assertEqual(set(s.deltas), set(c.stats))
        self.assertEqual(c.pending, {'kind': 'review', 'year': 1})
        self.assertEqual(c.age, 17)

    def test_training_and_intensity_matter(self):
        rng = random.Random(1)
        a, b = new('강훈련', seed=11), new('약훈련', seed=11)
        b.potential = a.potential
        b.stats = dict(a.stats)
        da = X.grow(a, ['power', 'contact'], 'hard', 0.8, 0.0, random.Random(2))
        db = X.grow(b, ['power', 'contact'], 'light', 0.8, 0.0, random.Random(2))
        self.assertGreater(da['power'], db['power'])
        self.assertLessEqual(max(a.stats.values()), max(X.stat_pot(a, k) for k in a.stats))
        old = new('노장', seed=12)
        old.age = 37
        d = X.grow(old, ['balance', 'contact'], 'normal', 1.0, 0.0, rng)
        self.assertLess(d['speed'], 0)                                            # 몸이 먼저 빠진다

    def test_draft_and_military_paths(self):
        rng = random.Random(9)
        c = new('드래프트', seed=9)
        c.age, c.grade = 19, 4
        c.stats = {k: 70.0 for k in c.stats}
        c.ovr = 70.0
        c.save()
        c.pending = X.next_step(c, rng)
        self.assertEqual(c.pending['what'], 'draft')
        self.assertTrue(c.pending['offer'])
        X.decide(c, 'draft', 'sign', rng)
        self.assertEqual((c.league, c.grade), ('kbo2', 0))
        c.age = 28
        c.flags = dict(c.flags, served=False, exempt=False)
        step = X.next_step(c, rng)
        self.assertEqual((step['what'], step['forced']), ('military', True))
        c.pending = step
        X.decide(c, 'military', 'sangmu', rng)
        self.assertEqual(c.club, '국군체육부대(상무)')
        X.army_after_season(c)
        X.army_after_season(c)
        self.assertTrue(c.flags['served'])
        self.assertNotEqual(c.club, '국군체육부대(상무)')
        with self.assertRaises(X.LiteError):
            X.decide(c, 'military', 'later', rng)                                 # 결정할 차례가 아니다

    def test_active_service_skips_two_years(self):
        rng = random.Random(4)
        c = new('현역', seed=4)
        c.league, c.club, c.age, c.grade = 'kbo1', 'lg', 24, 0
        c.save()
        c.pending = {'kind': 'decision', 'what': 'military', 'forced': False}
        year = c.year
        X.decide(c, 'military', 'active', rng)
        self.assertEqual((c.year, c.age), (year + 2, 26))
        self.assertTrue(c.flags['served'])
        self.assertEqual(LiteSeason.objects.filter(career=c, duty='현역 복무').count(), 2)

    def test_hall_orders_and_hides_admin(self):
        a = new('전설', seed=1)
        b = new('평범', seed=2)
        boss = X.create(member('admin'), name='운영', role='batter', position='SS', style='power', region='서울',
                        team='lg', rng=random.Random(3))
        for c, mvp in ((a, 2), (b, 0), (boss, 9)):
            LiteSeason.objects.create(career=c, year=1, age=25, league='kbo1', club='lg', games=144, war=8.0,
                                      awards=[{'kind': 'mvp', 'label': 'MVP'}] * mvp)
            X.retire(c)
            c.save()
        names = [r['c'].name for r in X.hall()]
        self.assertEqual(names[:2], ['전설', '평범'])
        self.assertNotIn('운영', names)
        self.assertEqual([r['c'].name for r in X.hall('mlb')], [])


class ViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_anonymous_and_public_pages(self):
        for url in ('/rookie/lite/', '/rookie/lite/hall/', '/rookie/lite/hall/?lg=kbo'):
            self.assertEqual(self.client.get(url, HTTP_USER_AGENT=PC).status_code, 200, url)
        self.assertContains(self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC), '로그인하고 시작')
        self.assertContains(self.client.get('/games/', HTTP_USER_AGENT=PC), '야구선수 키우기 라이트')

    def test_play_through_screens(self):
        u = member('화면라이트')
        c = self.client
        c.force_login(u)
        for ua in (PC, MOBILE):
            self.assertContains(c.get('/rookie/lite/', HTTP_USER_AGENT=ua), '고1, 야구부 입단')
        c.post('/rookie/lite/new/', {'role': 'pitcher', 'position_pitcher': 'SP', 'style_pitcher': 'fire',
                                     'region': '부산', 'team': 'lotte', 'name': '갈매기', 'number': '11'})
        career = LiteCareer.objects.get(user=u)
        self.assertEqual((career.role, career.position, career.style, career.team), ('pitcher', 'SP', 'fire', 'lotte'))
        for ua in (PC, MOBILE):
            r = c.get('/rookie/lite/', HTTP_USER_AGENT=ua)
            self.assertContains(r, '비시즌 훈련')
            self.assertContains(r, '시즌 시작')
        r = c.post('/rookie/lite/act/', {'action': 'play', 'program': ['velocity'], 'intensity': 'normal'}, follow=True)
        self.assertContains(r, '두 개')                                            # 프로그램은 두 개
        career.refresh_from_db()
        event = career.pending.get('event')
        data = {'action': 'play', 'program': ['velocity', 'control'], 'intensity': 'hard'}
        if event:
            data['event_choice'] = X.EVENTS[event]['choices'][0][0]
        c.post('/rookie/lite/act/', data)
        career.refresh_from_db()
        self.assertEqual(career.pending['kind'], 'review')
        for ua in (PC, MOBILE):
            r = c.get('/rookie/lite/', HTTP_USER_AGENT=ua)
            self.assertContains(r, '시즌 결산')
            self.assertContains(r, 'rl-month')
        c.post('/rookie/lite/act/', {'action': 'next'})
        career.refresh_from_db()
        self.assertEqual(career.pending['kind'], 'plan')
        self.assertEqual(c.get(f'/rookie/lite/c/{career.pk}/', HTTP_USER_AGENT=PC).status_code, 200)
        c.post('/rookie/lite/act/', {'action': 'quit'})
        career.refresh_from_db()
        self.assertIsNone(career.retired_at)                                       # 확인 없이 은퇴하지 않는다
        c.post('/rookie/lite/act/', {'action': 'quit', 'confirm': 'yes'})
        career.refresh_from_db()
        self.assertIsNotNone(career.retired_at)
        r = c.get('/rookie/lite/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '지난 커리어')
        self.assertContains(c.get('/rookie/lite/hall/', HTTP_USER_AGENT=PC), '갈매기')

    def test_decision_screens_render(self):
        u = member('갈림길')
        self.client.force_login(u)
        career = new('갈림', seed=5)
        career.user = u
        career.save()
        rng = random.Random(5)
        career.league, career.club, career.grade, career.age = 'kbo1', 'lg', 0, 30
        career.stats = {k: 74.0 for k in career.stats}
        career.ovr = 74.0
        career.flags = dict(career.flags, kbo_years=9, served=True)
        career.save()
        LiteSeason.objects.create(career=career, year=1, age=29, league='kbo1', club='lg', games=144, war=6.0)
        pendings = [{'kind': 'decision', 'what': 'posting'}, {'kind': 'decision', 'what': 'fa', 'offers': X.fa_offers(career, rng)},
                    {'kind': 'decision', 'what': 'retire'}, {'kind': 'decision', 'what': 'military', 'forced': False},
                    {'kind': 'decision', 'what': 'return'}, X.draft_offer(career, 'hs', rng)]
        for pend in pendings:
            career.pending = pend
            career.save()
            for ua in (PC, MOBILE):
                r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=ua)
                self.assertEqual(r.status_code, 200, pend)
                self.assertContains(r, 'rk-decide')
