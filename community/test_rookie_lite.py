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
        self.assertTrue(c.flags['exempt'])                                    # 올림픽 금메달 → 병역 특례
        self.assertGreater(state['mods']['injury'], 0)                       # 대가 — 부상 위험
        self.assertTrue(any('병역 특례' in p['title'] for p in state['press']))
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
            self.assertTrue(season.press)                                     # 프로 시즌엔 기사가 꼭 있다
            self.assertTrue(all(c.name in p['title'] or p['tag'] for p in season.press))
            X.next_season(c, random.Random(4))
            while c.pending['kind'] == 'decision':
                pend = c.pending
                ch = X.MEET_CHOICES[pend['about']](c)[0][0] if pend['what'] == 'meeting' else \
                    {'military': 'sangmu', 'retire': 'continue'}.get(pend['what'], 'stay')
                X.decide(c, pend['what'], ch, random.Random(5))
                c.save()


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
