"""2026-10-24 문구 점검 2차 — 역할별 능력 이름, '-0' 표기, None 표시, 0 변화 생략, 라벨 없는 숫자 등을 지키는지 확인한다."""
import math
from datetime import timedelta
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from . import rookie as R
from . import rookie_extreme as E
from . import rookie_league as L
from . import rookie_lite as X
from . import rookie_reports as Reports
from . import rookie_story as S
from .models import RookieGame, RookieLog
from .rookie_text import nz, signed
from .test_rookie_league import player
from .test_rookie_lite import pro


class SignedZeroTests(SimpleTestCase):
    def test_rounding_to_zero_never_prints_a_sign(self):
        self.assertEqual(signed(-0.004, 2), '0')
        self.assertEqual(signed(0.0), '0')
        self.assertEqual(signed(-0.04), '0')
        self.assertEqual(signed(0.17, 2), '+0.17')
        self.assertEqual(signed(-1.25, 2), '-1.25')
        self.assertEqual(math.copysign(1, nz(round(-0.04, 1))), 1.0)
        self.assertEqual(nz(-0.0), 0.0)
        self.assertEqual(nz(1.5), 1.5)

    def test_war_of_a_wash_season_is_plain_zero(self):
        self.assertEqual(str(L.war('pitcher', 'SP', {})), '0.0')
        self.assertEqual(str(L.war('batter', 'SS', {})), '0.0')


class MindRoleTests(TestCase):
    def test_confidence_names_only_the_abilities_that_apply_to_the_role(self):
        bat, pit = pro('타자마음', seed=2), pro('투수마음', seed=3)
        pit.role = 'pitcher'
        self.assertEqual(S.view(bat)['affects'], '컨택·선구안')
        self.assertEqual(S.view(pit)['affects'], '제구·멘탈')
        # 실제로 보정을 받는 능력과 화면 문구가 같은 능력이어야 한다
        base = {k: 50.0 for k in ('contact', 'eye', 'control', 'mental', 'power')}
        bat.flags = dict(bat.flags, confidence=90)
        boosted = S.game_stats(bat, base)
        self.assertGreater(boosted['contact'], 50)
        self.assertGreater(boosted['eye'], 50)
        self.assertEqual(boosted['control'], 50)
        self.assertEqual(boosted['power'], 50)

    def test_mind_panel_text_and_zero_bonus(self):
        bat = pro('타자패널', seed=4)
        view = S.view(bat)
        self.assertEqual(view['bonus'], '0')                      # 자신감 50 → '+0' 도 '-0' 도 아니다
        html = render_to_string('community/games/_rookie_mind.html', {'mind': view})
        self.assertIn('자신감에 따른 컨택·선구안 0', html)
        self.assertNotIn('타격 접근', html)
        self.assertNotIn('제구', html)


class DailyBodyTextTests(TestCase):
    def test_aging_sentence_names_the_role_body_abilities(self):
        bat = player('노쇠타자')
        pit = player('노쇠투수', role='pitcher', position='SP')
        self.assertEqual(R.condition(bat)['body'], '파워·주루')
        self.assertEqual(R.condition(pit)['body'], '구속·체력')
        self.assertEqual(R.condition(bat)['aging_age'], 33)


class ExtremeEffectLineTests(SimpleTestCase):
    def test_zero_items_are_left_out(self):
        text = E.effect_line(.04, 0, [('신뢰', 0), ('존중', 4), ('경쟁', 0)])
        self.assertEqual(text, '훈련 효과 +4% · 존중 +4')
        self.assertNotIn('+0', text)

    def test_risk_uses_percent_points_in_words(self):
        text = E.effect_line(0, .02, [])
        self.assertIn('%포인트', text)
        self.assertNotIn('%p', text)
        import inspect
        self.assertNotIn('%p', inspect.getsource(E.event_view))      # 실패 효과 안내문도 같은 표기

    def test_empty_list_says_nothing_changes(self):
        self.assertEqual(E.effect_line(0, 0, [('신뢰', 0)]), '변화 없음')

    def test_labels_and_separator_are_configurable(self):
        text = E.effect_line(-.2, .06, [('감독 신뢰', -7)], '훈련 보정', '부상 위험', ', ')
        self.assertEqual(text, '훈련 보정 -20%, 부상 위험 +6%포인트, 감독 신뢰 -7')


class BatterLabelTests(TestCase):
    def test_batter_season_line_starts_with_a_labelled_average(self):
        totals = dict(g=100, pa=400, ab=350, h=100, hr=10, rbi=50, bb=40, so=60)
        self.assertRegex(X._short('batter', totals), r'^타율 \.\d{3} \d+홈런 \d+타점 OPS ')
        self.assertTrue(L.bat_val(SimpleNamespace(totals=totals, war=1.2)).startswith('타율 '))

    def test_pitcher_member_record_shows_numbers_not_a_bare_decision(self):
        text = L.pit_season_summary(dict(outs=264, h=63, r=18, so=73, w=13, l=4, hld=2))
        self.assertIn('13승 4패', text)
        self.assertIn('2홀드', text)
        self.assertNotIn('(', text)
        # 한 경기 줄은 그대로 (승)
        self.assertTrue(L.pit_summary(dict(outs=18, h=4, r=1, so=7, w=1)).endswith('(승)'))


class AwardChipTests(SimpleTestCase):
    def test_league_name_is_not_printed_twice(self):
        from .views.rookie_lite_views import _award_sum
        seasons = [
            SimpleNamespace(league='kbo2', age=20, awards=[{'kind': 'minor', 'label': '퓨처스 MVP'}]),
            SimpleNamespace(league='mlb_aaa', age=22, awards=[{'kind': 'minor', 'label': '트리플A MVP'}]),
            SimpleNamespace(league='npb2', age=22, awards=[{'kind': 'minor', 'label': 'NPB 2군 MVP'}]),
            SimpleNamespace(league='hs', age=17, awards=[{'kind': 'minor', 'label': '고교 최우수선수'}]),
            SimpleNamespace(league='kbo1', age=25, awards=[{'kind': 'mvp', 'label': 'MVP'}]),
        ]
        c = SimpleNamespace(pending={}, seasons=SimpleNamespace(all=lambda: seasons))
        labels = [a['label'] for a in _award_sum(c)]
        self.assertEqual(sorted(labels), sorted(['KBO MVP', '퓨처스 MVP', '트리플A MVP', 'NPB 2군 MVP', '고교 최우수선수']))


class TemplateDetailTests(SimpleTestCase):
    def test_missing_opponent_level_shows_dash_not_none(self):
        row = dict(code='mid', label='중위', level=None, pa=3, avg_text='.250', obp_text='.300', hr=0, bb=0, so=1, note='')
        html = render_to_string('community/games/_rookie_line.html', {'x': {'splits': [row], 'v': {}}, 'role': 'batter'})
        self.assertNotIn('None', html)
        self.assertIn('<td>-</td>', html)

    def test_choice_card_button_does_not_repeat_the_title(self):
        html = render_to_string('community/games/_lite_choice.html', {
            'what': 'military', 'choice': 'sangmu', 'label': '상무에 입대할게요', 'hint': '', 'button': '입대하기'})
        self.assertEqual(html.count('상무에 입대할게요'), 1)
        self.assertIn('입대하기', html)
        plain = render_to_string('community/games/_lite_choice.html', {'what': 'x', 'choice': 'y', 'label': '가요'})
        self.assertIn('고르기', plain)

    def test_negotiation_terms_do_not_repeat_the_headline_amount(self):
        terms = dict(years=3, annual=93_2573, minor_annual=0, veto=True, split=False, player_opt_out=False, service=0, risk=10)
        full = render_to_string('community/games/_rookie_contract_terms.html', {'contract_terms': terms})
        brief = render_to_string('community/games/_rookie_contract_terms.html', {'contract_terms': terms, 'brief': True})
        self.assertIn('3년 남음', full)
        self.assertNotIn('3년 남음', brief)
        self.assertIn('계약서의 작은 글씨', brief)

    def test_on_hold_report_shows_one_block(self):
        report = dict(day=timezone.localdate(), player=SimpleNamespace(name='가', role='batter', pk=1), team='LG', summary='x',
                      metrics=[], strengths=['평가는 보류해요.'], tasks=['원인을 단정하지 않아요.'], trend='', evidence='e',
                      on_hold=True, member_history=[])
        html = render_to_string('community/games/_rookie_daily_report.html', {'report': report})
        self.assertIn('관찰 보류', html)
        self.assertNotIn('긍정적인 관찰', html)
        self.assertNotIn('보완 과제', html)


class ReportSampleTests(TestCase):
    def test_no_game_day_is_on_hold_and_tiny_samples_are_not_judged(self):
        p = player('보류타자')
        day = timezone.localdate() - timedelta(days=1)
        self.assertTrue(Reports.daily(p, day)['on_hold'])
        RookieGame.objects.create(player=p, season=L.get_season(1), league='kbo1', day=day, no=1, opponent='kt',
                                  summary='1타수 무안타', line=dict(g=1, pa=1, ab=1, h=0, so=1))
        report = Reports.daily(p, day)
        self.assertNotIn('삼진 비율', ' '.join(report['tasks']))
        self.assertFalse(report.get('on_hold'))


class RecentLogTests(TestCase):
    def test_repeated_zero_tp_rows_collapse_into_one_line(self):
        p = player('한도')
        today = timezone.localdate()
        RookieLog.objects.filter(player=p).delete()
        for i in range(5):
            RookieLog.objects.create(player=p, kind='earn', source='comment', tp=0, day=today,
                                     text='댓글·답변 +0 TP (보유 한도 500 TP)')
        RookieLog.objects.create(player=p, kind='train', tp=0, day=today, text='훈련')
        logs = R.recent_logs(p)
        zero = [x for x in logs if x.kind == 'earn']
        self.assertEqual(len(zero), 1)
        self.assertIn('5번', zero[0].text)
        self.assertNotIn('+0 TP', ' '.join(x.text for x in logs))


from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, override_settings

PC = 'Mozilla/5.0 Windows NT 10.0 Chrome/130'


@override_settings(ROOKIE_EXTREME_PREVIEW=True)
class ExtremeScreensTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('polish2-preview', password=None, is_staff=True)

    def test_preview_event_card_and_history_omit_zero_changes(self):
        import random
        c = X.create(self.user, mode='extreme', name='시제품', role='batter', position='SS',
                     style=next(iter(X.STYLES['batter'])), region='서울', team='lg', rng=random.Random(41))
        client = Client(HTTP_USER_AGENT=PC)
        client.force_login(self.user)
        page = client.get('/rookie/extreme/lab/').content.decode()
        self.assertNotIn('%p', page)
        self.assertNotRegex(page, r'[+\-]0%')
        self.assertNotRegex(page, r'(신뢰|존중|경쟁) \+0')
        event = E.event_view(c)
        E.resolve(c.pk, self.user, event['id'], event['choices'][-1]['key'], random.Random(2))
        after = client.get('/rookie/extreme/lab/').content.decode()
        self.assertNotIn('%p', after)
        self.assertNotRegex(after, r'(신뢰|존중|경쟁|훈련 보정|부상 위험) [+\-]0(?![\d.])')
