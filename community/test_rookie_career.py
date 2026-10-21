"""야구선수 키우기 — 선수 일생(rookie_career)·유산(rookie_legacy)·리그 코드 화면(2026-10-17 '선수 일생' 개편)."""
import io
import random
from datetime import datetime, timedelta
from unittest import mock

from django.core.management import call_command

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from common.models import Profile
from community import rookie as R
from community import rookie_career as C
from community import rookie_league as L
from community import rookie_legacy as G
from community import rookie_world as W
from community.models import RookieAward, RookieGame, RookieLog, RookiePlayer, RookieSeasonStat

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'
D1 = L.EPOCH


class Lucky:
    """합격·지명·희망 구단이 모두 '예'로 나오는 운 — random()=0, gauss()=0, choice 는 첫째."""
    def random(self):
        return 0.0

    def gauss(self, mu, sigma):
        return 0.0

    def choice(self, seq):
        return seq[0]

    def randint(self, a, b):
        return a

    def uniform(self, a, b):
        return (a + b) / 2


class Unlucky(Lucky):
    def random(self):
        return 0.999


def member(name):
    u = User.objects.create_user(username=name, password='pw12345!', email=f'{name}@example.com')
    pr, _ = Profile.objects.get_or_create(user=u)
    pr.nickname, pr.is_email_verified = name, True
    pr.save()
    return u


def kid(name='꼬마', role='batter', region='서울', team='kia', **over):
    p = R.create(member(name), name=name, role=role, team=team, region=region, rng=random.Random(1))
    fields = dict(traits=[], traits_seen=[], potential=90)
    fields.update(over)
    for k, v in fields.items():
        setattr(p, k, v)
    p.career = {'path': [dict(p.career['path'][0], day='2026-10-01')]}
    p.role_since = datetime(2026, 10, 1).date()
    p.save()
    RookiePlayer.objects.filter(pk=p.pk).update(created_at=timezone.make_aware(datetime(2026, 10, 1, 12, 0)))
    p.refresh_from_db()
    return p


def played_until(day):
    """그날까지 경기를 치른 것으로 — 학년 전환은 전날 경기를 치른 뒤에만 일어난다(rookie_career._school_due)."""
    for n in range(1, L.season_no(day) + 1):
        s = L.get_season(n)
        s.simulated_through = min(s.end, day)
        s.save()


def set_stats(p, level):
    p.stats = {k: float(level) for k in p.stats}
    p.ovr = R.overall(p.role, p.stats)
    p.save()


class RollTests(TestCase):
    def test_potential_and_traits(self):
        rng = random.Random(7)
        pots = [C.roll_potential(rng) for _ in range(400)]
        self.assertTrue(all(C.POTENTIAL_RANGE[0] <= x <= C.POTENTIAL_RANGE[1] for x in pots))
        self.assertTrue(78 <= sum(pots) / len(pots) <= 86)
        for _ in range(400):
            t = C.roll_traits(rng)
            self.assertLessEqual(len(t), 2)
            self.assertFalse({'early', 'late'} <= set(t))
            self.assertTrue(set(t) <= set(C.TRAITS))

    def test_scout_stars_appear_in_high_school(self):
        p = kid()
        self.assertIsNone(C.scout_stars(p))
        p.age, p.potential = 16, 93
        self.assertEqual(C.scout_stars(p), 5)
        p.potential = 70
        self.assertEqual(C.scout_stars(p), 1)


class CapTests(TestCase):
    def test_age_cap_stops_training_and_opens_with_age(self):
        cache.clear()
        p = kid()                                                          # 잠재력 90
        self.assertEqual(C.age_cap(p), 90 * C.AGE_RATIO[12])               # 나이 한계 = 잠재력 × 나이 비율
        self.assertEqual(C.stat_cap(p, p.focus), 90 * C.AGE_RATIO[12] + 4)  # 주특기는 +4
        p.tp = 2000
        p.save()
        with self.assertRaises(R.GameError) as ex:
            for _ in range(20):
                R.train(p.user, 'power', 5, rng=Lucky())               # 파워(주특기 아님)는 42 에서 멈춘다
        self.assertIn('12세', str(ex.exception))
        p.refresh_from_db()
        self.assertLessEqual(p.stats['power'], 90 * C.AGE_RATIO[12] + 1e-6)
        self.assertTrue(next(r for r in R.stat_rows(p) if r['key'] == 'power')['capped'])
        p.age = 16
        self.assertAlmostEqual(C.age_cap(p), 90 * C.AGE_RATIO[16])
        p.age, p.potential = 30, 70
        self.assertEqual(C.stat_cap(p, 'power'), 70)                 # 다 크면 잠재력이 한계
        p.potential = 75
        self.assertLess(C.age_cap(kid('비교한계', potential=75)), C.age_cap(kid('비교한계2', potential=90)))  # 학생 때도 잠재력이 작용

    def test_efficiency_peaks_in_early_twenties_and_old_decline(self):
        p = kid()
        kid_eff = C.age_mult(p)
        p.age = 24
        peak = C.age_mult(p)
        p.age = 35
        self.assertLess(kid_eff, peak)                                       # 몸이 덜 자란 학생은 효율이 낮다
        self.assertGreater(peak, C.age_mult(p))
        self.assertEqual(C.decline_start(p), 33)                             # 2026-10-19 노쇠 2년 늦춤
        self.assertEqual(C.decay_for(p, R.BASE_DECAY, 'contact'), R.BASE_DECAY)
        self.assertGreater(C.decay_for(p, R.BASE_DECAY, 'power'), R.BASE_DECAY)   # 몸 능력은 노쇠
        p.traits = ['iron']
        self.assertLess(C.decay_for(p, R.BASE_DECAY, 'power'), C.decay_for(kid('비교', age=35), R.BASE_DECAY, 'power'))

    def test_tp_has_a_ceiling(self):
        p = kid()
        p.tp = R.TP_MAX - 5
        p.save()
        got = R.award(p.user, 'column', '1')
        self.assertEqual((got['tp'], got['full']), (5, True))
        self.assertEqual(R.award(p.user, 'column', '2')['tp'], 0)   # 활동은 기록된다(출전·감쇠 판정)
        p.refresh_from_db()
        self.assertEqual(p.tp, R.TP_MAX)
        self.assertEqual(p.last_active, timezone.localdate())


class SchoolPathTests(TestCase):
    def setUp(self):
        cache.clear()
        played_until(timezone.localdate() + timedelta(days=60))

    def test_week_later_enters_chosen_middle_school(self):
        p = kid(region='경기')
        set_stats(p, 40)
        C.apply_school(p.user, '대원중')
        p.refresh_from_db()
        self.assertEqual(p.pending['choice'], '대원중')
        C.progress(p, p.grade_since + timedelta(days=C.GRADE_DAYS), rng=Lucky())
        p.refresh_from_db()
        self.assertEqual((p.league, p.club, p.grade, p.age), ('ms', '대원중', 1, 13))
        self.assertEqual(p.lineup, 'bench')                         # 신입생은 백업부터
        self.assertTrue(p.logs.filter(kind='career', text__contains='대원중 합격').exists())
        self.assertEqual([x['league'] for x in p.career['path']], ['little', 'ms'])
        self.assertEqual(p.pending, {})

    def test_rejected_or_no_choice_goes_to_local_school(self):
        p = kid(region='강원')
        p.pending = dict(p.pending, choice='배명중')                        # 서울 학교에 지원했다가 떨어짐
        p.save()
        C.progress(p, p.grade_since + timedelta(days=C.GRADE_DAYS), rng=Unlucky())
        p.refresh_from_db()
        self.assertEqual(p.league, 'ms')
        self.assertIn(p.club, W.MIDDLE_SCHOOLS['강원'])                      # 지원한 학교 쪽이 아니라 우리 지역
        self.assertTrue(p.logs.filter(kind='career', text__contains='배명중 불합격 — 우리 지역').exists())
        for _ in range(5):                                                   # 목록 없는 지역 → 가까운 지역부터
            b = kid(f'부산{_}', region='부산')
            C.progress(b, b.grade_since + timedelta(days=C.GRADE_DAYS), rng=random.Random(_))
            b.refresh_from_db()
            self.assertIn(W.school_region('ms', b.club), ('경북', '대구'))
            self.assertTrue(b.logs.filter(kind='career', text__contains='가까운').exists())
        q = kid('무지원', region='제주')
        C.progress(q, q.grade_since + timedelta(days=C.GRADE_DAYS), rng=Lucky())
        q.refresh_from_db()
        self.assertEqual(q.club, '제일중')                             # 제주 중학교로 배정

    def test_powerhouse_is_harder(self):
        p = kid()
        set_stats(p, 45)
        p.league, p.grade, p.age = 'ms', 3, 15
        self.assertGreater(C.accept_chance(p, 'hs', '서울동산고', 0), C.accept_chance(p, 'hs', '덕수고', 0))
        set_stats(p, 60)
        self.assertGreater(C.accept_chance(p, 'hs', '덕수고', 0), 0.6)  # 잘 크면 강호도 열린다

    def test_long_absence_catches_up_grades(self):
        p = kid()
        C.progress(p, p.grade_since + timedelta(days=C.GRADE_DAYS * 4), rng=Lucky())
        p.refresh_from_db()
        self.assertEqual((p.league, p.grade, p.age), ('hs', 1, 16))   # 초6 → 중1 → 중2 → 중3 → 고1
        self.assertEqual(p.pending, {})

    def test_early_bloomer_is_hidden_until_revealed(self):
        p = kid('조기', traits=['early'])
        self.assertEqual(C.age_cap(p), 90 * C.AGE_RATIO[12])               # 입단 화면에서 티가 나지 않는다
        self.assertEqual(C.career_view(p)['age_cap'], 90 * C.AGE_RATIO[12])
        C.progress(p, p.grade_since + timedelta(days=C.GRADE_DAYS), rng=Lucky())
        p.refresh_from_db()
        self.assertIn('early', p.traits_seen)
        self.assertAlmostEqual(C.age_cap(p), 90 * C.AGE_RATIO[14])        # 13세지만 한 살 먼저 열린다
        p.age = 24
        self.assertEqual(C.age_ratio(p), 1.0)                                # 줄어들지 않고 이어진다

    def test_quick_retire_cannot_reroll_talent(self):
        p = kid('리롤', traits=['natural'], potential=95)
        R.retire(p.user)
        q = R.create(p.user, name='리롤2', role='batter', team='kia', region='서울', rng=random.Random(99))
        self.assertEqual((q.potential, q.traits), (95, ['natural']))
        R.retire(q.user)
        from community.models import RookiePlayer as P
        P.objects.filter(user=q.user).update(retired_at=timezone.now() - timedelta(days=15))
        self.assertIsNone(R.inherits_from(q.user))                           # 시간이 지나면 새로 뽑는다

    def test_amateur_cannot_take_promotion_test(self):
        p = kid()
        with self.assertRaises(R.GameError):
            R.promotion_test(p.user)


class DraftTests(TestCase):
    def setUp(self):
        cache.clear()
        played_until(timezone.localdate() + timedelta(days=60))

    def senior(self, level=60, name='고3', **over):
        p = kid(name, **over)
        p.league, p.club, p.grade, p.age = 'hs', '덕수고', 3, 18
        p.grade_since = timezone.localdate() - timedelta(days=C.GRADE_DAYS)
        p.pending = {}
        p.save()
        set_stats(p, level)
        return p

    def test_star_is_drafted_by_wanted_team_and_signs(self):
        p = self.senior(66)
        tp0 = p.tp
        C.progress(p, timezone.localdate(), rng=Lucky())
        p.refresh_from_db()
        d = p.pending
        self.assertEqual(d['kind'], 'draft')
        self.assertEqual((d['offer']['team'], d['offer']['round']), ('kia', 1))
        self.assertTrue(d['abroad']['mlb'] and d['abroad']['npb'])     # 상위권 — 자격이 되는 나라 모두(2026-10-19)
        self.assertEqual(len(d['abroad']['mlb']), 3)                     # 나라마다 구단 셋 가운데 고른다
        self.assertTrue(p.logs.filter(kind='career', text__contains='1라운드').exists())
        text = C.decide(p.user, 'sign')
        p.refresh_from_db()
        self.assertEqual((p.league, p.club, p.age, p.grade), ('kbo2', 'kia', 19, 0))
        self.assertIn('입단', text)
        self.assertEqual(p.career['draft_hs']['round'], 1)
        self.assertEqual(p.lineup, 'bench')
        self.assertEqual(p.tp, tp0 + C.sign_bonus(1))                      # 지명 순위만큼 계약 보너스
        self.assertEqual(p.league_since, timezone.localdate())

    def test_undrafted_goes_develop_or_abroad_is_closed(self):
        p = self.senior(30, name='미지명')
        C.progress(p, timezone.localdate(), rng=Lucky())
        p.refresh_from_db()
        self.assertIsNone(p.pending['offer'])
        self.assertFalse(any(p.pending['abroad'].values()))
        with self.assertRaises(R.GameError):
            C.decide(p.user, 'sign')
        with self.assertRaises(R.GameError):
            C.decide(p.user, 'mlb')
        C.decide(p.user, 'develop')
        p.refresh_from_db()
        self.assertEqual((p.league, p.club), ('kbo3', 'kia'))

    def test_decline_for_university_then_draft_again(self):
        p = self.senior(55, name='대학파')
        C.progress(p, timezone.localdate(), rng=Lucky())
        with self.assertRaises(R.GameError):
            C.decide(p.user, 'univ', school='')                      # 대학을 골라야 한다
        C.decide(p.user, 'univ', school='고려대', rng=Lucky())
        p.refresh_from_db()
        self.assertEqual((p.league, p.club, p.grade, p.age), ('univ', '고려대', 1, 19))
        p.grade_since = timezone.localdate() - timedelta(days=C.GRADE_DAYS)
        p.save()
        C.progress(p, timezone.localdate(), rng=Lucky())
        p.refresh_from_db()
        self.assertEqual(p.grade, 1)                                         # 대학 한 학년은 30일(프로 한 시즌)
        p.grade, p.age = 4, 22
        p.grade_since = timezone.localdate() - timedelta(days=C.UNIV_GRADE_DAYS)
        p.save()
        set_stats(p, 80)
        C.progress(p, timezone.localdate(), rng=Lucky())
        p.refresh_from_db()
        self.assertEqual((p.pending['kind'], p.pending['from']), ('draft', 'univ'))
        with self.assertRaises(R.GameError):
            C.decide(p.user, 'univ', school='연세대')                # 대학은 한 번
        C.decide(p.user, 'mlb')
        p.refresh_from_db()
        self.assertEqual((p.league, p.age), ('mlb_aa', 23))                 # 대졸은 한 단계 위(더블A)부터
        self.assertIn(p.club, [c for c, _n, _col in W.MLB_TEAMS])
        self.assertEqual(len(p.career['path']), 3)                   # 리틀(입단) → 대학 → 미국

    def test_deadline_signs_by_default_and_draft_players_sit_out(self):
        p = self.senior(62, name='기한넘김')
        C.progress(p, timezone.localdate(), rng=Lucky())
        p.refresh_from_db()
        self.assertEqual(p.pending['kind'], 'draft')
        later = timezone.localdate() + timedelta(days=C.DECIDE_DAYS + 1)
        C.progress(p, later, rng=Lucky())
        p.refresh_from_db()
        self.assertEqual((p.league, p.club), ('kbo2', 'kia'))
        self.assertTrue(p.logs.filter(text__contains='결정 기한이 지나').exists())

    def test_failed_decision_cannot_reroll_the_draft(self):
        p = self.senior(30, name='재추첨')                                   # 미지명 · 해외 제안 없음
        with mock.patch('community.rookie_career.random.SystemRandom', return_value=Lucky()):
            with self.assertRaises(R.GameError) as first:
                C.decide(p.user, 'mlb')
            self.assertIn('방금', str(first.exception))
            p.refresh_from_db()
            score = p.pending['score']
            with self.assertRaises(R.GameError):
                C.decide(p.user, 'mlb')
        p.refresh_from_db()
        self.assertEqual(p.pending['score'], score)
        self.assertEqual(p.logs.filter(kind='career', text__contains='드래프트').count(), 1)

    def test_training_after_retirement_age_is_refused(self):
        p = kid('마지막')
        p.league, p.club, p.grade, p.grade_since, p.pending = 'kbo1', 'lg', 0, None, {}
        p.age, p.age_season, p.tp = 44, 3, 200
        p.save()
        with mock.patch('django.utils.timezone.localdate', return_value=L.season_bounds(4)[0]):
            with self.assertRaises(R.GameError) as ex:
                R.train(p.user, 'contact', 1)
        self.assertIn('은퇴', str(ex.exception))
        p.refresh_from_db()
        self.assertIsNotNone(p.retired_at)
        self.assertEqual(p.tp, 200)

    def test_pro_ages_each_season_and_retires_at_45(self):
        p = kid('노장')
        p.league, p.club, p.grade, p.grade_since, p.pending = 'kbo1', 'lg', 0, None, {}
        p.age, p.age_season = 30, 1
        p.save()
        C.progress(p, L.season_bounds(3)[0])
        p.refresh_from_db()
        self.assertEqual((p.age, p.age_season), (32, 3))
        p.age = 44
        p.save()
        C.progress(p, L.season_bounds(4)[0])
        p.refresh_from_db()
        self.assertIsNotNone(p.retired_at)
        self.assertEqual(p.career['retired']['age'], 45)
        self.assertIsNone(R.current(p.user_id))


class GameGrowthTests(TestCase):
    def test_playing_time_grows_related_stats(self):
        p = kid('출전왕')
        p.league, p.club, p.age, p.potential = 'kbo1', 'lg', 25, 99
        set_stats(p, 60)
        before = dict(p.stats)
        gains = C.game_xp(p, [{'g': 1, 'pa': 5, 'h': 3, 'd': 1, 'hr': 1, 'bb': 1, 'sb': 1}])
        self.assertGreater(gains['contact'], 0)
        self.assertGreater(gains['power'], gains['eye'])
        self.assertGreater(p.stats['speed'], before['speed'])
        self.assertLess(sum(gains.values()), 3)                       # 훈련 몇 번 분량 — 활동을 대신하지 않는다
        p.traits = ['learner']
        p.stats = dict(before)
        more = C.game_xp(p, [{'g': 1, 'pa': 5, 'h': 3, 'd': 1, 'hr': 1, 'bb': 1, 'sb': 1}])
        self.assertGreater(more['contact'], gains['contact'])

    def test_clutch_trait_changes_game_stats(self):
        p = kid('강심장', traits=['clutch'])
        self.assertEqual(C.game_stats(p)['clutch'], (p.stats['contact'] + p.stats['eye']) / 2 + 5)


class LeagueLifeTests(TestCase):
    """학생은 하루 한 경기, 상대는 같은 급 학교 · 프로는 같은 리그 구단 · 이정표·베스트 9·시상."""

    def setUp(self):
        cache.clear()

    def active(self, p, day):
        RookieLog.objects.create(player=p, kind='earn', source='checkin', ref=str(day), tp=20, text='출석', day=day)

    def pro(self, name, role='batter', league='kbo1', club='lg', position='SS', level=64):
        p = kid(name, role=role, position=position)
        p.league, p.club, p.grade, p.grade_since, p.pending, p.age, p.potential = league, club, 0, None, {}, 25, 99
        p.position = 'SP' if role == 'pitcher' else position
        p.save()
        set_stats(p, level)
        return p

    def test_amateur_plays_one_game_against_schools(self):
        p = kid('고교생')
        p.league, p.club, p.grade, p.age, p.pending = 'hs', '덕수고', 2, 17, {}
        p.save()
        set_stats(p, 45)
        self.active(p, D1)
        L.simulate_day(D1, rng=random.Random(3))
        games = list(RookieGame.objects.filter(player=p))
        self.assertLessEqual(len(games), 1)
        if games:
            self.assertIn(games[0].opponent, [s for _r, s in W.schools('hs')])
            self.assertNotEqual(games[0].opponent, '덕수고')
        st = RookieSeasonStat.objects.get(player=p)
        self.assertEqual((st.league, st.team, st.age), ('hs', '덕수고', 17))

    def test_midnight_checkin_waits_for_last_school_game(self):
        """자정에 출석해도 전날 경기를 치르기 전엔 학년이 넘어가지 않는다(2026-10-18 감사 C4)."""
        p = kid('자정중3')
        set_stats(p, 40)
        D = D1 + timedelta(days=5)
        p.league, p.club, p.grade, p.age = 'ms', '배명중', 3, 15
        p.grade_since, p.pending = D - timedelta(days=7), {'kind': 'apply', 'to': 'hs', 'choice': ''}
        p.settled_through, p.last_active = D - timedelta(days=1), D - timedelta(days=1)
        p.save()
        for d in (D - timedelta(days=2), D - timedelta(days=1)):
            self.active(p, d)
        with mock.patch('django.utils.timezone.localdate', return_value=D):
            R.award(p.user, 'checkin', 'midnight')
            p.refresh_from_db()
            self.assertEqual((p.league, p.grade), ('ms', 3))                  # 아직 경기 전
            call_command('rookie_daily', stdout=io.StringIO())
        p.refresh_from_db()
        self.assertEqual((p.league, p.grade), ('hs', 1))
        self.assertFalse(RookieGame.objects.filter(player=p, day=D - timedelta(days=1), league='hs').exists())
        self.assertTrue(RookieSeasonStat.objects.filter(player=p, league='ms').exists())

    def test_draft_waiting_players_sit_out(self):
        p = kid('졸업생')
        p.league, p.club, p.grade = 'hs', '덕수고', 3
        p.pending = {'kind': 'draft', 'deadline': (D1 + timedelta(days=3)).isoformat(), 'offer': None, 'abroad': {}}
        p.save()
        self.active(p, D1)
        L.simulate_day(D1, rng=random.Random(3))
        self.assertFalse(RookieGame.objects.filter(player=p).exists())

    def test_pro_opponents_milestones_and_best_nine(self):
        bat = self.pro('메이저타자', league='mlb', club='lad')
        pit = self.pro('메이저투수', role='pitcher', league='mlb', club='nyy', level=74)
        rival = self.pro('경쟁투수', role='pitcher', league='mlb', club='bos', level=50)
        for p in (bat, pit, rival):
            self.active(p, D1)
        L.simulate_day(D1, rng=random.Random(5))
        g = RookieGame.objects.filter(player=bat).first()
        self.assertIn(g.opponent, [c for c, _n, _col in W.MLB_TEAMS])
        self.assertTrue(RookieLog.objects.filter(player=bat, kind='mile', text__contains='프로 데뷔전').exists())
        nine = G.best_nine(D1, 'mlb')
        self.assertEqual(nine[0]['pos'], 'SP')
        self.assertIn(nine[0]['p'].pk, (pit.pk, rival.pk))                 # 그날 게임 스코어가 높은 쪽
        self.assertTrue(any(x.get('p') and x['p'].pk == bat.pk for x in nine))
        self.assertTrue(RookieLog.objects.filter(player=nine[0]['p'], text__contains='오늘의 베스트 9').exists())
        self.assertFalse(RookieLog.objects.filter(player=bat, text__contains='오늘의 베스트 9').exists())   # 혼자 뛴 자리는 남기지 않는다
        st = RookieSeasonStat.objects.get(player=pit)
        self.assertGreaterEqual(st.best_ovr, 74.0)

    def test_milestone_thresholds(self):
        p = self.pro('백호')
        before = {'g': 99, 'h': 99, 'hr': 49}
        texts = G.milestones(p, 'kbo1', D1, before, [{'g': 1, 'h': 2, 'hr': 1}], debut=False)
        self.assertIn('프로 통산 100안타', texts)
        self.assertIn('프로 통산 50홈런', texts)

    def test_awards_per_league(self):
        s = L.get_season(1)
        big = dict(g=140, pa=620, ab=540, h=180, d=35, t=3, hr=38, rbi=120, r=110, bb=70, hbp=5, so=90, sb=12, cs=3)
        ace = dict(g=28, gs=28, w=18, l=4, qs=22, outs=600, h=150, r=55, er=50, bb=40, hbp=3, so=210, hr=12, bf=800)
        rows = [(self.pro('엠엘비', league='mlb', club='lad'), big), (self.pro('사이영', 'pitcher', 'mlb', 'nyy'), ace),
                (self.pro('트리플', league='mlb_aaa', club='sea'), big)]
        hs = kid('고교에이스')
        hs.league, hs.club = 'hs', '덕수고'
        hs.save()
        rows.append((hs, dict(g=25, pa=100, ab=85, h=40, d=8, hr=6, rbi=30, r=25, bb=12, so=10)))
        for p, t in rows:
            RookieSeasonStat.objects.create(season=s, user=p.user, player=p, league=p.league, name=p.name, number=0,
                                            team=p.club, role=p.role, position=p.position, totals=t,
                                            war=L.war(p.role, p.position, t))
        awards = L.close_season(s)
        got = {(a.league, a.label): a.name for a in awards}
        self.assertEqual(got[('mlb', '사이영상')], '사이영')
        self.assertIn(('mlb', '실버슬러거 유격수'), got)
        self.assertNotIn(('mlb', '실버슬러거 투수'), got)               # 실버슬러거는 타자만
        self.assertEqual(got[('mlb_aaa', '트리플A MVP')], '트리플')
        self.assertEqual(got[('hs', '고교 최우수선수')], '고교에이스')
        self.assertEqual(got[('hs', '타격상')], '고교에이스')
        self.assertFalse(any(lg == 'kbo1' for lg, _l in got))

    def test_league_career_and_hall_of_fame(self):
        s = L.get_season(1)
        a = self.pro('전설', league='kbo1', club='lg')
        b = self.pro('현역', league='kbo1', club='kia')
        for p, war, best in ((a, 3.0, 82.0), (b, 6.0, 75.0)):
            RookieSeasonStat.objects.create(season=s, user=p.user, player=p, league='kbo1', name=p.name, team=p.club,
                                            role='batter', position='SS', totals={'g': 144, 'pa': 600, 'ab': 540, 'h': 160},
                                            war=war, best_ovr=best)
        RookieAward.objects.create(season=s, user=a.user, player=a, league='kbo1', kind='mvp', label='MVP', name=a.name,
                                   team='lg', role='batter', value='-')
        rows = G.league_career('kbo1')
        self.assertEqual([r['p'].name for r in rows], ['전설', '현역'])   # MVP 수가 먼저
        self.assertEqual(G.league_career('kbo1', retired_only=True), [])
        R.retire(a.user)
        self.assertEqual([r['p'].name for r in G.league_career('kbo1', retired_only=True)], ['전설'])

    def test_lifetime_splits_leagues(self):
        s = L.get_season(1)
        p = self.pro('평생')
        for lg, h in (('hs', 30), ('kbo2', 50), ('kbo1', 100)):
            RookieSeasonStat.objects.create(season=s, user=p.user, player=p, league=lg, name=p.name, team='lg',
                                            role='batter', totals={'g': 10, 'pa': 40, 'ab': 36, 'h': h}, war=1.0)
        life = G.lifetime(p)
        self.assertEqual([x['league'] for x in life['leagues']], ['kbo1', 'kbo2', 'hs'])
        self.assertEqual(life['pro']['v']['h'], 150)
        self.assertEqual(life['all']['v']['h'], 180)


class ScreenTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_apply_and_decide_through_views(self):
        p = kid('화면꼬마', region='서울')
        c = self.client
        c.force_login(p.user)
        r = c.get('/rookie/', HTTP_USER_AGENT=PC)
        self.assertContains(r, '중학야구 진학 지원')
        self.assertContains(r, '배명중')
        self.assertContains(r, '스카우트 평가')
        c.post('/rookie/apply/', {'school': '배명중'})
        p.refresh_from_db()
        self.assertEqual(p.pending['choice'], '배명중')
        r = c.post('/rookie/apply/', {'school': '없는중'}, follow=True)
        self.assertContains(r, '다시 골라')
        p.league, p.club, p.grade, p.age = 'hs', '덕수고', 3, 18
        p.grade_since = timezone.localdate() - timedelta(days=C.GRADE_DAYS)
        p.pending = {}
        p.save()
        set_stats(p, 66)
        with mock.patch('community.rookie_career.random.SystemRandom', return_value=Lucky()):
            for ua in (PC, MOBILE):
                r = c.get('/rookie/', HTTP_USER_AGENT=ua)
                self.assertContains(r, '신인 드래프트')
                self.assertContains(r, '해외 도전')
                self.assertContains(r, '대학 진학')
        r = c.post('/rookie/decide/', {'choice': 'npb'}, follow=True)
        p.refresh_from_db()
        self.assertEqual(p.league, 'npb2')
        self.assertContains(r, '일본 진출')
        self.assertContains(c.get(f'/rookie/p/{p.pk}/', HTTP_USER_AGENT=PC), '고졸 드래프트')

    def test_new_screens_render(self):
        p = kid('화면선수')
        p.league, p.club, p.grade, p.grade_since, p.pending, p.age = 'kbo1', 'lg', 0, None, {}, 25
        p.save()
        RookieLog.objects.create(player=p, kind='earn', source='checkin', ref='x', tp=20, text='출석', day=D1)
        L.simulate_day(D1, rng=random.Random(2))
        c = self.client
        with mock.patch('django.utils.timezone.localdate', return_value=D1 + timedelta(days=1)):
            for ua in (PC, MOBILE):
                for url, text in (('/rookie/league/?tab=best9&lg=kbo1', '오늘의 베스트 9'),
                                  ('/rookie/league/?tab=players', 'KBO'),
                                  ('/rookie/records/?view=career&lg=kbo1', '통산 순위'),
                                  ('/rookie/records/?view=hof', '명예의 전당'),
                                  ('/rookie/records/?view=highs&lg=kbo1&role=pitcher', '커리어하이'),
                                  (f'/rookie/p/{p.pk}/', '평생 통산')):
                    r = c.get(url, HTTP_USER_AGENT=ua)
                    self.assertContains(r, text, msg_prefix=url)
            self.assertContains(c.get('/rookie/records/', HTTP_USER_AGENT=PC), '최근 이정표')



class BalanceTests(TestCase):
    """2026-10-18 밸런스 개편 — 활동량이 드래프트를 가르고, 잠재력도 반영되고, 승격엔 체류·성적 과제가 붙는다."""

    def senior(self, name, level, pot=82):
        p = kid(name, potential=pot)
        p.league, p.club, p.grade, p.age = 'hs', '서울동산고', 3, 18
        p.save()
        set_stats(p, level)
        return p

    def test_draft_score_weighs_class_rank_and_potential(self):
        rng = Lucky()
        busy, idle = self.senior('부지런', 60), self.senior('출석만', 51)
        self.assertGreater(C.draft_score(busy, rng, 0)[0], C.draft_score(idle, rng, 0)[0] + 8)
        star = self.senior('천재', 55, pot=92)
        plain = self.senior('평범', 55, pot=74)
        self.assertGreater(C.draft_score(star, rng, 0)[0], C.draft_score(plain, rng, 0)[0] + 5)
        self.assertEqual(C.draft_round(C.draft_score(idle, rng, 0)[0]) or 99, max(C.draft_round(C.draft_score(idle, rng, 0)[0]) or 99, 7))

    def test_student_titles_are_relative_to_class(self):
        mean, sd = C.CLASS[17]
        self.assertEqual(R.title('batter', 'hs', mean, 17), '')
        self.assertEqual(R.title('batter', 'hs', mean + 1.0 * sd, 17), '유망주')
        self.assertEqual(R.title('batter', 'hs', mean + 1.7 * sd, 17), '특급 유망주')

    def test_promotion_needs_stay_and_recent_form(self):
        p = kid('승격대기')
        p.league, p.club, p.grade, p.grade_since, p.pending, p.age = 'kbo2', 'lg', 0, None, {}, 20
        p.league_since = timezone.localdate() - timedelta(days=3)
        p.save()
        set_stats(p, 66)
        gate = C.promotion_gate(p)
        self.assertEqual((gate['stay_need'], gate['stay_left']), (C.MIN_STAY, C.MIN_STAY - 3))
        self.assertFalse(gate['mission']['ok'])                              # 최근 경기 없음
        with self.assertRaises(R.GameError) as ex:
            R.promotion_test(p.user)
        self.assertIn('일을 뛴 뒤', str(ex.exception))
        p.league_since = timezone.localdate() - timedelta(days=20)
        p.save()
        s = L.get_season(1)
        for i in range(6):
            RookieGame.objects.create(season=s, player=p, league='kbo2', day=timezone.localdate() - timedelta(days=1 + i), no=i + 1,
                                      opponent='kt', line={'g': 1, 'pa': 5, 'ab': 4, 'h': 2, 'd': 1, 'bb': 1}, summary='-')
        gate = C.promotion_gate(p)
        self.assertTrue(gate['ok'], gate)
        p.career = dict(p.career, draft_univ={'round': 3})
        self.assertEqual(C.promotion_gate(p)['stay_need'], C.MIN_STAY_COLLEGE)

    def test_upkeep_counts_aging_and_caps(self):
        p = kid('노장유지')
        p.league, p.club, p.age, p.potential = 'kbo1', 'lg', 36, 90
        p.save()
        set_stats(p, 80)
        young = kid('청년유지')
        young.league, young.club, young.age, young.potential = 'kbo1', 'lg', 26, 90
        young.save()
        set_stats(young, 80)
        self.assertGreater(R.upkeep_of(p)[0], R.upkeep_of(young)[0])          # 노쇠·낮은 효율이 유지비에 들어간다
