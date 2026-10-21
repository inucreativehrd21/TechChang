"""점수·아웃·출루 방식과 맞는 중계, 구원 보직, 과거 문구 표시를 검증한다."""
import copy
import random
from types import SimpleNamespace
from unittest import mock

from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from . import rookie_lite as X
from . import rookie_sim as M
from . import rookie_story as S
from . import rookie_world as W
from .rookie_text import display


def player(role='batter'):
    return SimpleNamespace(pk=77, name='검토선수', flags={}, year=1, age=24, role=role,
                           position='SS' if role == 'batter' else 'SP', club='lg', league='kbo1',
                           ovr=64, potential=76, traits=[], style='contact' if role == 'batter' else 'fire',
                           stats={k: 64 for k in (M.BAT if role == 'batter' else M.PIT)})


class BaseballTextTests(SimpleTestCase):
    def test_league_names_distinguish_majors_from_minors_without_changing_codes(self):
        self.assertEqual(W.short('kbo1'), 'KBO')
        self.assertEqual(W.short('npb1'), 'NPB')
        self.assertEqual(W.league('mlb_a')['name'], '마이너리그 싱글A')
        self.assertEqual(W.system_of('mlb_a'), 'mlb')
        self.assertEqual(W.next_league('kbo2'), 'kbo1')

    def test_setup_and_middle_relief_are_distinct_and_rp_is_not_always_closer(self):
        self.assertEqual(M.PIT_ROLES['win'], '중간계투')
        self.assertEqual(M.PIT_ROLES['setup'], '셋업맨')
        self.assertEqual(dict(X.BENCH)['RP'], '구원 투수')

    def test_old_text_is_normalized_without_rewriting_or_disabling_escaping(self):
        old = 'KBO 1군 / NPB 1군 / MLB 싱글A <script>alert(1)</script>'
        rendered = Template('{% load rookie_tags %}{{ value|baseball_text }}').render(Context({'value': old}))
        self.assertIn('KBO / NPB / 마이너리그 싱글A', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('KBO 1군', old)
        self.assertEqual(display(display(old)), display(old))

    def test_existing_story_json_uses_current_league_labels_on_render(self):
        event = dict(kind='manager', id='old-event', background='manager-office',
                     title='KBO 1군 콜업', text='NPB 1군과 MLB 트리플A', choices=[])
        before = copy.deepcopy(event)
        html = render_to_string('community/games/_rookie_story_scene.html', {'e': event})
        self.assertIn('KBO 콜업', html)
        self.assertIn('NPB와 마이너리그 트리플A', html)
        self.assertNotIn('KBO 1군', html)
        self.assertEqual(event, before)

    def test_pitcher_lead_situation_does_not_say_the_score_is_tied(self):
        event = S.encounter(player('pitcher'), 'highlight', random.Random(4))
        self.assertIn('한 점 앞선', event['text'])
        self.assertNotIn('동점', event['text'])
        self.assertIn('동점', S.encounter(player(), 'highlight', random.Random(4))['text'])

    def test_early_go_ahead_hit_is_not_called_game_winner_before_later_loss(self):
        p = player()
        moment = X.make_moment(p, 'series', '한국시리즈 최종 승부', '10월', random.Random(2))
        moment['sit'].update(need='run', inning='8회초', outs=1, bases=[False, False, True], score='2 : 2')
        with mock.patch.object(M, '_pick', return_value='HR'):
            result = X.play_moment(p, moment, 'short', random.Random(2))
        self.assertIn('앞서가는 2점 홈런', result['text'])
        won, text = X.moment_outcome(moment, result, mock.Mock(random=lambda: .99))
        self.assertFalse(won)
        self.assertNotIn('결승', text)

    def test_hit_by_pitch_is_not_narrated_as_walk(self):
        for role in ('batter', 'pitcher'):
            p = player(role)
            moment = X.make_moment(p, 'series', '한국시리즈', '10월', random.Random(3))
            moment['sit']['need'] = 'run' if role == 'batter' else 'hold'
            choice = 'short' if role == 'batter' else 'fast'
            with mock.patch.object(M, '_pick', return_value='HBP'):
                result = X.play_moment(p, moment, choice, random.Random(3))
            self.assertIn('몸에 맞는 공', result['text'])
            self.assertNotIn('볼넷', result['text'])

    def test_mentor_hints_match_the_batter_and_pitcher_stats(self):
        bat = X.event_view(player(), 'mentor')['choices']
        pit = X.event_view(player('pitcher'), 'mentor')['choices']
        self.assertIn('선구안과 컨택', bat[0]['hint'])
        self.assertIn('훈련 리듬', bat[0]['hint'])
        self.assertIn('주루', bat[1]['hint'])
        self.assertIn('신뢰', bat[1]['hint'])
        self.assertIn('멘탈과 제구', pit[0]['hint'])

    def test_series_result_uses_competition_name_without_scene_suffix(self):
        self.assertEqual(X.moment_result_text(dict(kind='series', stage='한국시리즈 최종 승부', won=True)), '한국시리즈 우승!')
