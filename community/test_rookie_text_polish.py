"""2026-10-24 문구 점검 반영 — 조사·숫자 표기·이름 안전망·어체를 지키는지 확인한다."""
import random
from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from . import rookie_league as L
from . import rookie_lite as X
from . import rookie_reports as Reports
from . import rookie_sim as M
from . import rookie_story as S
from . import rookie_universe as U
from . import rookie_world_hub as Hub
from .models import RookieGame
from .rookie_text import is_real_person, josa
from .test_rookie_league import player
from .test_rookie_lite import new, pro


class JosaModuleTests(SimpleTestCase):
    def test_josa_lives_in_rookie_text_and_lite_still_exports_it(self):
        self.assertIs(X.josa, josa)
        self.assertEqual(josa('체인지업', '을/를'), '을')
        self.assertEqual(josa('슬라이더', '이/가'), '가')
        self.assertEqual(josa('체인지업', '으로/로'), '으로')
        self.assertEqual(josa('두산', '와/과'), '과')


class PitchTextTests(TestCase):
    def test_pitch_names_get_the_right_particle_in_the_moment_text(self):
        c = pro('구종', seed=5, ovr=70.0, age=24)
        seen = set()
        for seed in range(60):
            m = X.make_moment(c, 'series', '한국시리즈 7차전', '10월', random.Random(seed))
            view = X.moment_view(c, dict(m, opp=dict(m['opp'], pitch='체인지업')))
            text = ' '.join([str(view['opp'].get('scout', ''))] + [x['label'] + x['hint'] for x in view['choices']]
                            + [str(m['opp'].get('scout', ''))] + [x[1] + x[3] for x in m['choices']])
            seen.add(text)
            for wrong in ('체인지업를', '체인지업가', '체인지업로'):
                self.assertNotIn(wrong, text)
        self.assertTrue(any('체인지업' in t for t in seen))


class PitcherRoleLogTests(SimpleTestCase):
    def test_role_move_text_does_not_depend_on_the_final_consonant(self):
        arm = {'velocity': 80, 'control': 80, 'breaking': 80, 'stamina': 30, 'mental': 80}
        weak = {'velocity': 30, 'control': 30, 'breaking': 30, 'stamina': 30, 'mental': 30}
        bad = [{'outs': 9, 'er': 8} for _ in range(2)]
        reasons = []
        for cur in ('chase', 'win', 'setup', 'closer'):
            reasons.append(M.pitcher_role(cur, arm, 65, [])[2])
            reasons.append(M.pitcher_role(cur, weak, 65, bad)[2])
        reasons = [r for r in reasons if r]
        self.assertTrue(reasons)
        for why in reasons:
            if '보직' in why:
                self.assertRegex(why, r'보직으로 (올라갔어요|내려갔어요)')
            self.assertNotRegex(why, r'(패전조|추격조|중간계투|마무리|셋업맨)(으로|로) ')


class StoryChangeTests(SimpleTestCase):
    def player(self):
        return SimpleNamespace(pk=1, flags={}, name='선수')

    def test_change_drops_the_trailing_period_and_uses_the_minus_sign(self):
        text = S.change(self.player(), '선발 수업을 시작했어요. 불펜 등판을 이어가며 다음 평가를 준비해요.', discipline=3, confidence=-2)
        self.assertEqual(text, '선발 수업을 시작했어요. 불펜 등판을 이어가며 다음 평가를 준비해요 — 자기 관리 +3 · 자신감 −2')
        self.assertNotIn('. —', text)
        self.assertNotIn('-2', text)

    def test_change_without_deltas_drops_the_period_too(self):
        self.assertEqual(S.change(self.player(), '그대로예요.'), '그대로예요')


class _ForcedRandom(random.Random):
    """앞에서부터 정해 둔 글자를 choice 로 돌려주고, 다 쓰면 시드 난수로 이어 간다."""
    picks = ()

    def choice(self, seq):
        if self.picks:
            return self.picks.pop(0)
        return super().choice(seq)


def _Forced(picks):
    rng = _ForcedRandom(0)
    rng.picks = list(picks)
    return rng


class RivalNameSafetyTests(SimpleTestCase):
    def test_the_whole_korean_rival_name_space_never_yields_a_blocked_or_famous_name(self):
        bad_found = 0
        for s in X.SURNAMES:
            for a in X.GIVEN:
                for b in X.GIVEN:
                    if is_real_person(s + a + b):
                        bad_found += 1
                    name = X.rival_name('kbo1', _Forced([s, a, b]))
                    self.assertFalse(is_real_person(name), name)
                    self.assertEqual(len(name), 3)
        self.assertGreaterEqual(bad_found, 8)            # 박지원·이준석·최규하·김하성·류현진·박찬호·송진우·이호준

    def test_known_collisions_are_redrawn_and_stay_deterministic_per_seed(self):
        for real in ('박지원', '이준석', '최규하', '김하성', '류현진', '박찬호', '송진우', '이호준'):
            self.assertTrue(is_real_person(real), real)
            name = X.rival_name('kbo1', _Forced(list(real)))
            self.assertNotEqual(name, real)
            self.assertEqual(name, X.rival_name('kbo1', _Forced(list(real))))
        self.assertEqual(X.rival_name('kbo1', random.Random(7)), X.rival_name('kbo1', random.Random(7)))

    def test_fallback_name_is_safe_and_fixed(self):
        class Always(random.Random):
            def __init__(self):
                super().__init__(0)
                self.n = 0

            def choice(self, seq):
                self.n += 1
                return '박지원'[(self.n - 1) % 3]

        name = X.rival_name('kbo1', Always())
        self.assertFalse(is_real_person(name))
        self.assertEqual(name, X._safe_rival_name())
        self.assertFalse(is_real_person(X._safe_rival_name()))

    def test_world_hub_rosters_never_use_blocked_or_famous_names(self):
        for league in ('kbo1', 'kbo2', 'hs', 'univ', 'little'):
            for club in ('lg', 'doosan', 'kia', 'ssg', 'nc', 'hanwha', 'lotte'):
                for year in (1, 2, 3):
                    names = [p['name'] for p in Hub.roster(league, club, year)]
                    self.assertEqual(len(names), len(set(names)))
                    self.assertEqual([n for n in names if is_real_person(n)], [])

    def test_hub_replaces_a_colliding_name_without_changing_the_rest(self):
        original = Hub.roster('kbo1', 'lg', 1)
        real = original[0]['name']
        from unittest import mock
        with mock.patch.object(Hub, 'is_real_person', side_effect=lambda n: n == real):
            patched = Hub.roster('kbo1', 'lg', 1)
        self.assertNotEqual(patched[0]['name'], real)
        self.assertEqual([p['name'] for p in patched[1:]], [p['name'] for p in original[1:]])


class RateFormatTests(SimpleTestCase):
    def test_rate_style_for_ops_and_win_pct(self):
        self.assertEqual(L.rate(0.812), '.812')
        self.assertEqual(L.rate(1.0), '1.000')
        self.assertEqual(L.rate(1.012), '1.012')
        self.assertEqual(M._rate(0.8), '.800')

    def test_universe_uses_the_shared_rate_helper(self):
        self.assertIs(U.L, L)


class AwakenFailureTextTests(TestCase):
    def test_failure_text_names_the_real_penalty_for_both_roles(self):
        rng = random.Random(3)
        for role, label in (('batter', '선구안'), ('pitcher', '멘탈')):
            c = new('각성' + role, role=role, position='SS' if role == 'batter' else 'SP', seed=62)
            c.league, c.club, c.grade, c.age = 'kbo1', 'lg', 0, 31
            c.stats = {k: 60.0 for k in c.stats}
            c.ovr = 60.0
            c.pending = {'kind': 'decision', 'what': 'awaken', 'odds': 0.0}
            msg = X.decide(c, 'awaken', 'try', rng)
            fx = c.flags['awaken_fx']
            self.assertFalse(fx['ok'])
            self.assertIn(label, fx['fail_text'])
            self.assertIn('1 빠졌어요', fx['fail_text'])
            self.assertIn(f'{X.AWAKEN_WAIT}시즌 뒤', fx['fail_text'])
            self.assertIn('부상 위험', fx['fail_text'])
            self.assertIn(f'{label} −1', msg)


class RetireTextTests(TestCase):
    def test_age_retirement_uses_the_limit_constant(self):
        c = pro('은퇴문구', seed=11, ovr=60.0, age=43)
        limit = X.Bloom.retirement_limit(c, X.RETIRE_AT)
        c.pending = {'kind': 'retired', 'why': '나이'}
        self.assertEqual(X.retire(c, '나이'), f'{limit}세, 유니폼을 벗었어요')
        c.pending = {'why': '나이'}
        self.assertIn(f'…{limit}세까지 뛰었다', X.retire_headline(c, 12)['title'])
        self.assertIn('12시즌 선수 생활 마침표', X.retire_headline(c, 12)['title'])
        self.assertNotIn('0시즌', X.retire_headline(c, 0)['title'])

    def test_quit_message_for_a_brand_new_career(self):
        c = pro('초보', seed=12, ovr=60.0, age=18)
        with self.assertRaises(X.LiteError) as ctx:
            X.check_quit(c)
        self.assertIn('아직 한 시즌도 뛰지 않았어요', str(ctx.exception))
        self.assertNotIn('0시즌', str(ctx.exception))


class DailyReportToneTests(TestCase):
    def test_report_is_in_haeyo_style_and_uses_dot_style_rates(self):
        p = player('톤타자')
        day = timezone.localdate() - timedelta(days=1)
        empty = Reports.daily(p, day)
        RookieGame.objects.create(player=p, season=L.get_season(1), league='kbo1', day=day, no=1, opponent='kt',
                                  summary='4타수 2안타', line=dict(g=1, pa=5, ab=4, h=2, hr=1, bb=1, so=3, rbi=3))
        report = Reports.daily(p, day)
        pit = player('톤투수', role='pitcher', position='SP')
        RookieGame.objects.create(player=pit, season=L.get_season(1), league='kbo1', day=day, no=1, opponent='kt',
                                  summary='6이닝', line=dict(g=1, outs=18, h=4, bb=2, so=7, er=1, r=1, np=90, bf=24))
        preport = Reports.daily(pit, day)
        for r in (empty, report, preport):
            text = ' '.join([r['summary'], r.get('trend', ''), r.get('sample_note', ''), *r['strengths'], *r['tasks']])
            self.assertNotIn('습니다', text)
            self.assertNotIn('입니다', text)
        ops = dict(report['metrics'])['OPS']
        self.assertRegex(ops, r'^(\.\d{3}|\d\.\d{3})$')
        self.assertNotRegex(report['trend'], r'OPS 0\.')
