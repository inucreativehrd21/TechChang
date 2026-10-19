"""야구선수 키우기(community/rookie.py, 2026-10-16)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from common.models import DailyCheckIn, Profile
from community import rookie as R
from community.models import Answer, Category, Comment, Question, RookiePlayer

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


GATE_OK = {'stay_need': 14, 'stay_left': 0, 'mission': {'text': '', 'now': '', 'ok': True}, 'ok': True}


class FixedRng:
    """흔들림 없는 훈련·심사 — uniform 은 가운데, 대성공 없음, gauss 는 정해 준 값."""
    def __init__(self, gauss=0.0):
        self._g = gauss

    def random(self):
        return 0.99

    def uniform(self, a, b):
        return (a + b) / 2

    def gauss(self, mu, sigma):
        return self._g

    def choice(self, seq):
        return seq[0]


def adult(p, **over):
    """프로 성인 선수로(나이 한계·잠재력·특성이 성장 수식을 흔들지 않게) — 저장까지."""
    fields = dict(age=25, potential=99, traits=[], traits_seen=[], grade=0, grade_since=None, pending={})
    fields.update(over)
    for k, v in fields.items():
        setattr(p, k, v)
    p.save()
    return p


def member(name='member1', nick='회원선수'):
    u = User.objects.create_user(username=name, password='pw12345!', email=f'{name}@example.com')
    p, _ = Profile.objects.get_or_create(user=u)
    p.nickname, p.is_email_verified = nick, True
    p.save()
    return u


class ConvergenceTests(TestCase):
    """설계 약속 — '초반엔 빠르게, 갈수록 꾸준해야 유지(수렴)'. 숫자를 바꾸면 rookie.py 머리말도 고칠 것."""

    def test_growth_is_fast_early_and_slow_late(self):
        self.assertGreater(R.gain(25), R.gain(50))
        self.assertGreater(R.gain(50), R.gain(80))
        self.assertGreater(R.gain(25) / R.gain(80), 8)
        curve, _ = R.simulate(20, 3)
        self.assertGreaterEqual(curve[0], 37)                 # 출석만 해도 첫날 25 → 37+(OVR 다섯 능력 평균, 2026-10-18)

    def test_each_activity_level_converges(self):
        light = R.simulate(20, 150)[0]
        steady = R.simulate(30, 150)[0]
        full = R.simulate(R.DAILY_MAX, 150)[0]
        for curve in (light, steady, full):
            self.assertLess(abs(curve[-1] - curve[-30]), 0.6)  # 마지막 한 달은 거의 안 움직인다 = 수렴
        self.assertTrue(60 <= light[-1] < 65)                  # 출석만 → 2군 상위
        self.assertTrue(65 <= steady[-1] < 72)                 # 출석+칼럼 1편 → 1군
        self.assertTrue(78 <= full[-1] < 83)                   # 매일 한도 → 에이스
        self.assertLessEqual(next(i for i, v in enumerate(full) if v >= 45) + 1, 3)   # 2군 문턱 사흘

    def test_rest_drops_hard(self):
        _, stats = R.simulate(R.DAILY_MAX, 150)
        week = R.simulate(0, 7, start=stats, idle=True)[0][-1]
        two = R.simulate(0, 14, start=stats, idle=True)[0][-1]
        self.assertLess(week, 61)                               # 에이스도 일주일 쉬면 1군 강등선
        self.assertLess(two, 40)                                # 2주면 육성군 강등선
        self.assertEqual(R.decay_rate(0), R.decay_rate(1))
        self.assertEqual(R.decay_rate(30), R.MAX_DECAY)


class DecayWhyTests(TestCase):
    """훈련 뒤 밤사이 능력치가 빠진 이유(2026-10-18) — 유지비·쉰 날 감각 저하·노쇠로 나눠 남긴다."""

    def test_overnight_drop_is_explained(self):
        u = member('정산이유')
        p = adult(R.create(u, name='이유', role='batter', team='lg', number=7, focus='contact', region='서울'))
        p.stats = {k: 70.0 for k in p.stats}
        p.age = 33
        today = timezone.localdate()
        p.last_active = today - timedelta(days=4)
        p.settled_through = today - timedelta(days=4)
        p.save()
        R._decay(p, today)
        rows = {r['key']: r for r in R.stat_rows(p)}
        drop = rows['speed']['drop']
        self.assertIsNotNone(drop)
        labels = [x['label'] for x in drop['parts']]
        self.assertIn('유지비', labels)
        self.assertIn('쉰 날 감각 저하', labels)
        self.assertIn('나이(노쇠)', labels)                                          # 주루는 몸 능력 — 서른셋이면 노쇠
        self.assertNotIn('나이(노쇠)', [x['label'] for x in rows['eye']['drop']['parts']])   # 선구안은 노쇠가 없다
        self.assertEqual(drop['when'], '지난 3일')
        self.assertEqual(rows['contact']['role'], R.STAT_ROLE['contact'])


class EngineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.u = member()
        self.p = adult(R.create(self.u, name='김테크', role='pitcher', team='lg', number=17, focus='control',
                                region='서울'))

    def refresh(self):
        self.p.refresh_from_db()
        return self.p

    def test_create_starts_at_floor_with_welcome_tp(self):
        p = R.create(member('새내기'), name='리틀', role='pitcher', team='kia', focus='control', region='부산')
        self.assertEqual((p.tp, p.league, p.club, p.age, p.grade, p.focus),
                         (R.WELCOME_TP, 'little', '부산 리틀야구단', 12, 6, 'control'))
        self.assertEqual(p.pending, {'kind': 'apply', 'to': 'ms', 'choice': ''})        # 초6 = 졸업 학년 → 중학교 지원
        p = self.p
        self.assertEqual(set(p.stats), {'velocity', 'control', 'breaking', 'stamina', 'mental'})
        self.assertEqual(p.ovr, 25.0)
        self.assertEqual(p.logs.get().kind, 'start')
        with self.assertRaises(R.GameError):
            R.create(member('m2'), name='x', role='pitcher', team='mlb', region='서울')      # 희망 구단은 KBO 만
        with self.assertRaises(R.GameError):
            R.create(member('m3'), name='x', role='pitcher', team='lg', region='화성')
        with self.assertRaises(R.GameError):
            R.create(self.u, name='둘째', role='batter', team='lg', region='서울')           # 현역은 한 명

    def test_awards_have_daily_caps_and_no_repeats(self):
        self.assertIsNone(R.award(member('nobody'), 'column', '1'))        # 선수가 없으면 없다
        got = [R.award(self.u, 'column', str(i)) for i in range(1, 5)]
        self.assertEqual([g and g['count'] for g in got], [1, 2, 3, None])   # 하루 3편
        self.assertIsNone(R.award(self.u, 'column', '1'))                  # 같은 칼럼은 한 번
        self.assertEqual(self.refresh().tp, R.WELCOME_TP + 30)

    def test_signals_pay_for_checkin_comment_answer(self):
        cat, _ = Category.objects.get_or_create(name='자유')
        q = Question.objects.create(author=self.u, category=cat, subject='질문', content='본문', create_date=timezone.now())
        DailyCheckIn.objects.create(user=self.u)
        Comment.objects.create(author=self.u, question=q, content='짧음', create_date=timezone.now())     # 10자 미만
        Comment.objects.create(author=self.u, question=q, content='충분히 긴 댓글입니다 좋아요', create_date=timezone.now())
        Answer.objects.create(author=self.u, question=q, content='AI 가 대신 단 아주 긴 답변입니다', create_date=timezone.now(), is_ai=True)
        Answer.objects.create(author=self.u, question=q, content='제가 직접 단 꽤 긴 답변입니다', create_date=timezone.now())
        self.assertEqual(self.refresh().tp, R.WELCOME_TP + 20 + 10 + 10)
        self.assertEqual(sorted(self.p.logs.filter(kind='earn').values_list('source', flat=True)),
                         ['checkin', 'comment', 'comment'])

    def test_settle_decays_once_and_demotes(self):
        p = self.p
        today = timezone.localdate()
        p.stats = {k: 70.0 for k in p.stats}
        p.ovr, p.league, p.club = 70.0, 'kbo1', 'lg'
        p.last_active = today - timedelta(days=10)
        p.settled_through = today - timedelta(days=11)
        p.save()
        r = R.settle(p, today)
        self.assertEqual(r['days'], 10)
        self.assertLess(p.ovr, 58)
        self.assertEqual(p.league, 'kbo2')                       # 1군(64) − 6 아래 → 퓨처스
        self.assertTrue(p.logs.filter(kind='decay').exists())
        self.assertTrue(p.logs.filter(kind='demote').exists())
        self.assertEqual(R.settle(p, today)['days'], 0)          # 같은 날 두 번 정산하지 않는다

    def test_active_player_only_pays_upkeep(self):
        p = self.p
        today = timezone.localdate()
        p.stats = {k: 65.0 for k in p.stats}
        p.ovr = 65.0
        p.last_active = today - timedelta(days=1)
        p.settled_through = today - timedelta(days=2)
        p.save()
        R.settle(p, today)
        self.assertAlmostEqual(p.ovr, 65 - 40 * R.BASE_DECAY, places=1)

    def test_training_costs_tp_and_focus_grows_faster(self):
        r1 = R.train(self.u, 'control', 1, rng=FixedRng())
        r2 = R.train(self.u, 'velocity', 1, rng=FixedRng())
        self.assertAlmostEqual(r1['after'] - r1['before'], R.gain(25) * R.FOCUS_BONUS, places=2)
        self.assertAlmostEqual(r2['after'] - r2['before'], R.gain(25), places=2)
        p = self.refresh()
        self.assertEqual(p.tp, R.WELCOME_TP - 2 * R.TRAIN_COST)
        self.assertGreater(p.ovr, 25)
        with self.assertRaises(R.GameError):
            R.train(self.u, 'control', 10, rng=FixedRng()) and R.train(self.u, 'control', 10, rng=FixedRng())

    def test_fatigue_halves_gain_after_daily_limit(self):
        self.p.tp = 1000
        self.p.save()
        for _ in range(3):
            R.train(self.u, 'mental', 5, rng=FixedRng())         # 오늘 15회
        self.assertEqual(R.trained_today(self.refresh()), 15)
        s = float(self.p.stats['stamina'])
        r = R.train(self.u, 'stamina', 1, rng=FixedRng())
        self.assertAlmostEqual(r['after'] - s, R.gain(s) * R.FATIGUE_EFF, places=2)
        self.assertEqual(r['tired'], 1)

    @mock.patch('community.rookie_career.promotion_gate', return_value=GATE_OK)
    def test_promotion_test_rules(self, _gate):
        with self.assertRaises(R.GameError):
            R.promotion_test(self.u, rng=FixedRng(10))           # 학생(리틀)은 승격 심사가 없다
        self.p.league, self.p.club = 'kbo3', 'lg'
        self.p.save()
        with self.assertRaises(R.GameError):
            R.promotion_test(self.u, rng=FixedRng(10))           # OVR 25 < 퓨처스 49
        self.p.stats = {k: 50.0 for k in self.p.stats}
        self.p.ovr = 50.0
        self.p.save()
        r = R.promotion_test(self.u, rng=FixedRng(5))
        self.assertTrue(r['passed'])
        self.assertEqual(self.refresh().league, 'kbo2')
        self.assertEqual(r['games'][0]['line'], '6이닝 1실점 6탈삼진')
        with self.assertRaises(R.GameError):
            R.promotion_test(self.u, rng=FixedRng(5))            # 하루 한 번(이미 2군이라도 오늘 심사함)

    @mock.patch('community.rookie_career.promotion_gate', return_value=GATE_OK)
    def test_failed_test_keeps_league(self, _gate):
        self.p.stats = {k: 50.0 for k in self.p.stats}
        self.p.ovr, self.p.league, self.p.club = 50.0, 'kbo3', 'lg'
        self.p.save()
        r = R.promotion_test(self.u, rng=FixedRng(-9))
        self.assertFalse(r['passed'])
        self.assertEqual(self.refresh().league, 'kbo3')
        self.assertEqual(self.p.logs.filter(kind='test').count(), 1)


class ViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.u = member()

    def get(self, url, ua=PC, **kw):
        return self.client.get(url, HTTP_USER_AGENT=ua, **kw)

    def test_anonymous_sees_intro_and_ranking(self):
        r = self.get('/rookie/')
        self.assertContains(r, '로그인하고 시작')
        self.assertContains(r, '어떻게 키우나요')
        for url in ('/rookie/league/', '/rookie/league/?tab=players', '/rookie/league/?tab=teams',
                    '/rookie/awards/', '/rookie/records/', '/rookie/records/?role=pitcher'):
            self.assertEqual(self.get(url).status_code, 200, url)
        self.assertRedirects(self.get('/rookie/ranking/'), '/rookie/league/?tab=players', fetch_redirect_response=False)

    def test_create_then_play_pc_and_mobile(self):
        self.client.force_login(self.u)
        r = self.get('/rookie/')
        self.assertContains(r, '리틀야구단 입단하기')
        self.assertContains(r, '회원선수')                       # 이름 기본값 = 닉네임
        r = self.client.post('/rookie/create/', {'role': 'batter', 'team': 'kia', 'name': '창이', 'number': '7',
                                                 'focus_batter': 'power', 'region': '광주'}, HTTP_USER_AGENT=PC)
        self.assertRedirects(r, '/rookie/', fetch_redirect_response=False)
        p = RookiePlayer.objects.get(user=self.u)
        self.assertEqual((p.role, p.team, p.focus, p.number), ('batter', 'kia', 'power', 7))
        for ua in (PC, MOBILE):
            r = self.get('/rookie/', ua=ua)
            self.assertContains(r, '창이')
            self.assertContains(r, '광주 리틀야구단')
            self.assertContains(r, '희망 구단')
            self.assertContains(r, '중학야구 진학 지원')                # 초6 = 졸업 학년
            self.assertContains(r, '충장중')                          # 광주 중학교가 먼저
            self.assertContains(r, '오늘의 TP')
            self.assertContains(r, 'nonce=')
        self.assertTemplateUsed(self.get('/rookie/', ua=MOBILE), 'base_mobile.html')

    def test_train_ajax_returns_play_area(self):
        adult(R.create(self.u, name='창이', role='batter', team='kia', region='서울'))
        self.client.force_login(self.u)
        r = self.client.post('/rookie/train/', {'stat': 'contact', 'times': '5'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        d = r.json()
        self.assertTrue(d['ok'])
        self.assertIn('rk-stats', d['html'])
        self.assertIn('컨택', d['toast'])
        self.assertEqual(RookiePlayer.objects.get(user=self.u).tp, R.WELCOME_TP - 50)
        r = self.client.post('/rookie/train/', {'stat': 'contact', 'times': '10'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        r = self.client.post('/rookie/train/', {'stat': 'contact', 'times': '10'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)
        self.assertIn('모자라요', r.json()['message'])
        r = self.client.post('/rookie/train/', {'stat': 'eye', 'times': '1'})            # 자바스크립트 없이
        self.assertRedirects(r, '/rookie/', fetch_redirect_response=False)

    @mock.patch('community.rookie_career.promotion_gate', return_value=GATE_OK)
    def test_promotion_result_is_shown_once(self, _gate):
        p = adult(R.create(self.u, name='창이', role='batter', team='kia', region='서울'), league='kbo3', club='kia')
        p.stats = {k: 60.0 for k in p.stats}
        p.ovr = 60.0
        p.save()
        self.client.force_login(self.u)
        self.client.post('/rookie/test/')
        r = self.get('/rookie/')
        self.assertContains(r, '승격 심사')
        self.assertContains(r, 'rk-test')
        self.assertNotContains(self.get('/rookie/'), 'rk-test')

    def test_column_read_pays_tp_with_message_once(self):
        R.create(self.u, name='창이', role='batter', team='kia', region='서울')
        bot = User.objects.create(username=Question.BOT_USERNAME)
        cat, _ = Category.objects.get_or_create(name='HRD')
        col = Question.objects.create(author=bot, category=cat, subject='칼럼', content='본문 ' * 100,
                                      create_date=timezone.now())
        self.client.force_login(self.u)
        r = self.get(f'/{col.id}/')
        self.assertContains(r, '야구선수 훈련 포인트 +10 TP')
        self.assertNotContains(self.get(f'/{col.id}/'), '야구선수 훈련 포인트')
        self.assertEqual(RookiePlayer.objects.get(user=self.u).tp, R.WELCOME_TP + 10)

    def test_ranking_hides_admin_and_shows_teams(self):
        admin = member('admin', '운영자')
        R.create(admin, name='운영선수', role='pitcher', team='lg', region='서울')
        R.create(self.u, name='회원투수', role='pitcher', team='lg', region='서울')
        r = self.get('/rookie/league/?tab=players')
        self.assertContains(r, '회원투수')
        self.assertNotContains(r, '운영선수')
        r = self.get('/rookie/league/?tab=teams')
        self.assertContains(r, 'LG 트윈스')
        self.assertContains(r, '지망 유망주 1명')                  # 운영자 선수는 세지 않는다
        self.assertContains(r, '아직 선수 없음')

    def test_games_index_lists_rookie_and_retire_needs_confirm(self):
        self.assertContains(self.get('/games/'), '야구선수 키우기')
        R.create(self.u, name='창이', role='batter', team='kia', region='서울')
        self.client.force_login(self.u)
        self.client.post('/rookie/retire/', {})
        self.assertTrue(R.current(self.u.id))
        self.client.post('/rookie/retire/', {'confirm': 'yes'})
        self.assertIsNone(R.current(self.u.id))
        p = RookiePlayer.objects.get(user=self.u)                 # 은퇴한 선수는 기록으로 남는다
        self.assertIsNotNone(p.retired_at)
        self.assertTrue(p.logs.filter(kind='retire').exists())
        self.assertContains(self.get('/rookie/'), '지난 선수')        # 새 선수 만들기 + 지난 선수 안내
        self.assertEqual(self.get(f'/rookie/p/{p.pk}/').status_code, 200)

    def test_settle_command(self):
        from django.core.management import call_command
        p = R.create(self.u, name='창이', role='batter', team='kia', region='서울')
        p.stats = {k: 60.0 for k in p.stats}
        p.ovr = 60.0
        p.last_active = timezone.localdate() - timedelta(days=5)
        p.settled_through = timezone.localdate() - timedelta(days=5)
        p.save()
        out = mock.MagicMock()
        call_command('rookie_daily', stdout=out)
        p.refresh_from_db()
        self.assertLess(p.ovr, 60)
        self.assertEqual(p.settled_through, timezone.localdate() - timedelta(days=1))



class ColumnRepeatTests(TestCase):
    def test_same_column_pays_again_after_30_days(self):
        from datetime import timedelta
        u = member('재독자')
        p = R.create(u, name='재독', role='batter', team='kia', region='서울')
        self.assertTrue(R.award(u, 'column', '77'))
        self.assertIsNone(R.award(u, 'column', '77'))
        p.logs.filter(source='column').update(day=timezone.localdate() - timedelta(days=31))
        self.assertTrue(R.award(u, 'column', '77'))


class CreateTwiceTests(TestCase):
    def test_double_submit_does_not_500(self):
        from django.db import IntegrityError
        u = member('두번누름')
        self.client.force_login(u)
        with mock.patch('community.rookie.create', side_effect=IntegrityError('dup')):
            r = self.client.post('/rookie/create/', {'role': 'batter', 'team': 'lg', 'name': 'x', 'region': '서울'})
        self.assertEqual(r.status_code, 302)

    def test_bad_train_input_has_friendly_message(self):
        u = member('이상입력')
        R.create(u, name='x', role='batter', team='lg', region='서울')
        self.client.force_login(u)
        r = self.client.post('/rookie/train/', {'stat': 'contact', 'times': 'abc'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('invalid literal', r.json()['message'])



class NightlyIsolationTests(TestCase):
    """선수 한 명의 오류·망가진 데이터가 밤 정산 전체와 리그 화면을 멈추지 않는다(2026-10-18 감사 C7·V2)."""

    def setUp(self):
        cache.clear()

    def stale(self, p):
        p.settled_through = timezone.localdate() - timedelta(days=5)
        p.last_active = timezone.localdate() - timedelta(days=5)
        p.stats = {k: 60.0 for k in p.stats}
        p.ovr = 60.0
        p.save()

    def test_broken_player_does_not_stop_others(self):
        from community import rookie_world as W
        bad = adult(R.create(member('망가짐'), name='망가짐', role='batter', team='lg', region='서울'),
                    league='KBO1', club='lg', pending={'kind': 'draft'})           # 관리자 오타·기한 없는 결정
        ok = adult(R.create(member('멀쩡함'), name='멀쩡함', role='batter', team='kia', region='서울'),
                   league='kbo1', club='kia')
        for p in (bad, ok):
            self.stale(p)
        self.assertIsNone(W.prev_league('KBO1'))
        self.assertIsNone(W.next_league('KBO1'))
        real = R.settle

        def boom(p, *a, **kw):
            if p.pk == bad.pk:
                raise RuntimeError('boom')
            return real(p, *a, **kw)
        with mock.patch('community.rookie.settle', side_effect=boom):
            self.assertEqual(R.settle_all(), 1)
        ok.refresh_from_db()
        self.assertEqual(ok.settled_through, timezone.localdate() - timedelta(days=1))
        self.assertGreaterEqual(R.settle_all(), 1)                             # 망가진 데이터도 예외 없이 정산
        bad.refresh_from_db()
        self.assertEqual(bad.pending, {})                                     # 기한 없는 결정 = 지난 것 → 기본값
        self.client.force_login(ok.user)
        self.assertEqual(self.client.get('/rookie/league/', HTTP_USER_AGENT=PC).status_code, 200)

    def test_admin_league_is_a_choice(self):
        from community.admin import RookiePlayerForm
        choices = dict(RookiePlayerForm.base_fields['league'].choices)
        self.assertIn('kbo1', choices)
        self.assertNotIn('KBO1', choices)
        su = User.objects.create_superuser('운영', 'op@example.com', 'pw12345!')
        p = adult(R.create(member('관리대상'), name='관리', role='batter', team='lg', region='서울'))
        self.client.force_login(su)
        from django.conf import settings
        base = '/' + getattr(settings, 'ADMIN_URL', 'secret-control-panel/').strip('/') + '/'
        r = self.client.get(f'{base}community/rookieplayer/{p.pk}/change/', HTTP_USER_AGENT=PC)
        self.assertIn(r.status_code, (200, 302))


class MainFromLiteTests(TestCase):
    """2026-10-19 — 라이트 판의 각성·은퇴 카드·베스트 라인업을 정식 판에도."""

    def setUp(self):
        import tempfile
        cache.clear()
        self.media = tempfile.mkdtemp()

    def _capped(self, name='각성정식', age=26, potential=70, tp=400):
        from community import rookie_career as C
        u = member(name, name)
        p = R.create(u, name=name, role='batter', team='lg', region='서울', focus='contact')
        p = adult(p, age=age, potential=potential, league='kbo1', club='lg', tp=tp)
        p.stats = {k: C.stat_cap(p, k) for k in p.stats}
        p.save()
        return u, p

    def test_awakening_needs_a_grown_body_with_every_stat_capped(self):
        from community import rookie_career as C
        u, p = self._capped()
        self.assertTrue(C.awaken_ready(p))
        young = adult(R.create(member('어린이', '어린이'), name='어린이', role='batter', team='lg', region='서울'), age=20, potential=70)
        young.stats = {k: C.stat_cap(young, k) for k in young.stats}
        self.assertFalse(C.awaken_ready(young))                        # 나이 한계가 아직 오르는 중
        cap, gain = C.stat_cap(p, 'power'), C.awaken_gain(p)
        lucky = type('Lucky', (), {'random': lambda self: 0.0})()
        r = R.awaken(u, 'try', rng=lucky)
        p.refresh_from_db()
        self.assertEqual(C.awakened(p), 1)
        self.assertEqual(C.stat_cap(p, 'power'), cap + gain)              # 보라색 별 = 한 칸 위 별의 잠재력까지
        self.assertEqual(C.base_stars(p) + C.awakened(p), 2)                  # 별 하나짜리(잠재력 70)가 둘로
        self.assertEqual(p.tp, 400 - C.AWAKEN_COST)
        self.assertTrue(p.career['awaken_fx']['ok'])
        self.assertIn('각성에 성공', r['text'])
        self.assertFalse(C.awaken_ready(p))
        # 연출은 한 번, 보라색 별은 진로 칸에
        self.client.force_login(u)
        self.assertContains(self.client.get('/rookie/', HTTP_USER_AGENT=PC), 'rl-fx is-ok')
        r = self.client.get('/rookie/', HTTP_USER_AGENT=PC)
        self.assertNotContains(r, 'rl-fx is-ok')
        self.assertContains(r, 'is-awaken')

    def test_awakening_panel_skip_and_short_tp(self):
        from community import rookie_career as C
        u, p = self._capped('보류정식', tp=40)
        self.client.force_login(u)
        r = self.client.get('/rookie/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '각성의 순간')
        self.assertContains(r, 'TP를 더 모아 올게요')                     # 150 TP 가 없다
        with self.assertRaises(R.GameError):
            R.awaken(u, 'try')
        self.client.post('/rookie/awaken/', {'choice': 'skip'})
        p.refresh_from_db()
        self.assertTrue(p.career.get('awaken_next'))
        self.assertFalse(C.awaken_ready(p))
        self.assertNotContains(self.client.get('/rookie/', HTTP_USER_AGENT=PC), '각성의 순간')

    def test_retire_shows_the_jersey_card_and_image(self):
        from django.test import override_settings
        from community.views import rookie_views as RV
        u, p = self._capped('카드정식', potential=88)
        self.client.force_login(u)
        self.assertRedirects(self.client.get(f'/rookie/p/{p.pk}/card/'), f'/rookie/p/{p.pk}/', fetch_redirect_response=False)
        self.assertEqual(self.client.get(f'/rookie/p/{p.pk}/card.png').status_code, 404)   # 현역은 아직
        r = self.client.post('/rookie/retire/', {'confirm': 'yes'})
        self.assertRedirects(r, f'/rookie/p/{p.pk}/card/?new=1', fetch_redirect_response=False)
        r = self.client.get(f'/rookie/p/{p.pk}/card/?new=1', HTTP_USER_AGENT=PC)
        self.assertContains(r, 'rl-rc-jersey')
        self.assertContains(r, '쌓은 TP')
        self.assertContains(r, '새 선수 시작하기')
        self.assertContains(r, f'/rookie/p/{p.pk}/og.png')
        self.assertContains(self.client.get(f'/rookie/p/{p.pk}/', HTTP_USER_AGENT=MOBILE), '은퇴 카드 보기')
        calls = []

        def fake(html, size, out):
            import os
            calls.append(size)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, 'wb').write(b'PNG-fake')
        with override_settings(MEDIA_ROOT=self.media), mock.patch.object(RV, 'render_png', fake):
            for _ in range(2):
                self.assertEqual(self.client.get(f'/rookie/p/{p.pk}/card.png')['Content-Type'], 'image/png')
        self.assertEqual(calls, [(432, 540, 2.5)])

    def test_hall_of_fame_has_best_lineup(self):
        from community import rookie_league as L
        from community.models import RookieSeasonStat
        u, p = self._capped('라인업정식')
        RookieSeasonStat.objects.create(season=L.get_season(1), user=u, player=p, league='kbo1', name=p.name, team='lg',
                                        role='batter', position=p.position, war=4.0, best_ovr=80, age=27,
                                        totals={'g': 120, 'pa': 500, 'ab': 450, 'h': 140})
        p.retired_at = timezone.now()
        p.save()
        r = self.client.get('/rookie/records/?view=hof&lg=kbo1', HTTP_USER_AGENT=PC)
        self.assertContains(r, '역대 베스트 라인업')
        self.assertContains(r, '라인업정식')


class AwakenRedesignTests(TestCase):
    """2026-10-19 각성 개편 — 별 다섯 칸 고정(보라색이 빈 칸을 채운다), 성적이 좋으면 한계 전에도 기회."""

    def _p(self, name, potential, age=26, tp=2000):
        from community import rookie_career as C
        u = member(name, name)
        p = adult(R.create(u, name=name, role='batter', team='lg', region='서울', focus='contact'), age=age,
                  potential=potential, league='kbo1', club='lg', tp=tp)
        p.stats = {k: C.stat_cap(p, k) for k in p.stats}
        p.save()
        return u, p

    def test_one_star_can_climb_to_five_and_stops_there(self):
        from community import rookie_career as C
        u, p = self._p('한별', 70)
        lucky = type('Lucky', (), {'random': lambda self: 0.0})()
        seen = []
        for _ in range(6):
            p.refresh_from_db()
            p.career = {k: v for k, v in (p.career or {}).items() if k != 'awaken_next'}   # 기다리는 날은 건너뛴다
            p.stats = {k: C.stat_cap(p, k) for k in p.stats}
            p.save()
            if not C.awaken_ready(p):
                break
            R.awaken(u, 'try', rng=lucky)
            p.refresh_from_db()
            seen.append(C.base_stars(p) + C.awakened(p))
        self.assertEqual(seen, [2, 3, 4, 5])                                 # 다섯 칸에서 멈춘다
        self.assertEqual(C.pot_eff(p), C.STAR_FLOOR[5])
        five = self._p('다섯별', 95)[1]
        self.assertFalse(C.awaken_ready(five))                                # 처음부터 다섯이면 기회 없음

    def test_hard_work_and_form_open_the_door_before_the_wall(self):
        from community import rookie_career as C
        u, p = self._p('열일', 80, age=19)
        p.stats = {k: C.stat_cap(p, k) - 2.0 for k in p.stats}                # 한계 가까이(평균 2 모자람)
        p.save()
        with mock.patch.object(C, 'performance', return_value=1.2):
            self.assertTrue(C.awaken_ready(p))
        with mock.patch.object(C, 'performance', return_value=0.1):
            self.assertFalse(C.awaken_ready(p))                               # 성적이 받쳐 줘야
        p.stats = {k: C.stat_cap(p, k) - 8.0 for k in p.stats}
        with mock.patch.object(C, 'performance', return_value=2.0):
            self.assertFalse(C.awaken_ready(p))                               # 덜 키웠으면 안 된다

    def test_little_league_pitcher_throws_like_a_kid(self):
        from community import rookie_sim as M
        self.assertLess(M.top_speed(33, 12), 100)
        self.assertGreater(M.top_speed(33, 12), 80)
        self.assertEqual(M.top_speed(60, 25), M.top_speed(60))
        self.assertLess(M.top_speed(55, 17), 140)


class NameRuleTests(TestCase):
    def test_main_game_refuses_politician_names(self):
        with self.assertRaises(R.GameError):
            R.create(member('정치이름', '정치이름'), name='문재인', role='batter', team='lg', region='서울')
        r = self.client
        u = member('폼정치', '폼정치')
        r.force_login(u)
        r.post('/rookie/create/', {'name': '전두환', 'role': 'batter', 'team': 'lg', 'region': '서울', 'number': '1',
                                   'focus': 'contact', 'position': 'SS'})
        self.assertFalse(RookiePlayer.objects.filter(user=u).exists())


class AwardCelebrationTests(TestCase):
    """2026-10-19 수상 축하 — 새로 받은 상을 내 선수 화면에서 한 번."""

    def test_new_award_is_celebrated_once(self):
        from community import rookie_league as L
        from community.models import RookieAward
        u = member('정식수상', '정식수상')
        p = adult(R.create(u, name='정식수상', role='batter', team='lg', region='서울', focus='contact'), league='kbo1', club='lg')
        s = L.get_season(1)
        RookieAward.objects.create(season=s, user=u, player=p, league='kbo1', kind='gg', label='골든글러브 유격수', name=p.name,
                                   team='lg', role='batter', value='WAR 5.1')
        RookieAward.objects.create(season=s, user=u, player=p, league='kbo1', kind='mvp', label='MVP', name=p.name,
                                   team='lg', role='batter', value='WAR 7.2 · .341/.420/.612')
        self.client.force_login(u)
        r = self.client.get('/rookie/', HTTP_USER_AGENT=PC)
        self.assertContains(r, 'rl-mfx is-award')
        self.assertContains(r, 'WAR 7.2')                                      # MVP 가 앞에, 골든글러브는 곁에
        self.assertContains(r, '골든글러브 유격수')
        self.assertNotContains(self.client.get('/rookie/', HTTP_USER_AGENT=PC), 'rl-mfx is-award')
