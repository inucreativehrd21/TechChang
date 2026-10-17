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
        self.assertGreaterEqual(curve[0], 38)                 # 출석만 해도 첫날 25 → 38+

    def test_each_activity_level_converges(self):
        light = R.simulate(20, 150)[0]
        steady = R.simulate(30, 150)[0]
        full = R.simulate(R.DAILY_MAX, 150)[0]
        for curve in (light, steady, full):
            self.assertLess(abs(curve[-1] - curve[-30]), 0.6)  # 마지막 한 달은 거의 안 움직인다 = 수렴
        self.assertTrue(60 <= light[-1] < 65)                  # 출석만 → 2군 상위
        self.assertTrue(65 <= steady[-1] < 72)                 # 출석+칼럼 1편 → 1군
        self.assertTrue(78 <= full[-1] < 83)                   # 매일 한도 → 에이스
        self.assertLessEqual(next(i for i, v in enumerate(full) if v >= 45) + 1, 2)   # 2군 문턱 이틀

    def test_rest_drops_hard(self):
        _, stats = R.simulate(R.DAILY_MAX, 150)
        week = R.simulate(0, 7, start=stats, idle=True)[0][-1]
        two = R.simulate(0, 14, start=stats, idle=True)[0][-1]
        self.assertLess(week, 61)                               # 에이스도 일주일 쉬면 1군 강등선
        self.assertLess(two, 40)                                # 2주면 육성군 강등선
        self.assertEqual(R.decay_rate(0), R.decay_rate(1))
        self.assertEqual(R.decay_rate(30), R.MAX_DECAY)


class EngineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.u = member()
        self.p = R.create(self.u, name='김테크', role='pitcher', team='lg', number=17, focus='control')

    def refresh(self):
        self.p.refresh_from_db()
        return self.p

    def test_create_starts_at_floor_with_welcome_tp(self):
        p = self.p
        self.assertEqual((p.tp, p.tier, p.focus), (R.WELCOME_TP, 0, 'control'))
        self.assertEqual(set(p.stats), {'velocity', 'control', 'breaking', 'stamina', 'mental'})
        self.assertEqual(p.ovr, 25.0)
        self.assertEqual(p.logs.get().kind, 'start')
        with self.assertRaises(R.GameError):
            R.create(member('m2'), name='x', role='pitcher', team='mlb')

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
        p.ovr, p.tier = 70.0, 2
        p.last_active = today - timedelta(days=10)
        p.settled_through = today - timedelta(days=11)
        p.save()
        r = R.settle(p, today)
        self.assertEqual(r['days'], 10)
        self.assertLess(p.ovr, 60)
        self.assertEqual(p.tier, 1)                              # 1군 → 2군 (60 아래)
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

    def test_promotion_test_rules(self):
        with self.assertRaises(R.GameError):
            R.promotion_test(self.u, rng=FixedRng(10))           # OVR 25 < 45
        self.p.stats = {k: 46.0 for k in self.p.stats}
        self.p.ovr = 46.0
        self.p.save()
        r = R.promotion_test(self.u, rng=FixedRng(5))
        self.assertTrue(r['passed'])
        self.assertEqual(self.refresh().tier, 1)
        self.assertEqual(r['games'][0]['line'], '6이닝 1실점 6탈삼진')
        with self.assertRaises(R.GameError):
            R.promotion_test(self.u, rng=FixedRng(5))            # 하루 한 번(이미 2군이라도 오늘 심사함)

    def test_failed_test_keeps_tier(self):
        self.p.stats = {k: 46.0 for k in self.p.stats}
        self.p.ovr = 46.0
        self.p.save()
        r = R.promotion_test(self.u, rng=FixedRng(-9))
        self.assertFalse(r['passed'])
        self.assertEqual(self.refresh().tier, 0)
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
        self.assertContains(r, '육성군 입단하기')
        self.assertContains(r, '회원선수')                       # 이름 기본값 = 닉네임
        r = self.client.post('/rookie/create/', {'role': 'batter', 'team': 'kia', 'name': '창이', 'number': '7',
                                                 'focus_batter': 'power'}, HTTP_USER_AGENT=PC)
        self.assertRedirects(r, '/rookie/', fetch_redirect_response=False)
        p = RookiePlayer.objects.get(user=self.u)
        self.assertEqual((p.role, p.team, p.focus, p.number), ('batter', 'kia', 'power', 7))
        for ua in (PC, MOBILE):
            r = self.get('/rookie/', ua=ua)
            self.assertContains(r, '창이')
            self.assertContains(r, 'KIA 타이거즈')
            self.assertContains(r, '오늘의 TP')
            self.assertContains(r, 'nonce=')
        self.assertTemplateUsed(self.get('/rookie/', ua=MOBILE), 'base_mobile.html')

    def test_train_ajax_returns_play_area(self):
        R.create(self.u, name='창이', role='batter', team='kia')
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
        self.assertIn('모자랍니다', r.json()['message'])
        r = self.client.post('/rookie/train/', {'stat': 'eye', 'times': '1'})            # 자바스크립트 없이
        self.assertRedirects(r, '/rookie/', fetch_redirect_response=False)

    def test_promotion_result_is_shown_once(self):
        p = R.create(self.u, name='창이', role='batter', team='kia')
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
        R.create(self.u, name='창이', role='batter', team='kia')
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
        R.create(admin, name='운영선수', role='pitcher', team='lg')
        R.create(self.u, name='회원투수', role='pitcher', team='lg')
        r = self.get('/rookie/league/?tab=players')
        self.assertContains(r, '회원투수')
        self.assertNotContains(r, '운영선수')
        r = self.get('/rookie/league/?tab=teams')
        self.assertContains(r, 'LG 트윈스')
        self.assertContains(r, '선수 1명')
        self.assertContains(r, '아직 선수 없음')

    def test_games_index_lists_rookie_and_retire_needs_confirm(self):
        self.assertContains(self.get('/games/'), '야구선수 키우기')
        R.create(self.u, name='창이', role='batter', team='kia')
        self.client.force_login(self.u)
        self.client.post('/rookie/retire/', {})
        self.assertTrue(RookiePlayer.objects.filter(user=self.u).exists())
        self.client.post('/rookie/retire/', {'confirm': 'yes'})
        self.assertFalse(RookiePlayer.objects.filter(user=self.u).exists())

    def test_settle_command(self):
        from django.core.management import call_command
        p = R.create(self.u, name='창이', role='batter', team='kia')
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
        p = R.create(u, name='재독', role='batter', team='kia')
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
            r = self.client.post('/rookie/create/', {'role': 'batter', 'team': 'lg', 'name': 'x'})
        self.assertEqual(r.status_code, 302)

    def test_bad_train_input_has_friendly_message(self):
        u = member('이상입력')
        R.create(u, name='x', role='batter', team='lg')
        self.client.force_login(u)
        r = self.client.post('/rookie/train/', {'stat': 'contact', 'times': 'abc'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('invalid literal', r.json()['message'])
