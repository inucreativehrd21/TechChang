"""야구선수 키우기 라이트(community/rookie_lite.py, 2026-10-18) — 한 판 30분 커리어 시뮬레이터."""
import io
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone
from unittest import mock

from common.models import Profile
from community import rookie_lite as X
from community import rookie_staff as S
from community import rookie_world as W
from community.models import LiteCareer, LiteSeason

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'
RIGHTS = '구단·대회 명칭과 로고의 권리는 각 권리자에게 있습니다.'


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
            ev = pend.get('event')
            choice = rng.choice([k for k, _l, _h in X.EVENTS[ev]['choices']]) if ev else ''
            X.run_season(c, X.pick_programs(c, rng), rng.choice(list(X.INTENSITY)), choice, rng,
                         intl={k: rng.choice(['go', 'skip']) for k in pend.get('intl') or []})
            seasons += 1
        elif pend['kind'] == 'review':
            X.next_season(c, rng)
        elif pend['kind'] == 'decision':
            what = pend['what']
            seen.add(what)
            if what == 'meeting':
                X.decide(c, what, rng.choice([k for k, *_ in X.MEET_CHOICES[pend['about']](c)]), rng)
                c.save()
                continue
            if what == 'moment':
                m = pend['moments'][pend.get('i', 0)]
                X.decide(c, what, rng.choice([x[0] for x in m['choices']]), rng)
                c.save()
                continue
            opts = {'draft': (['sign'] if pend.get('offer') else ['develop']) + list(pend.get('abroad') or {}),
                    'military': ['sangmu', 'active'], 'posting': ['mlb', 'npb', 'stay'],
                    'fa': [o['key'] for o in pend.get('offers') or []],
                    'return': [o['key'] for o in pend.get('offers') or []] + ['stay'],
                    'awaken': ['try', 'skip'],
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

    def test_pick_home_high_school(self):
        c = X.create(member('학교고름'), name='학교', role='batter', position='SS', style='contact', region='부산',
                     team='lotte', school='경남고', rng=random.Random(2))
        self.assertEqual((c.league, c.club), ('hs', '경남고'))
        with self.assertRaises(X.LiteError):                                   # 고향 밖 학교는 못 고른다
            X.create(member('남의동네'), name='남', role='batter', position='SS', style='contact', region='부산',
                     team='lotte', school='덕수고', rng=random.Random(2))
        # 고교 야구부가 없는 울산은 맞닿은 지역(경북·경남·부산) 학교에서
        near = {r for r, _s in X.school_choices('울산')}
        self.assertTrue(near and near <= {'경북', '경남', '부산'})
        u = X.create(member('울산'), name='울산', role='batter', position='SS', style='contact', region='울산',
                     team='lotte', rng=random.Random(3))
        self.assertIn(u.club, [s for _r, s in X.school_choices('울산')])

    def test_powerhouse_is_harder_to_start(self):
        c = new('강호', seed=4)
        c.club = '덕수고'
        self.assertEqual(X.duty_level(c), W.level('hs') + X.HS_COMPETE)       # 강호는 주전 경쟁이 세다
        c.club = '경기고'
        self.assertEqual(X.duty_level(c), W.level('hs'))
        c.league = 'kbo1'
        c.club = 'lg'
        self.assertEqual(X.duty_level(c), W.level('kbo1'))
        # 스카우트 노출: 강호 주전은 +, 강호 벤치는 묻혀서 −, 일반 고교는 0
        c.league, c.club = 'hs', '덕수고'
        c.stats, c.ovr = {k: 80.0 for k in c.stats}, 80.0
        self.assertGreater(X.showcase(c, 'hs'), 0)
        c.stats, c.ovr = {k: 30.0 for k in c.stats}, 30.0
        self.assertLess(X.showcase(c, 'hs'), 0)
        c.club = '경기고'
        self.assertEqual(X.showcase(c, 'hs'), 0.0)

    def test_full_career_ends_in_about_twenty_five_seasons(self):
        for seed, role, pos in ((3, 'batter', 'SS'), (4, 'pitcher', 'SP'), (5, 'pitcher', 'RP')):
            c = new(f'끝까지{seed}', role, pos, seed=seed)
            seasons, seen = autoplay(c, random.Random(seed))
            c.refresh_from_db()
            self.assertIsNotNone(c.retired_at)
            self.assertTrue(15 <= seasons <= 28, seasons)                       # 한 판 30분 남짓(약하면 34세 무렵 방출로 일찍 끝난다)
            self.assertIn('draft', seen)
            self.assertEqual(LiteSeason.objects.filter(career=c).count(), c.year - 1)
            self.assertTrue(c.peak)

    def test_season_has_months_awards_and_growth(self):
        c = new('시즌', seed=7)
        rng = random.Random(7)
        s = X.run_season(c, ['contact', 'power'], 'normal', 'accept' if c.pending.get('event') else '', rng)
        self.assertEqual(len(s.months), 6)
        self.assertEqual(s.months[2]['label'], '황금사자기')
        self.assertEqual(set(s.deltas) - {'_why'}, set(c.stats))
        self.assertEqual(set(s.deltas['_why']), set(c.stats))                  # 능력치마다 바뀐 이유
        if c.pending.get('what') == 'moment':                                  # 고교 대회 결승 — 승부하고 넘어간다
            X.decide(c, 'moment', c.pending['moments'][0]['choices'][0][0], rng)
            self.assertEqual(len(c.pending['moments']), 1)
        self.assertEqual((c.pending['kind'], c.pending['year']), ('review', 1))
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


def pro(name='프로', seed=1, league='kbo1', ovr=70.0, age=24):
    c = new(name, seed=seed)
    c.league, c.club, c.grade, c.age = league, 'lg', 0, age
    c.stats = {k: ovr for k in c.stats}
    c.ovr = ovr
    c.peak = league
    c.flags = dict(c.flags, start=2026, trust=50)
    c.save()
    return c


class GameRulesTests(TestCase):
    """2026-10-18 사용자 요청 묶음 — 훈련 가드레일, 감독 면담, 시즌 중 승격·강등, 기사, 국가대표."""

    def test_training_guardrail(self):
        c = new('가드레일', seed=3)
        c.flags = dict(c.flags, train_log=[['contact', 'power'], ['eye', 'power']])
        rules = X.train_rules(c)
        self.assertEqual(rules, {'locked': ['power'], 'banned': ['eye', 'power']})
        with self.assertRaises(X.LiteError):                    # 두 비시즌 연속 웨이트 → 세 번째는 잠김
            X.check_programs(c, ['power', 'speed'])
        c.flags['train_log'] = [['contact', 'eye']]
        with self.assertRaises(X.LiteError):                    # 지난 비시즌과 같은 조합
            X.check_programs(c, ['eye', 'contact'])
        self.assertEqual(X.check_programs(c, ['eye', 'speed']), ['eye', 'speed'])
        rng = random.Random(1)
        for _ in range(50):
            p = X.pick_programs(c, rng)
            self.assertNotEqual(p, ['contact', 'eye'])
        c.flags['train_log'] = []
        c.save()
        X.run_season(c, ['contact', 'power'], 'normal', 'accept' if c.pending.get('event') else '', rng)
        self.assertEqual(c.flags['train_log'], [['contact', 'power']])

    def test_trust_moves_playing_time(self):
        c = pro('신뢰', seed=2)
        base = X.duty_level(c)
        c.flags['trust'] = 90
        self.assertLess(X.duty_level(c), base)
        c.flags['trust'] = 10
        self.assertGreater(X.duty_level(c), base)

    def test_josa(self):
        self.assertEqual(X.josa('KBO리그', '으로/로'), '로')
        self.assertEqual(X.josa('NPB 2군', '으로/로'), '으로')
        self.assertEqual(X.josa('KBO 육성군', '으로/로'), '으로')
        self.assertEqual(X.josa('일본프로야구(NPB)', '으로/로'), '로')
        self.assertEqual(X.josa('서울', '으로/로'), '로')
        self.assertEqual(X.josa('LG 트윈스', '와/과'), '와')
        self.assertEqual(X.josa('두산', '와/과'), '과')

    def test_midseason_callup_meeting(self):
        rng = random.Random(5)
        c = pro('콜업', seed=5, league='kbo2', ovr=66.0, age=22)
        c.pending = X.plan_step(c, rng)
        c.pending['event'] = None
        state = X.start_season(c, ['contact', 'power'], 'normal', '', {k: 'skip' for k in c.pending['intl']}, rng)
        t = X._sum_chunks(state['splits'][0]['chunks'])
        m = X._meeting(c, 'promote', 'mid', t, 50, rng, to='kbo1')
        c.pending = dict(m, half=state)
        c.save()
        view = X.decision_view(c)
        self.assertEqual(view['what'], 'meeting')
        self.assertIn('부진', view['text'])
        self.assertTrue(view['rival']['name'])
        text = X.decide(c, 'meeting', 'accept', rng)
        self.assertIn('올라갔어요', text)
        self.assertEqual(c.league, 'kbo1')
        s = c.seasons.get(year=1)
        self.assertEqual([x['league'] for x in s.splits], ['kbo2', 'kbo1'])
        self.assertTrue(any(m['moved'] and m['move_kind'] == 'up' for m in s.months))
        self.assertEqual(c.pending['kind'], 'review')
        self.assertTrue(any('콜업' in p['tag'] for p in s.press))

    def test_stubborn_backfires_or_sticks(self):
        rng = random.Random(6)
        c = pro('고집', seed=6, league='kbo2', ovr=60.0)
        c.pending = X._meeting(c, 'promote', 'end', {}, 100, rng, to='kbo1')
        with mock.patch.object(X, '_sticks', return_value=False):
            text = X.decide(c, 'meeting', 'demand', rng)
        self.assertIn('실망', text)
        self.assertEqual(c.league, 'kbo2')                                    # 콜업 취소
        self.assertEqual(X.trust(c), 38)
        self.assertEqual(c.flags['doghouse'], 1)
        self.assertTrue(any(p['tag'] == '[단독]' for p in c.flags['press']))  # 기사가 새어 나갔다
        c2 = pro('배짱', seed=7, league='kbo2', ovr=60.0)
        c2.pending = X._meeting(c2, 'promote', 'end', {}, 100, rng, to='kbo1')
        with mock.patch.object(X, '_sticks', return_value=True):
            X.decide(c2, 'meeting', 'demand', rng)
        self.assertEqual(c2.league, 'kbo1')
        self.assertLess(X.trust(c2), 50)

    def test_season_end_move_goes_through_manager(self):
        rng = random.Random(8)
        c = pro('면담', seed=8, league='kbo2', ovr=70.0)
        c.flags['move'] = {'kind': 'promote', 'to': 'kbo1'}
        c.save()
        step = X.next_step(c, rng)
        self.assertEqual((step['what'], step['about'], step['phase']), ('meeting', 'promote', 'end'))
        c.pending = step
        X.decide(c, 'meeting', 'accept', rng)
        self.assertEqual(c.league, 'kbo1')
        self.assertNotEqual(c.pending.get('what'), 'meeting')
        self.assertGreater(X.trust(c), 50)

    def test_national_team_calendar_and_exemption(self):
        c = pro('국대', seed=9, ovr=72.0, age=24)                          # 2026년 1번째 시즌 → WBC·아시안게임
        self.assertEqual(set(X.intl_this_year(c)), {'wbc', 'asian'})
        self.assertEqual(set(X.intl_offers(c)), {'wbc', 'asian'})
        c.year = 2                                                            # 2027 → 프리미어12
        self.assertEqual(X.intl_this_year(c), ['premier12'])
        c.year = 3                                                            # 2028 → 올림픽
        self.assertIn('olympics', X.intl_this_year(c))
        gold = {'key': 'olympics', 'name': '올림픽', 'tier': 'gold', 'result': '금메달', 'line': '.400 2홈런'}
        state = {'intl': [], 'press': [], 'news': [], 'mods': {'injury': 0.0}}
        with mock.patch.object(X, 'play_intl', return_value=gold):
            X._intl(c, 'olympics', state, random.Random(1))
        self.assertTrue(state['intl'][0]['final'])                           # 결승 진출 — 메달 색은 결정적 순간에서
        self.assertFalse(c.flags.get('exempt'))
        self.assertGreater(state['mods']['injury'], 0)                       # 대가 — 부상 위험
        season = LiteSeason(career=c, year=1, age=c.age, league='kbo1', club='lg', awards=[], press=[], news=[])
        X.resolve_moments(c, season, [{'kind': 'intl', 'key': 'olympics', 'won': True, 'ok': True, 'line': '', 'text': ''}],
                          random.Random(1))
        self.assertTrue(c.flags['exempt'])                                    # 올림픽 금메달 → 병역 특례
        self.assertIn({'kind': 'national', 'label': '올림픽 금메달'}, season.awards)
        self.assertTrue(any('병역 특례' in p['title'] for p in season.press))
        p12 = dict(gold, key='premier12', name='프리미어12', tier='champ', result='우승')
        with mock.patch.object(X, 'play_intl', return_value=p12):
            X._intl(c, 'premier12', state, random.Random(1))
        self.assertEqual(c.flags['tired']['train'], 0.9)                      # 11월 대회 — 다음 시즌 몸이 무겁다
        young = pro('어린국대', seed=10, ovr=67.0, age=30)
        self.assertNotIn('asian', X.intl_offers(young))                       # 아시안게임은 25세 이하(+와일드카드)

    def test_season_press_reads_like_headlines(self):
        c = pro('기자', seed=11, ovr=75.0)
        c.pending = X.plan_step(c, random.Random(2))
        c.pending['event'] = None
        c.save()
        season = None
        for _ in range(4):
            season = X.run_season(c, X.pick_programs(c, random.Random(_)), 'normal', '', random.Random(_),
                                  intl={k: 'skip' for k in c.pending.get('intl') or []})
            if season is None:
                X.decide(c, 'meeting', 'accept', random.Random(3))
                season = c.seasons.order_by('-year').first()
            while c.pending.get('what') == 'moment':
                X.decide(c, 'moment', c.pending['moments'][c.pending.get('i', 0)]['choices'][2][0], random.Random(6))
                season = c.seasons.order_by('-year').first()
            self.assertTrue(season.press)                                     # 프로 시즌엔 기사가 꼭 있다
            self.assertTrue(all(c.name in p['title'] or p['tag'] for p in season.press))
            X.next_season(c, random.Random(4))
            while c.pending['kind'] == 'decision':
                pend = c.pending
                ch = X.MEET_CHOICES[pend['about']](c)[0][0] if pend['what'] == 'meeting' else \
                    pend['moments'][pend.get('i', 0)]['choices'][0][0] if pend['what'] == 'moment' else \
                    {'military': 'sangmu', 'retire': 'continue', 'awaken': 'skip'}.get(pend['what'], 'stay')
                X.decide(c, pend['what'], ch, random.Random(5))
                c.save()


class MomentAndWhyTests(TestCase):
    """2026-10-18 사용자 요청 — 한국시리즈 같은 결승의 승부처 선택, 훈련 뒤 떨어진 능력치의 이유."""

    def _series(self, c, choice, ok):
        from community.models import LiteSeason
        season = LiteSeason.objects.create(career=c, year=c.year, age=c.age, league='kbo1', club='lg', games=144,
                                           awards=[], press=[], news=[])
        m = X.make_moment(c, 'series', '한국시리즈 7차전', '10월', random.Random(4))
        c.pending = {'kind': 'decision', 'what': 'moment', 'year': season.year, 'moments': [m], 'i': 0, 'done': []}
        c.save()
        with mock.patch.object(X, 'play_moment', return_value={'ok': ok, 'text': '끝내기 안타!' if ok else '헛스윙 삼진…',
                                                                 'line': '직구 — 노림수 적중, 안타', 'outcome': '1B'}):
            with mock.patch('random.Random.random', return_value=0.5):
                text = X.decide(c, 'moment', choice, random.Random(1))
        season.refresh_from_db()
        return text, season

    def test_moment_choices_and_series_result(self):
        c = pro('승부처', seed=21, ovr=70.0)
        m = X.make_moment(c, 'series', '한국시리즈 7차전', '10월', random.Random(2))
        self.assertEqual([x[0] for x in m['choices']], ['fast', 'break', 'short'])        # 직구·결정구 노리기·짧게
        self.assertIn('직구', m['opp']['scout'])
        p = X.make_moment(_pitcher('투수승부'), 'series', '한국시리즈 7차전', '10월',
                          random.Random(3))
        self.assertEqual([x[0] for x in p['choices']], ['fast', 'break', 'edge'])        # 구종 선택
        with self.assertRaises(X.LiteError):
            X.play_moment(c, m, 'bunt', random.Random(1))
        text, season = self._series(c, 'fast', ok=True)                                # 성공 → 우승(0.5 < 0.88)
        self.assertIn('우승', text)
        self.assertTrue(season.champion)
        self.assertIn({'kind': 'ring', 'label': '한국시리즈 우승'}, season.awards)
        self.assertEqual(c.pending['kind'], 'review')
        self.assertTrue(c.pending['moments'][0]['won'])
        c2 = pro('준우승', seed=23, ovr=70.0)
        text, season = self._series(c2, 'short', ok=False)                             # 실패 → 준우승(0.5 > 0.20)
        self.assertIn('준우승', text)
        self.assertFalse(season.champion)

    def test_reading_the_scouting_report_pays(self):
        rng = random.Random(5)
        c = pro('스카우팅', seed=24, ovr=68.0)
        good = bad = 0
        for _ in range(600):
            m = X.make_moment(c, 'series', '한국시리즈 7차전', '10월', rng)
            f = m['opp']['fast']
            if f in (75, 25):
                good += X.play_moment(c, m, 'fast' if f == 75 else 'break', rng)['ok']
                bad += X.play_moment(c, m, 'break' if f == 75 else 'fast', rng)['ok']
        self.assertGreater(good, bad * 1.3)                                          # 리포트대로 노리면 훨씬 낫다

    def test_drop_reasons_are_recorded(self):
        rng = random.Random(7)
        c = pro('노장', seed=25, ovr=70.0, age=35)
        c.pending = X.plan_step(c, rng)
        c.pending['event'] = None
        c.save()
        s = X.run_season(c, ['power', 'contact'], 'normal', '', rng, intl={k: 'skip' for k in c.pending.get('intl') or []})
        while s is None or c.pending.get('what') == 'moment':
            pend = c.pending
            if pend.get('what') == 'meeting':
                X.decide(c, 'meeting', 'accept', rng)
            else:
                X.decide(c, 'moment', pend['moments'][pend.get('i', 0)]['choices'][0][0], rng)
            s = c.seasons.order_by('-year').first()
        why = s.deltas['_why']
        labels = {lab for k in why for lab, _v in why[k]}
        self.assertIn('나이(노쇠)', labels)                                            # 서른다섯 — 노쇠
        self.assertIn('훈련 부작용', {lab for lab, _v in why['speed']})               # 웨이트 → 주루 −
        for k in c.stats:                                                            # 이유를 더하면 변화와 맞는다
            self.assertAlmostEqual(sum(v for _l, v in why[k]), s.deltas[k], delta=0.35)


class CapLedgerTests(TestCase):
    def test_capped_training_shows_in_ledger_and_plan(self):
        c = pro('천장', seed=31, ovr=70.0, age=29)
        c.stats['contact'] = X.stat_pot(c, 'contact')                                # 정확도는 잠재력 끝
        c.save()
        self.assertEqual(X.room_of(c, 'contact'), 0.0)
        d = X.grow(c, ['contact', 'eye'], 'normal', 1.0, 2.0, random.Random(3))
        why = dict(d['_why']['contact'])
        self.assertGreater(why['훈련'], 0)                                            # 훈련은 했고
        self.assertLessEqual(why['잠재력 한계'], -why['훈련'])                         # 끝에 닿아 그만큼 깎였다
        for k in c.stats:                                                            # 이유를 더하면 변화와 맞는다
            self.assertAlmostEqual(sum(v for _l, v in d['_why'][k]), d[k], delta=0.35)


class FourthBatchTests(TestCase):
    """2026-10-18 4차 — 해외 복귀 제안·커리어 하이·상점·인기·스캔들·억까·명예의 전당 투수/야수·코치 이름."""

    def test_abroad_gets_return_offer_every_season_and_can_leave(self):
        rng = random.Random(3)
        c = pro('해외파', seed=40, league='mlb_aa', ovr=55.0, age=24)
        c.club = 'nyy' if 'nyy' in W.PRO_TEAM else W.MLB_TEAMS[0][0]
        c.flags = dict(c.flags, contract={'years': 2, 'annual': 30000})
        c.save()
        for _ in range(2):                                                   # 시즌마다 다시 묻는다
            pend = X.next_step(c, rng, skip_meeting=True)
            self.assertEqual(pend['what'], 'return')
            c.pending = pend
            X.decide(c, 'return', 'stay', rng)
            self.assertEqual(c.league, 'mlb_aa')
        c.pending = X.next_step(c, rng, skip_meeting=True)
        self.assertEqual([o['key'] for o in c.pending['offers']], ['self'])     # 1군감이 아니면 스스로 유턴만
        text = X.decide(c, 'return', 'self', rng)
        self.assertEqual((c.league, c.club), ('kbo2', c.team))
        self.assertNotIn('contract', c.flags)                                 # 남은 해외 계약은 포기
        self.assertIn('포기', text)
        star = pro('유턴스타', seed=41, league='mlb', ovr=74.0, age=30)
        star.club = W.MLB_TEAMS[0][0]
        star.save()
        offers = X.return_offers(star, rng)
        self.assertEqual([o['key'] for o in offers], ['kbo', 'rich'])
        self.assertGreater(offers[1]['annual'], offers[0]['annual'])
        star.pending = {'kind': 'decision', 'what': 'return', 'offers': offers}
        X.decide(star, 'return', 'kbo', rng)
        self.assertEqual((star.league, star.club), ('kbo1', star.team))
        self.assertEqual(star.flags['contract']['annual'], offers[0]['annual'])
        old = pro('노장해외', seed=42, league='npb1', ovr=60.0, age=35)          # 남아도 은퇴는 물어본다
        old.club = W.NPB_TEAMS[0][0]
        old.pending = {'kind': 'decision', 'what': 'return', 'offers': X.return_offers(old, rng)}
        X.decide(old, 'return', 'stay', rng)
        self.assertEqual(old.pending['what'], 'retire')

    def test_career_high_prefers_the_highest_stage(self):
        c = pro('하이', seed=43)
        big = {'pa': 600, 'ab': 520, 'h': 180, 'hr': 40, 'bb': 70, 'so': 90, 'rbi': 120}
        LiteSeason.objects.create(career=c, year=5, age=26, league='kbo1', club='lg', games=144, totals=big, war=9.0)
        LiteSeason.objects.create(career=c, year=6, age=27, league='mlb', club=W.MLB_TEAMS[0][0], games=162,
                                  totals=dict(big, hr=22), war=3.1)
        LiteSeason.objects.create(career=c, year=7, age=28, league='mlb', club=W.MLB_TEAMS[0][0], games=162,
                                  totals={'pa': 40, 'ab': 36, 'h': 14, 'hr': 4}, war=1.4)      # 잠깐 뛴 몫은 빼고
        high = X.career_high(c)
        self.assertEqual((high['league'], high['war']), ('MLB', 3.1))

    def test_shop_gear_house_and_accessory(self):
        rng = random.Random(4)
        c = pro('쇼핑', seed=44, ovr=68.0)
        c.earnings = 600000                                                  # 60억 — 1군 물가(×4)
        c.pending = X.plan_step(c, rng)
        c.pending.update(event=None, intl=[], shop='chain')
        c.save()
        X.buy(c, 'bat', 'craft')
        with self.assertRaises(X.LiteError):
            X.buy(c, 'bat', 'pro')                                           # 더 좋은 걸 이미 샀다
        X.buy(c, 'guard', 'fit')
        X.buy(c, 'house', 'own')
        with self.assertRaises(X.LiteError):
            X.buy(c, 'house', 'rent')                                        # 내 집이 있다
        X.buy(c, 'acc', 'chain')
        self.assertEqual(X.cash(c), 600000 - 2000 * 4 - 1200 * 4 - 100000 * 4 - 20000)   # 값은 리그 물가를 곱한다
        self.assertEqual(X.fame(c), 4)
        with self.assertRaises(X.LiteError):
            X.buy(c, 'acc', 'watch')                                         # 들어오지 않은 물건
        with self.assertRaises(X.LiteError):
            X.buy(c, 'acc', 'chain')                                         # 이미 샀다(한 번이면 평생)
        poor = pro('가난', seed=45)
        poor.pending = {'kind': 'plan', 'event': None, 'intl': []}
        with self.assertRaises(X.LiteError):
            X.buy(poor, 'house', 'own')
        # 장비는 이번 시즌 경기에만 — 시즌을 시작하면 배트 보정이 붙는다
        state = X.start_season(c, X.pick_programs(c, rng), 'normal', '', {}, rng)
        self.assertEqual(c.flags['gear_on']['boost'], {'contact': 2.0, 'power': 2.0})
        self.assertEqual(X._game_stats(c)['contact'], float(c.stats['contact']) + 2.0)
        self.assertNotIn('gear', c.flags)
        self.assertTrue(state)

    def test_rent_is_charged_each_season_or_you_move_out(self):
        rng = random.Random(5)
        c = pro('월세', seed=46)
        c.flags = dict(c.flags, cash=20000, house='rent')
        c.pending = {'kind': 'plan', 'event': None, 'intl': []}
        state = X.start_season(c, X.pick_programs(c, rng), 'normal', '', {}, rng)
        self.assertEqual(X.cash(c), 8000)                                    # 1군 월세 = 3,000만원 × 물가 4
        self.assertIn('월세 1억 2,000만원을 냈어요', state['news'])
        c.flags['train_log'] = []
        state = X.start_season(c, X.pick_programs(c, rng), 'normal', '', {}, rng)
        self.assertEqual(c.flags['house'], 'dorm')                           # 못 내면 숙소로
        self.assertTrue(any('숙소' in n for n in state['news']))

    def test_fame_brings_ads_and_fades(self):
        flags = {'fame': 70.0}
        s = LiteSeason(league='kbo1', war=6.0, awards=[{'kind': 'mvp', 'label': 'MVP'}, {'kind': 'gg', 'label': 'GG'}])
        self.assertGreater(X.fame_after(flags, s), 75.0)                     # MVP·골든글러브면 크게 오른다
        quiet = LiteSeason(league='kbo1', war=0.0, awards=[])
        self.assertLess(X.fame_after(flags, quiet), 70.0)                    # 쉬면 잊힌다
        self.assertGreater(X.ad_income({'fame': 80}, 'mlb'), X.ad_income({'fame': 80}, 'kbo1'))
        self.assertEqual(X.ad_income({'fame': 10}, 'kbo1'), 0)
        self.assertEqual(X.ad_income({'fame': 90}, 'hs'), 0)

    def test_rival_scandal_opens_a_door(self):
        rng = random.Random(6)
        c = pro('기회', seed=47, league='kbo2', ovr=60.0)
        c.pending = {'kind': 'plan', 'event': None, 'intl': []}
        with mock.patch.object(X, 'SCANDAL_P', 1.0):
            state = X.start_season(c, X.pick_programs(c, rng), 'normal', '', {}, rng)
            m = X.break_meeting(c, state, rng)
        self.assertIsNotNone(m)
        self.assertEqual((m['about'], m['to']), ('promote', 'kbo1'))
        self.assertIn('scandal', m)
        self.assertTrue(any(m['rival']['name'] in p['title'] for p in state['press']))
        v = X.meeting_view(c, m)
        self.assertIn('긴급', v['title'])
        self.assertTrue(v['scandal'])

    def test_bad_luck_injury_has_a_silly_reason(self):
        rng = random.Random(7)
        c = pro('억까', seed=48)
        c.traits = ['iron']
        c.pending = {'kind': 'plan', 'event': None, 'intl': []}
        with mock.patch.object(X, 'BAD_LUCK_P', 1.0), mock.patch.dict(X.INTENSITY, {'light': ('가볍게', 0.6, -1.0)}):
            state = X.start_season(c, X.pick_programs(c, rng), 'light', '', {}, rng)
        self.assertTrue(any(n.startswith('억까') for n in state['news']))
        self.assertTrue(any(p['tag'] == '[황당]' for p in state['press']))
        self.assertGreater(state['out'][1], state['out'][0])

    def test_hall_splits_pitchers_and_batters(self):
        for name, role, pos in (('투수명전', 'pitcher', 'SP'), ('야수명전', 'batter', 'SS')):
            c = new(name, role=role, position=pos)
            LiteSeason.objects.create(career=c, year=1, age=24, league='kbo1', club='lg', games=144, war=3.0,
                                      totals={'outs': 540, 'w': 120, 'l': 101, 'er': 60, 'so': 150, 'g': 30, 'gs': 30}
                                      if role == 'pitcher' else {'pa': 600, 'ab': 540, 'h': 160, 'hr': 20})
            c.retired_at = timezone.now()
            c.save()
        self.assertEqual([r['c'].name for r in X.hall(role='pitcher')], ['투수명전'])
        self.assertEqual([r['c'].name for r in X.hall(role='batter')], ['야수명전'])
        self.assertEqual(X.hall(role='pitcher')[0]['line']['w'], 120)
        r = self.client.get('/rookie/lite/hall/?role=pitcher', HTTP_USER_AGENT=PC)
        self.assertContains(r, '평균자책점')
        self.assertContains(r, '<td>120</td><td>101</td>', html=False)
        self.assertNotContains(r, '야수명전')

    def test_coaches_differ_by_school_country_and_club(self):
        hs = S.staff('hs', '덕수고', 'lead')
        kbo = S.staff('kbo1', 'lg', 'lead')
        mlb = S.staff('mlb', W.MLB_TEAMS[0][0], 'lead')
        npb = S.staff('npb1', W.NPB_TEAMS[0][0], 'lead')
        self.assertEqual(hs[1], '야구부 감독')
        self.assertEqual(kbo[1], '감독')
        self.assertEqual(len({hs[0], kbo[0], mlb[0], npb[0]}), 4)
        self.assertIn(' ', mlb[0])                                           # 미국 이름
        self.assertEqual(S.staff('kbo1', 'lg', 'lead'), kbo)                 # 같은 팀이면 늘 같은 사람
        self.assertNotEqual(S.staff('kbo1', 'doosan', 'lead')[0], kbo[0])
        self.assertEqual(S.staff('kbo2', 'lg', 'coding', 'pitcher')[1], '투수 코치')
        self.assertEqual(S.staff('kbo1', 'lg', 'charter'), ('재원', '에이전트'))     # 팀 밖 사람은 그대로
        c = pro('코치', seed=49)
        self.assertEqual(X.who_is(c, 'lead'), kbo)


class AgingAndIntlTests(TestCase):
    """2026-10-18 5차 — 노쇠 곡선(서른 넘어 더 빨리, 훈련으로 못 메움)·베테랑 방출·국제대회 결승 상대."""

    def test_decline_is_steeper_after_thirty(self):
        c = pro('노쇠', seed=50, ovr=80.0, age=27)
        c.potential, c.traits = 80, []
        skill = {a: X.frac(c, 'contact', a) for a in (28, 33, 36, 39)}
        body = {a: X.frac(c, 'power', a) for a in (28, 33, 36, 39)}
        self.assertLess(skill[36], 0.80)                                     # 기술도 서른여섯이면 꽤 빠진다
        self.assertLess(body[36], skill[36])                                 # 몸이 먼저
        self.assertGreater((skill[33] - skill[36]) / 3, (skill[28] - skill[33]) / 5)   # 해마다 더 빨리 빠진다
        young = next(v for at, v in X.AGE_TRAIN if 25 <= at)
        old = next(v for at, v in X.AGE_TRAIN if 39 <= at)                 # 노쇠 2년 늦춤(2026-10-19) 뒤 기준
        self.assertLess(old, young / 4)                                      # 나이 들면 훈련으로 노쇠를 못 메운다

    def test_veteran_far_below_the_top_league_gets_released(self):
        rng = random.Random(51)
        c = pro('베테랑', seed=51, league='kbo2', ovr=50.0, age=38)
        c.flags = dict(c.flags, served=True)
        whats = [X.next_step(c, rng, skip_meeting=True).get('what') for _ in range(20)]
        self.assertGreater(whats.count('released'), 10)                       # 38세·1군보다 14 낮으면 대부분 방출
        young = pro('젊은2군', seed=52, league='kbo2', ovr=50.0, age=26)
        young.flags = dict(young.flags, served=True)
        self.assertNotIn('released', [X.next_step(young, rng, skip_meeting=True).get('what') for _ in range(10)])

    def test_asian_games_final_is_asian(self):
        rng = random.Random(53)
        names = {X.intl_rival('asian', rng).split(' ')[0] for _ in range(200)}
        self.assertLessEqual(names, {'일본', '대만', '중국'})
        wbc = {X.intl_rival('wbc', rng).split(' ')[0] for _ in range(400)}
        self.assertIn('도미니카', wbc)
        self.assertTrue(any(X.intl_rival('wbc', rng).split(' ')[1] in X.INTL_NAMES['latin'][0] for _ in range(200)))  # 중남미는 스페인어 이름


class CardImageAndHallFilterTests(TestCase):
    """2026-10-18 5차 — 은퇴 카드 이미지(PNG·링크 미리보기), 카드 칸 고정, 명예의 전당 드롭다운."""

    def setUp(self):
        import tempfile
        self.media = tempfile.mkdtemp()
        cache.clear()

    def _retired(self, name='카드주인', role='pitcher', pos='SP'):
        c = new(name, role=role, position=pos)
        LiteSeason.objects.create(career=c, year=1, age=24, league='kbo1', club='lg', games=144, war=5.0,
                                  totals={'outs': 540, 'w': 120, 'l': 101, 'er': 60, 'so': 1500, 'g': 30, 'gs': 30}
                                  if role == 'pitcher' else {'pa': 600, 'ab': 540, 'h': 1600, 'hr': 20},
                                  awards=[{'kind': 'gg', 'label': '골든글러브 투수'}])
        c.retired_at = timezone.now()
        c.pending = {'kind': 'retired', 'why': ''}
        c.save()
        return c

    def test_card_has_fixed_cells_and_image_links(self):
        c = self._retired()
        r = self.client.get(f'/rookie/lite/c/{c.pk}/card/', HTTP_USER_AGENT=PC)
        self.assertContains(r, 'rl-rc-honors')
        self.assertContains(r, 'rl-rc-jersey')                                # 유니폼 등판
        self.assertContains(r, 'is-zero')                                     # 0인 칸도 그대로(줄이 맞게)
        self.assertContains(r, '1,500')                                       # 천 단위 쉼표
        self.assertContains(r, f'/rookie/lite/c/{c.pk}/card.png')
        self.assertContains(r, f'/rookie/lite/c/{c.pk}/og.png')               # 링크 미리보기

    def test_png_is_rendered_once_and_cached(self):
        from django.test import override_settings
        from community.views import rookie_lite_views as LV
        c = self._retired('이미지')
        calls = []

        def fake(html, size, out):
            calls.append((size, 'rl-rcard' in html))
            import os
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, 'wb').write(b'PNG-fake')
        with override_settings(MEDIA_ROOT=self.media), mock.patch.object(LV, 'render_png', fake):
            for _ in range(2):
                r = self.client.get(f'/rookie/lite/c/{c.pk}/card.png', HTTP_USER_AGENT=PC)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r['Content-Type'], 'image/png')
            r = self.client.get(f'/rookie/lite/c/{c.pk}/og.png', HTTP_USER_AGENT=PC)
            self.assertEqual(r.status_code, 200)
            r = self.client.get(f'/rookie/lite/c/{c.pk}/card.png?download=1', HTTP_USER_AGENT=PC)
            self.assertIn('attachment', r['Content-Disposition'])
        self.assertEqual(calls, [((432, 540, 2.5), True), ((1200, 630, 1), True)])   # 한 번 찍으면 다시 안 찍는다

    def test_png_needs_a_retired_career_and_survives_render_failure(self):
        from django.test import override_settings
        from community.views import rookie_lite_views as LV
        live = new('현역')
        self.assertEqual(self.client.get(f'/rookie/lite/c/{live.pk}/card.png').status_code, 404)
        c = self._retired('실패')

        def boom(*a):
            raise RuntimeError('no chromium')
        with override_settings(MEDIA_ROOT=self.media), mock.patch.object(LV, 'render_png', boom):
            self.assertEqual(self.client.get(f'/rookie/lite/c/{c.pk}/card.png').status_code, 503)

    def test_hall_has_dropdown_filter(self):
        self._retired('투수카드')
        self._retired('타자카드', role='batter', pos='SS')
        r = self.client.get('/rookie/lite/hall/?role=batter', HTTP_USER_AGENT=MOBILE)
        self.assertContains(r, '<select name="role">', html=False)
        self.assertContains(r, '<option value="batter" selected>타자</option>', html=False)
        self.assertContains(r, '타자카드')
        self.assertNotContains(r, '투수카드')


class SixthBatchTests(TestCase):
    """2026-10-19 6차 — 결정적 순간 문구·흐름, 각성, 장비 부상 상한, 베스트 라인업, 게임 창."""

    def test_walkoff_hit_always_wins_and_middle_innings_explain_the_rest(self):
        m_bat = {'side': 'bat'}
        for ok in (True, False):                                            # 9회말 2사 — 내 결과가 곧 승패
            won, text = X.moment_outcome(m_bat, {'ok': ok, 'final': True, 'text': '끝내기 안타!' if ok else '헛스윙 삼진…'},
                                         random.Random(1))
            self.assertEqual(won, ok)
        seen = set()
        for seed in range(60):                                              # 8회 결승점 — 이어지는 경기는 뒷이야기로 맞춘다
            won, text = X.moment_outcome(m_bat, {'ok': True, 'final': False, 'text': '결승 적시타!'}, random.Random(seed))
            seen.add(won)
            self.assertIn(X.AFTER[('bat', True, won)], text)
        self.assertEqual(seen, {True, False})

    def test_moment_screen_plays_the_season_first(self):
        u = member('승부처')
        self.client.force_login(u)
        c = new('승부처선수', seed=60)
        c.user = u
        c.league, c.club, c.grade, c.age = 'kbo1', 'kia', 0, 27
        s = LiteSeason.objects.create(career=c, year=c.year, age=27, league='kbo1', club='kia', games=144, team_w=90, team_l=54,
                                      team_rank=1, team_of=10, months=[{'label': '4월', 'line': '-', 'w': 15, 'l': 9}])
        c.pending = {'kind': 'decision', 'what': 'moment', 'year': s.year, 'i': 0, 'done': [],
                     'moments': [X.make_moment(c, 'series', '한국시리즈 7차전', '10월', random.Random(2))]}
        c.save()
        r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC)
        html = r.content.decode()
        self.assertIn('data-rl-ticker', html)                                  # 정규시즌 전광판이 먼저
        self.assertLess(html.index('data-rl-ticker'), html.index('rl-moment-scene'))
        self.assertIn('바로 승부처로', html)

    def test_awakening_when_every_stat_is_capped(self):
        rng = random.Random(61)
        c = pro('각성', seed=61, ovr=60.0, age=24)
        c.potential = 58
        c.stats = {k: X.stat_pot(c, k) for k in c.stats}
        c.flags = dict(c.flags, served=True)
        pend = X.next_step(c, rng, skip_meeting=True)
        self.assertEqual(pend['what'], 'awaken')
        before, gain = X.stat_pot(c, 'contact'), X.awaken_gain(c)
        c.pending = dict(pend, odds=1.0)
        X.decide(c, 'awaken', 'try', rng)
        self.assertEqual(X.awakened(c), 1)
        self.assertEqual(X.stat_pot(c, 'contact'), before + gain)             # 한 칸 위 별의 잠재력까지
        self.assertTrue(c.flags['awaken_fx']['ok'])
        self.assertEqual(c.pending['kind'], 'plan')
        self.assertFalse(X.awaken_ready(c))                                   # 두 시즌 쉬었다가
        u = member('각성화면')
        c.user = u
        c.save()
        self.client.force_login(u)
        r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC)
        self.assertContains(r, 'rl-fx is-ok')                                 # 연출은 한 번
        self.assertContains(r, 'is-awaken')                                   # 보라색 별
        r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC)
        self.assertNotContains(r, 'rl-fx is-ok')
        fail = pro('각성실패', seed=62, ovr=60.0, age=31)
        fail.pending = {'kind': 'decision', 'what': 'awaken', 'odds': 0.0}
        X.decide(fail, 'awaken', 'try', rng)
        self.assertEqual(X.awakened(fail), 0)
        self.assertFalse(fail.flags['awaken_fx']['ok'])
        self.assertGreater(fail.flags['tired']['injury'], 0)

    def test_full_gear_never_makes_you_injury_proof(self):
        c = pro('완전무장', seed=63, ovr=70.0, age=24)
        c.traits = []
        c.flags = dict(c.flags, house='own', gear={'year': c.year, 'guard': 'fit', 'bat': 'craft'})
        self.assertAlmostEqual(X.gear_cut(c), 1 - X.GEAR_CUT_MAX)                 # 보호대·집을 다 갖춰도 12%까지만
        bare = pro('맨몸', seed=64, ovr=70.0, age=24)
        bare.traits = []
        self.assertAlmostEqual(X.injury_odds(c, 'normal'), X.injury_odds(bare, 'normal') * (1 - X.GEAR_CUT_MAX))
        c.traits = ['iron']
        self.assertGreaterEqual(X.injury_odds(c, 'light'), X.INJURY_FLOOR)          # 어떤 경우에도 2%는 남는다

    def test_best_lineup_fills_positions_once(self):
        def ret(name, role, pos, war):
            c = new(name, role=role, position=pos)
            LiteSeason.objects.create(career=c, year=1, age=24, league='kbo1', club='lg', games=144, war=war,
                                      totals={'pa': 600, 'ab': 540, 'h': 160} if role == 'batter' else {'outs': 540, 'w': 12})
            c.retired_at = timezone.now()
            c.save()
        ret('에이스', 'pitcher', 'SP', 9.0)
        ret('마무리', 'pitcher', 'RP', 3.0)
        ret('외야1', 'batter', 'OF', 8.0)
        ret('외야2', 'batter', 'OF', 7.0)
        ret('유격', 'batter', 'SS', 6.0)
        lineup = X.best_lineup(X.hall(limit=2000))
        spots = {s['slot']: (s['r']['c'].name if s['r'] else None) for s in lineup['field'] + lineup['bench']}
        self.assertEqual((spots['SP'], spots['RP'], spots['SS'], spots['CF'], spots['LF']), ('에이스', '마무리', '유격', '외야1', '외야2'))
        self.assertIsNone(spots['C'])
        r = self.client.get('/rookie/lite/hall/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '역대 베스트 라인업')
        self.assertNotContains(self.client.get('/rookie/lite/hall/?role=pitcher', HTTP_USER_AGENT=PC), '역대 베스트 라인업')

    def test_game_links_open_in_a_game_window_on_pc(self):
        r = self.client.get('/games/', HTTP_USER_AGENT=PC)
        self.assertContains(r, 'data-game-window')
        self.assertContains(r, "window.name === 'tc-game'")


class AwakenRedesignLiteTests(TestCase):
    """2026-10-19 각성 개편(라이트) — 별 다섯 칸, 성적이 좋으면 한계 전에도, 노쇠 2년 늦춤."""

    def test_stars_fill_empty_slots_up_to_five(self):
        rng = random.Random(70)
        c = pro('한칸씩', seed=70, ovr=60.0, age=24)
        c.potential = 55
        c.flags = dict(c.flags, served=True)
        totals = []
        for _ in range(6):
            c.flags.pop('awaken_next', None)
            c.stats = {k: X.stat_pot(c, k) for k in c.stats}
            if not X.awaken_ready(c):
                break
            c.pending = {'kind': 'decision', 'what': 'awaken', 'odds': 1.0}
            X.decide(c, 'awaken', 'try', rng)
            totals.append(X.base_stars(c) + X.awakened(c))
        self.assertEqual(totals, [2, 3, 4, 5])
        self.assertEqual(X.pot_eff(c), X.STAR_FLOOR[5])

    def test_form_opens_awakening_before_every_stat_is_capped(self):
        c = pro('폼좋음', seed=71, ovr=60.0, age=25)
        c.potential = 66
        c.flags = dict(c.flags, served=True)
        c.stats = {k: X.stat_pot(c, k) - 3.0 for k in c.stats}
        c.save()
        LiteSeason.objects.create(career=c, year=c.year - 1 if c.year > 1 else 1, age=24, league='kbo1', club='lg', games=144,
                                  totals={'pa': 600, 'ab': 520, 'h': 180, 'hr': 30, 'bb': 70, '2b': 35})
        self.assertTrue(X.awaken_ready(c))
        LiteSeason.objects.filter(career=c).update(totals={'pa': 600, 'ab': 560, 'h': 120, 'hr': 5, 'bb': 20})
        self.assertFalse(X.awaken_ready(c))                                  # 성적이 안 받쳐 주면 아직

    def test_decline_starts_two_years_later(self):
        c = pro('노쇠늦게', seed=72, ovr=80.0, age=27)
        c.traits = []
        self.assertEqual(X.frac(c, 'power', 30), X.frac(c, 'power', 28))       # 서른까지 꼭짓점
        self.assertGreater(X.frac(c, 'power', 31) - X.frac(c, 'power', 33), 0.04)   # 서른둘부터 본격적으로


class LaunchTests(TestCase):
    """1.0 출시 — 정치인·대통령 이름 금지, 명예의 전당은 출시 뒤 커리어부터."""

    def test_politician_names_are_refused(self):
        for bad in ('윤석열', '이재명 ', '박정희짱', 'Trump'):
            with self.assertRaises(X.LiteError):
                X.create(member(f'금지{len(bad)}{bad[:1]}'), name=bad, role='batter', position='SS', style='contact',
                         region='서울', team='lg', rng=random.Random(1))
        ok = X.create(member('보통이름'), name='김민석', role='batter', position='SS', style='contact', region='서울',
                      team='lg', rng=random.Random(1))
        self.assertEqual(ok.name, '김민석')

    def test_hall_counts_only_careers_after_launch(self):
        old = new('출시전')
        LiteSeason.objects.create(career=old, year=1, age=24, league='kbo1', club='lg', games=144, war=5.0)
        old.retired_at = timezone.now()
        old.save()
        self.assertEqual([r['c'].name for r in X.hall()], ['출시전'])         # 출시 뒤 커리어는 오른다
        LiteCareer.objects.filter(pk=old.pk).update(created_at=X.HALL_SINCE - timedelta(days=1))
        self.assertEqual([r['c'].name for r in X.hall()], [])
        self.assertEqual(self.client.get(f'/rookie/lite/c/{old.pk}/card/', HTTP_USER_AGENT=PC).status_code, 200)  # 카드는 남는다


class MomentFxTests(TestCase):
    """2026-10-19 결정적 순간 결과 연출 — 고른 뒤 한 번 보여 주는 장면(전광판 한 줄·점수·타구 길·우승/메달)."""

    def test_scene_follows_the_play(self):
        c = pro('연출', seed=80, ovr=70.0)
        m = X.make_moment(c, 'series', '한국시리즈 7차전', '10월', random.Random(2))
        m['sit'] = {'inning': '9회말', 'outs': 2, 'bases': [False, True, True], 'score': '3 : 4', 'need': 'hit'}
        hr = {'ok': True, 'text': '끝내기 홈런!', 'line': '직구 — 노림수 적중, 홈런', 'outcome': 'HR', 'final': True}
        fx = X.moment_fx(c, m, hr, {'won': True, 'result': '우승!'}, more=False)
        self.assertEqual((fx['head'], fx['path'], fx['before'], fx['after']), ('끝내기 홈런', 'hr', [3, 4], [6, 4]))
        self.assertEqual(fx['after_text'], '')                                 # 경기를 끝낸 승부 — 뒷이야기 없음
        fx = X.moment_fx(c, m, dict(hr, ok=False, outcome='SO'), {'won': False, 'result': '준우승'}, more=False)
        self.assertEqual((fx['head'], fx['path'], fx['after']), ('헛스윙 삼진', 'so', [3, 4]))
        p = _pitcher('연출투수')
        pm = X.make_moment(p, 'intl', '아시안게임 결승', '9월', random.Random(3), key='asian', opp_name='일본 다카하시 쇼타')
        pm['sit'] = {'inning': '7회말', 'outs': 1, 'bases': [True, False, True], 'score': '2 : 2', 'need': 'hold'}
        dp = {'ok': True, 'text': '병살타!', 'line': '슬라이더로 유인 — 범타', 'outcome': 'OUT', 'final': False}
        fx = X.moment_fx(p, pm, dp, {'won': True, 'result': '금메달'}, more=True)
        self.assertEqual((fx['head'], fx['path'], fx['medal']), ('병살타', 'ground', 'gold'))
        self.assertEqual(fx['colors'], list(X.KOREA_COLORS))                  # 국가대표는 태극 색
        self.assertEqual(fx['after_text'], X.AFTER[('pit', True, True)])       # 이어지는 승부 — 뒷이야기
        hit = dict(dp, ok=False, outcome='HR')
        self.assertEqual(X.moment_fx(p, pm, hit, {'won': False, 'result': '은메달'}, more=False)['after'], [2, 5])

    def test_scene_shows_once_after_the_choice(self):
        c = pro('연출화면', seed=81, ovr=70.0)
        season = LiteSeason.objects.create(career=c, year=c.year, age=c.age, league='kbo1', club='lg', games=144,
                                           awards=[], press=[], news=[])
        c.pending = {'kind': 'decision', 'what': 'moment', 'year': season.year, 'i': 0, 'done': [],
                     'moments': [X.make_moment(c, 'series', '한국시리즈 7차전', '10월', random.Random(4))]}
        c.save()
        with mock.patch.object(X, 'play_moment', return_value={'ok': True, 'text': '끝내기 안타!', 'final': True,
                                                                 'line': '직구 — 노림수 적중, 안타', 'outcome': '1B'}):
            X.decide(c, 'moment', 'fast', random.Random(1))
        c.save()
        self.assertEqual(c.flags['moment_fx']['result'], '한국시리즈 우승!')            # 어느 대회인지
        self.client.force_login(c.user)
        r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC)
        self.assertContains(r, 'data-rl-mfx')
        self.assertContains(r, '시즌 결산 보기')
        self.assertNotIn('moment_fx', LiteCareer.objects.get(pk=c.pk).flags)
        self.assertNotContains(self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC), 'data-rl-mfx')   # 한 번만


class FeedbackBatch11Tests(TestCase):
    """2026-10-19 사용자 요청 — 우승한 대회 이름, 타자 폼 교정 문구, 오늘의 랭킹, 수상 축하."""

    def test_result_names_the_tournament(self):
        self.assertEqual(X.moment_result_text({'kind': 'amateur', 'key': '봉황대기', 'stage': '봉황대기 결승', 'won': True}),
                         '봉황대기 우승!')
        self.assertEqual(X.moment_result_text({'kind': 'series', 'key': '', 'stage': '일본시리즈 7차전', 'won': False}),
                         '일본시리즈 준우승')
        self.assertEqual(X.moment_result_text({'kind': 'intl', 'key': 'asian', 'stage': '아시안게임 결승', 'won': True}),
                         '아시안게임 금메달')
        c = new('대회이름', seed=90)
        s = LiteSeason.objects.create(career=c, year=1, age=16, league='hs', club=c.club, games=30, champion=True,
                                      awards=[{'kind': 'ring', 'label': '청룡기 우승'}], months=[])
        c.pending = {'kind': 'review', 'year': 1}
        c.save()
        self.client.force_login(c.user)
        self.assertContains(self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC), '청룡기 우승!')   # 전광판도

    def test_batter_form_change_talks_about_the_swing(self):
        hit = type('Hit', (), {'random': lambda self: 0.0})()
        self.assertIn('타구가', X.apply_event(pro('폼타자', seed=91), 'form', 'accept', hit, {}))
        self.assertIn('공이', X.apply_event(_pitcher('폼투수'), 'form', 'accept', hit, {}))

    def _retired(self, name, seed, when):
        c = pro(name, seed=seed)
        LiteSeason.objects.create(career=c, year=1, age=24, league='kbo1', club='lg', games=144, war=4.0,
                                  awards=[{'kind': 'mvp', 'label': 'MVP'}])
        c.retired_at = when
        c.save()
        return c

    def test_today_ranking_counts_only_todays_retirements(self):
        start, _end = X.day_bounds()
        self._retired('오늘은퇴', 92, start + timedelta(minutes=5))
        self._retired('어제은퇴', 93, start - timedelta(hours=2))
        r = self.client.get('/rookie/lite/today/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '오늘의 랭킹')
        self.assertContains(r, '오늘은퇴')
        self.assertNotContains(r, '어제은퇴')
        r = self.client.get('/rookie/lite/today/?d=1', HTTP_USER_AGENT=PC)
        self.assertContains(r, '어제은퇴')
        self.assertNotContains(r, '오늘은퇴')
        self.assertContains(self.client.get('/rookie/lite/hall/', HTTP_USER_AGENT=PC), '오늘은퇴')   # 명예의 전당은 그대로

    def test_award_celebration_once_and_first_time_only_for_minor_awards(self):
        c = pro('수상축하', seed=94)
        s1 = LiteSeason.objects.create(career=c, year=1, age=24, league='kbo1', club='lg', games=144, war=6.0,
                                       totals={'pa': 600, 'ab': 520, 'h': 180, 'hr': 30},
                                       awards=[{'kind': 'mvp', 'label': 'MVP'}, {'kind': 'gg', 'label': '골든글러브 유격수'}])
        X.wrap_season(c, s1, random.Random(1))
        fx = c.flags['award_fx']
        self.assertEqual((fx['hero'], fx['count'], fx['others']), ('MVP', '첫 수상', ['골든글러브 유격수']))
        c.flags.pop('award_fx')
        s2 = LiteSeason.objects.create(career=c, year=2, age=25, league='kbo1', club='lg', games=144, war=4.0,
                                       totals={'pa': 600}, awards=[{'kind': 'gg', 'label': '골든글러브 유격수'}])
        X.wrap_season(c, s2, random.Random(1))
        self.assertNotIn('award_fx', c.flags)                                  # 두 번째 골든글러브는 조용히
        s3 = LiteSeason.objects.create(career=c, year=3, age=26, league='kbo1', club='lg', games=144, war=7.0,
                                       totals={'pa': 600}, awards=[{'kind': 'mvp', 'label': 'MVP'}])
        X.wrap_season(c, s3, random.Random(1))
        self.assertEqual(c.flags['award_fx']['count'], '통산 2번째')            # MVP 는 받을 때마다
        c.save()
        self.client.force_login(c.user)
        self.assertContains(self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC), 'rl-mfx is-award')
        self.assertNotContains(self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC), 'rl-mfx is-award')


class MoneyBalanceTests(TestCase):
    """2026-10-19 밸런스 2 — 장비 의존도 낮춤, 리그 물가, 세금, 돈 쓸 곳(관리팀·전지훈련·팬 이벤트·나눔·투자)."""

    def _shopper(self, name, seed, league='kbo1', cash=2000000):
        c = pro(name, seed=seed, league=league, ovr=60.0)
        c.flags = dict(c.flags, cash=cash)
        c.pending = {'kind': 'plan', 'event': None, 'intl': []}
        c.save()
        return c

    def test_prices_follow_the_league(self):
        futures, majors = self._shopper('퓨처스물가', 101, 'kbo2'), self._shopper('빅리그물가', 102, 'mlb')
        X.buy(futures, 'bat', 'craft')
        X.buy(majors, 'bat', 'craft')
        self.assertEqual(2000000 - X.cash(futures), round(2000 * 1.2))
        self.assertEqual(2000000 - X.cash(majors), 2000 * 40)                 # 메이저리그 장인 배트 8억
        self.assertLessEqual(X.GEAR_CUT_MAX, 0.12)

    def test_taxes_come_out_of_salary(self):
        self.assertEqual(X.income_tax(0), 0)
        self.assertAlmostEqual(X.income_tax(30000) / 30000, 0.31, places=2)     # 3억 — 실효세율 31%쯤
        self.assertGreater(X.income_tax(1000000) / 1000000, 0.43)              # 100억 — 45% 구간
        c = pro('세금', seed=103)
        s = LiteSeason.objects.create(career=c, year=c.year, age=c.age, league='kbo1', club='lg', games=144, war=3.0,
                                      salary=30000, totals={'pa': 600}, awards=[])
        before = X.cash(c)
        X.wrap_season(c, s, random.Random(1))
        s.refresh_from_db()
        self.assertTrue(any(n.startswith('세금 ') for n in s.news))
        self.assertLess(X.cash(c) - before, 30000)

    def test_care_staff_change_the_season(self):
        rng = random.Random(7)
        c = self._shopper('관리팀', 104)
        for code in X.CARE:
            X.buy(c, 'care', code)
        with self.assertRaises(X.LiteError):
            X.buy(c, 'care', 'trainer')                                       # 시즌에 한 번
        state = X.start_season(c, X.pick_programs(c, rng), 'normal', '', {}, rng)
        self.assertAlmostEqual(state['mods']['train'], X.CARE_TRAIN)
        self.assertEqual(state['mods']['age'], X.CARE_AGE)
        self.assertTrue(state['physio'])
        old = self._shopper('노쇠', 105)
        old.age = 36
        keep, plain = dict(old.stats), None
        X.grow(old, [], 'normal', 0.0, 0.0, random.Random(3), 1.0, X.CARE_AGE)
        cared = sum(old.stats.values()) - sum(keep.values())
        old.stats = dict(keep)
        X.grow(old, [], 'normal', 0.0, 0.0, random.Random(3), 1.0, 1.0)
        plain = sum(old.stats.values()) - sum(keep.values())
        self.assertGreater(cared, plain)                                      # 노쇠 관리팀 — 덜 빠진다

    def test_camp_fan_give_and_invest(self):
        c = self._shopper('돈쓰기', 106)
        k = 'contact'
        before = float(c.stats[k])
        X.buy(c, 'camp', k)
        self.assertAlmostEqual(float(c.stats[k]), min(X.stat_pot(c, k), before + X.CAMP[2]))
        with self.assertRaises(X.LiteError):
            X.buy(c, 'camp', 'power')                                         # 비시즌에 한 번
        fame0 = X.fame(c)
        X.buy(c, 'fan', '')
        X.buy(c, 'give', 'foundation')
        self.assertEqual(X.fame(c), fame0 + X.FAN[2] + X.GIVE['foundation'][2])
        self.assertTrue(any('재단' in p['title'] for p in c.flags['press']))   # 다음 시즌 기사
        with self.assertRaises(X.LiteError):
            X.buy(c, 'give', 'foundation')                                    # 평생 한 번
        have = X.cash(c)
        X.buy(c, 'invest', '')
        self.assertEqual(X.cash(c), have - int(have * X.INVEST_SHARE))
        s = LiteSeason.objects.create(career=c, year=c.year, age=c.age, league='kbo1', club='lg', games=144, war=2.0,
                                      totals={'pa': 600}, awards=[])
        X.wrap_season(c, s, random.Random(1))
        s.refresh_from_db()
        self.assertNotIn('invest', c.flags)
        self.assertTrue(any(n.startswith('지인 사업 투자') for n in s.news))

    def test_amateurs_cannot_use_the_new_services(self):
        c = new('고교생돈', seed=107)
        c.flags = dict(c.flags, cash=100000)
        c.pending = {'kind': 'plan', 'event': None, 'intl': []}
        with self.assertRaises(X.LiteError):
            X.buy(c, 'care', 'trainer')


def _pitcher(name):
    c = X.create(member(name), name=name, role='pitcher', position='RP', style='fire', region='서울', team='lg',
                 rng=random.Random(9))
    c.league, c.club, c.grade, c.age = 'kbo1', 'lg', 0, 26
    c.stats = {k: 70.0 for k in c.stats}
    c.ovr = 70.0
    c.save()
    return c


class ViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_anonymous_and_public_pages(self):
        for url in ('/rookie/lite/', '/rookie/lite/hall/', '/rookie/lite/hall/?lg=kbo'):
            self.assertEqual(self.client.get(url, HTTP_USER_AGENT=PC).status_code, 200, url)
        for ua in (PC, MOBILE):
            r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=ua)
            self.assertContains(r, '로그인하지 않아도 바로 할 수 있어요')               # 손님도 바로 만든다
            self.assertContains(r, '고1 신입으로 야구부에 들어가기')
            self.assertContains(r, RIGHTS)
            r = self.client.get('/games/', HTTP_USER_AGENT=ua)
            self.assertContains(r, 'gm-ball')                                          # 야구 두 판은 한 묶음
            self.assertContains(r, '라이트 판')
            self.assertContains(r, '로그인 없이 바로')
            r = self.client.get('/', HTTP_USER_AGENT=ua)
            self.assertContains(r, '야구선수 키우기, 문을 열었어요')                       # 홈 런칭 칸
            self.assertNotContains(r, '브라우저 게임')
        self.assertContains(self.client.get('/rookie/', HTTP_USER_AGENT=PC), RIGHTS)

    def test_guest_plays_then_claims_on_login(self):
        c = self.client
        c.post('/rookie/lite/new/', {'role': 'batter', 'position_batter': 'SS', 'style_batter': 'contact',
                                     'region': '서울', 'team': 'lg', 'name': '손님유격', 'number': '6'})
        career = LiteCareer.objects.get(name='손님유격')
        self.assertIsNone(career.user)
        self.assertTrue(career.guest)
        r = c.get('/rookie/lite/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '훈련 프로그램을')
        self.assertContains(r, 'data-rl-count')                                        # 0 / 2 세기
        self.assertContains(c.get(f'/rookie/lite/c/{career.pk}/', HTTP_USER_AGENT=PC), '이어서 하기')
        # 다른 손님(다른 세션)은 이 판을 움직이지 못하고, 커리어 페이지에서도 주인이 아니다
        other = Client()
        self.assertNotContains(other.get(f'/rookie/lite/c/{career.pk}/', HTTP_USER_AGENT=PC), '이어서 하기')
        other.post('/rookie/lite/act/', {'action': 'quit', 'confirm': 'yes'})
        career.refresh_from_db()
        self.assertIsNone(career.retired_at)
        # 두 번째 판은 만들지 않는다
        c.post('/rookie/lite/new/', {'role': 'batter', 'position_batter': 'CF', 'style_batter': 'power',
                                     'region': '부산', 'team': 'lotte', 'name': '두번째', 'number': '7'})
        self.assertFalse(LiteCareer.objects.filter(name='두번째').exists())
        # 은퇴한 손님 판은 명예의 전당에 오르지 않는다
        c.post('/rookie/lite/act/', {'action': 'quit', 'confirm': 'yes'})
        career.refresh_from_db()
        self.assertIsNotNone(career.retired_at)
        LiteSeason.objects.create(career=career, year=90, age=22, league='kbo1', club='lotte', games=144)   # 명예의 전당은 리그별 — KBO 시즌 하나
        self.assertNotIn('손님유격', [row['c'].name for row in X.hall()])
        # 로그인하면 계정으로 옮겨진다
        u = member('손님이었던')
        c.force_login(u)
        r = c.get('/rookie/lite/', HTTP_USER_AGENT=PC, follow=True)
        self.assertContains(r, '내 계정으로 옮겼어요')
        career.refresh_from_db()
        self.assertEqual((career.user, career.guest), (u, ''))
        self.assertIn('손님유격', [row['c'].name for row in X.hall()])

    def test_guest_cleanup_after_two_weeks(self):
        old = X.create(None, name='오래된손님', role='batter', position='SS', style='contact', region='서울', team='lg',
                       rng=random.Random(3), guest='g' * 24)
        fresh = X.create(None, name='새손님', role='batter', position='SS', style='contact', region='서울', team='lg',
                         rng=random.Random(4), guest='h' * 24)
        LiteCareer.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=15))
        call_command('rookie_daily', stdout=io.StringIO())
        self.assertFalse(LiteCareer.objects.filter(pk=old.pk).exists())
        self.assertTrue(LiteCareer.objects.filter(pk=fresh.pk).exists())

    def test_play_through_screens(self):
        u = member('화면라이트')
        c = self.client
        c.force_login(u)
        for ua in (PC, MOBILE):
            self.assertContains(c.get('/rookie/lite/', HTTP_USER_AGENT=ua), '고1 신입으로 야구부에 들어가기')
        r = c.get('/rookie/lite/', HTTP_USER_AGENT=PC)
        self.assertContains(r, 'data-rl-schools="부산"')                            # 지역마다 고교 묶음
        self.assertContains(r, 'value="경남고"')
        self.assertContains(r, 'rl-hard')
        c.post('/rookie/lite/new/', {'role': 'pitcher', 'position_pitcher': 'SP', 'style_pitcher': 'fire',
                                     'region': '부산', 'school': '부산고', 'team': 'lotte', 'name': '갈매기', 'number': '11'})
        career = LiteCareer.objects.get(user=u)
        self.assertEqual((career.role, career.position, career.style, career.team, career.club),
                         ('pitcher', 'SP', 'fire', 'lotte', '부산고'))
        for ua in (PC, MOBILE):
            r = c.get('/rookie/lite/', HTTP_USER_AGENT=ua)
            self.assertContains(r, '훈련 프로그램을 <em>두 개</em> 골라 주세요')
            self.assertContains(r, 'rk-sprite')                                    # 코치가 말한다
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
        while career.pending.get('what') == 'moment':
            for ua in (PC, MOBILE):
                self.assertContains(c.get('/rookie/lite/', HTTP_USER_AGENT=ua), 'rl-moment')
            m = career.pending['moments'][career.pending.get('i', 0)]
            c.post('/rookie/lite/act/', {'action': 'decide', 'what': 'moment', 'choice': m['choices'][0][0]})
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
        self.assertNotContains(c.get('/rookie/lite/hall/', HTTP_USER_AGENT=PC), '갈매기')   # 고교만 뛰었으면 리그 전당엔 없다
        LiteSeason.objects.create(career=career, year=90, age=22, league='kbo1', club='lotte', games=144)
        self.assertContains(c.get('/rookie/lite/hall/', HTTP_USER_AGENT=PC), '갈매기')
        self.assertNotContains(c.get('/rookie/lite/hall/?lg=mlb', HTTP_USER_AGENT=PC), '갈매기')

    def test_retire_card_and_archive(self):
        u = member('카드')
        c = self.client
        c.force_login(u)
        career = new('은퇴카드', seed=4)
        career.user = u
        career.save()
        self.assertRedirects(c.get(f'/rookie/lite/c/{career.pk}/card/'), f'/rookie/lite/c/{career.pk}/',
                             fetch_redirect_response=False)                  # 현역은 카드가 아직 없다
        r = c.post('/rookie/lite/act/', {'action': 'quit', 'confirm': 'yes'})
        self.assertRedirects(r, f'/rookie/lite/c/{career.pk}/card/?new=1', fetch_redirect_response=False)
        for ua in (PC, MOBILE):
            r = c.get(f'/rookie/lite/c/{career.pk}/card/?new=1', HTTP_USER_AGENT=ua)
            self.assertContains(r, 'rl-rcard')
            self.assertContains(r, '은퇴카드')
            self.assertContains(r, '[은퇴]')
            self.assertContains(r, '새 선수 시작하기')
            self.assertContains(r, RIGHTS)
            r = c.get('/rookie/lite/cards/', HTTP_USER_AGENT=ua)
            self.assertContains(r, f'/rookie/lite/c/{career.pk}/card/')
            self.assertContains(r, 'noindex')
        other = self.client_class()
        self.assertNotContains(other.get(f'/rookie/lite/c/{career.pk}/card/?new=1', HTTP_USER_AGENT=PC),
                               '새 선수 시작하기')                              # 남의 카드는 구경만
        self.assertContains(other.get('/rookie/lite/cards/', HTTP_USER_AGENT=PC), '로그인하면 카드가 계정에 보관돼요')

    def test_plan_and_meeting_screens(self):
        u = member('개편화면')
        self.client.force_login(u)
        c = pro('화면', seed=12, ovr=72.0)
        c.user = u
        c.flags['train_log'] = [['contact', 'power'], ['eye', 'power']]
        c.flags['press'] = [X.press('[오피셜]', '화면, 연봉 계약')]
        c.pending = X.plan_step(c, random.Random(1))
        c.save()
        for ua in (PC, MOBILE):
            r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=ua)
            self.assertContains(r, 'rl-hud')
            self.assertContains(r, 'is-locked')                                   # 두 비시즌 연속 웨이트
            self.assertContains(r, '화면, 연봉 계약')                              # 오프시즌 기사
            self.assertContains(r, 'intl_wbc')                                      # 국가대표 소집
            self.assertContains(r, 'rl-cta')                                        # 할 일 버튼은 아래에 붙는다
        r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=MOBILE)              # 모바일: 위쪽 선수 요약, 접는 연표
        self.assertContains(r, 'rl-mcard')
        self.assertNotContains(r, 'rl-side')
        r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=PC)
        self.assertContains(r, 'rl-side')
        self.assertNotContains(r, 'rl-mcard')
        r = self.client.post('/rookie/lite/act/', {'action': 'play', 'program': ['power', 'speed'], 'intensity': 'normal'},
                             follow=True)
        self.assertContains(r, '두 비시즌 연속')
        c.pending = X._meeting(c, 'role_down', 'end', {}, 144, random.Random(2),
                               new_role=('bench', 0, '백업(대타·대주자)'), old_role=('lower', 6, '하위타선 주전 · 6번'))
        c.save()
        for ua in (PC, MOBILE):
            r = self.client.get('/rookie/lite/', HTTP_USER_AGENT=ua)
            self.assertContains(r, 'rl-room')
            self.assertContains(r, '보직 변경 통보')
            self.assertContains(r, '제 자리를 지키고 싶어요')

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
