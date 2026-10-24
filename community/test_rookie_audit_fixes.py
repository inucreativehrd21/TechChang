"""2026-10-24 점검에서 나온 운영 결함의 회귀 검사 — 로컬 SQLite 가 못 잡는 쪽은 주석으로 남겨요."""
import random
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from . import rookie_extreme as E
from . import rookie_lite as X
from . import rookie_universe as U
from .test_rookie_universe import fake

MEMBER = dict(id='lite:99', name='실제회원', age=24, own_age=24, same_age=True, league='kbo1', league_label='KBO 1군',
              club='lg', club_label='LG', ovr=70, war=3.0, own_war=1.0, line='타율 .300', role='batter',
              url='/rookie/lite/c/99/', source='회원 커리어', season=3, metrics=[])


class RivalNamesTests(SimpleTestCase):
    """기사·면담·콜업 판정에는 실제 회원 이름이 들어가면 안 돼요 — 도전 장면만 공개 회원 기록을 써요."""

    def test_default_rival_is_always_simulated(self):
        with mock.patch('community.rookie_peers.comparisons', return_value=[MEMBER]):
            r = U.rival_report(fake(), 'kbo1', 'down')
        self.assertEqual(r['source'], 'simulation')
        self.assertNotEqual(r['name'], MEMBER['name'])

    def test_make_rival_never_uses_member_record(self):
        with mock.patch('community.rookie_peers.comparisons', return_value=[MEMBER]):
            r = X.make_rival(fake(), 'kbo1', 'up', random.Random(1))
        self.assertEqual(r['source'], 'simulation')

    def test_challenge_uses_member_record_only_in_the_same_league(self):
        p = fake()
        with mock.patch('community.rookie_peers.comparisons', return_value=[MEMBER]):
            same = U.rival_report(p, 'kbo1', 'down', members=True)
            other = U.rival_report(p, 'kbo2', 'down', members=True)
        self.assertEqual((same['source'], same['name']), ('member_record', MEMBER['name']))
        self.assertEqual(other['source'], 'simulation')                     # 다른 리그 기록으로 강도를 어림하지 않아요


@override_settings(ROOKIE_EXTREME_PREVIEW=True)
class ExtremeActiveDutyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('army-preview', password=None, is_staff=True)

    def test_event_is_reissued_for_the_year_after_active_duty(self):
        rng = random.Random(4)
        c = X.create(self.user, mode='extreme', name='입대', role='batter', position='SS',
                     style=next(iter(X.STYLES['batter'])), region='서울', team='lg', rng=random.Random(41))
        c.league, c.club, c.age, c.grade = 'kbo1', 'lg', 24, 0
        c.save()
        c.pending = {'kind': 'decision', 'what': 'military', 'forced': False}
        year = c.year
        X.decide(c, 'military', 'active', rng)
        self.assertEqual(c.year, year + 2)
        self.assertEqual(c.pending['kind'], 'plan')
        pending = (c.flags['extreme'].get('pending') or {})
        # 입대 전 연도로 저장된 사건이 남으면 답도 시즌 시작도 막혀 커리어가 멈춰요.
        self.assertIn(pending.get('year', c.year), (c.year,))
        if pending:
            E.apply_choice(c, pending['id'], E.event_view(c)['choices'][0]['key'], random.Random(2))


class StoryScenePlacementTests(SimpleTestCase):
    def test_story_scene_height_is_not_fixed(self):
        """협상 계약서처럼 긴 장면이 고정 높이 + overflow:hidden 에 잘려 선택 버튼에 닿지 못하던 결함(2026-10-24) — 짧으면 채우고 길면 바깥 틀이 스크롤해야 해요."""
        import pathlib
        css = (pathlib.Path(__file__).resolve().parent.parent / 'static' / 'css' / 'rookie-flow.css').read_text(encoding='utf-8')
        rule = next(line for line in css.splitlines() if '.rl-main-screen > .rs-story-scene {' in line)
        self.assertNotIn('height: calc(var(--rl-scene-height)', rule.replace('min-height: calc(var(--rl-scene-height)', ''))
        self.assertIn('min-height: calc(var(--rl-scene-height)', rule)
