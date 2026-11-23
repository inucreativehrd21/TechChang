"""테크창 삼국지 규칙 엔진·판 생성기 검사(DB 없이)."""
import json
from datetime import date, timedelta

from django.test import SimpleTestCase

from community import samguk_board as B
from community import samguk_data as D
from community import samguk_rules as R

DAY = date(2026, 11, 20)


def _first_attack(board, state):
    """시작 도시에서 칠 수 있는 첫 성과 출정 행동."""
    src = state['start']
    for dst in R.links(state, src):
        if state['cities'][dst]['owner'] != R.ME:
            officers = state['cities'][src]['officers'][:3]
            return {'kind': 'attack', 'from': src, 'to': dst, 'officers': officers,
                    'troops': state['cities'][src]['troops']}
    return None


class BoardTests(SimpleTestCase):
    def test_same_day_same_board(self):
        self.assertEqual(B.generate(DAY), B.generate(DAY))
        self.assertNotEqual(B.generate(DAY), B.generate(DAY + timedelta(days=1)))

    def test_board_is_json(self):
        board = B.generate(DAY)
        self.assertEqual(json.loads(json.dumps(board)), board)

    def test_board_shape(self):
        for i in range(60):
            board = B.generate(DAY + timedelta(days=i))
            self.assertEqual(len(board['starts']), 3)
            self.assertIn(board['event'], B.EVENTS)
            self.assertGreaterEqual(len(board['lords']), 5)
            placed = [o for v in board['cities'].values() for o in v['officers']]
            placed += [o for s in board['starts'] for o in s['officers']]
            placed += [o for codes in board['free'].values() for o in codes]
            self.assertEqual(len(placed), len(set(placed)), f'{board["date"]}: 한 판에 같은 장수가 둘')
            for s in board['starts']:
                self.assertEqual(board['cities'][s['city']]['owner'], R.NONE)
                self.assertEqual(len(s['officers']), 2)

    def test_every_general_within_seven_days(self):
        seen = set()
        for i in range(7):
            board = B.generate(B.EPOCH + timedelta(days=i))
            seen.update(o for v in board['cities'].values() for o in v['officers'])
            seen.update(o for s in board['starts'] for o in s['officers'])
            seen.update(o for codes in board['free'].values() for o in codes)
        self.assertEqual(set(D.GENERAL) - seen, set())

    def test_boss_joins_as_lord(self):
        board = B.generate(DAY, boss={'name': '테스터', 'officers': ['lubu', 'chengong'], 'troops': 5000})
        self.assertIn('boss', board['lords'])
        city = next(c for c, v in board['cities'].items() if v['owner'] == 'boss')
        self.assertEqual(board['cities'][city]['officers'], ['lubu', 'chengong'])


class RulesTests(SimpleTestCase):
    def setUp(self):
        self.board = B.generate(DAY)
        self.state = R.new_run(self.board, 'wei', 0, seed=1234)

    def test_new_run(self):
        s = self.state
        self.assertEqual(R.ap_left(s), R.AP_BASE)
        self.assertEqual(s['food'], R.START_FOOD)
        self.assertEqual(R.mine(s), [s['start']])
        self.assertEqual(s['gold'], int(R.START_GOLD * 1.15))       # 위 보정

    def test_apply_does_not_mutate(self):
        before = json.dumps(self.state, sort_keys=True)
        R.apply(self.board, self.state, {'kind': 'develop', 'city': self.state['start']})
        self.assertEqual(json.dumps(self.state, sort_keys=True), before)

    def test_develop_and_conscript(self):
        s, res = R.apply(self.board, self.state, {'kind': 'develop', 'city': self.state['start']})
        self.assertGreater(s['gold'], self.state['gold'])
        self.assertEqual(R.ap_left(s), R.AP_BASE - 1)
        s2, res = R.apply(self.board, s, {'kind': 'conscript', 'city': s['start']})
        self.assertGreater(s2['cities'][s['start']]['troops'], s['cities'][s['start']]['troops'])

    def test_rule_error_keeps_ap(self):
        with self.assertRaises(R.RuleError):
            R.apply(self.board, self.state, {'kind': 'develop', 'city': 'nowhere'})
        with self.assertRaises(R.RuleError):
            R.apply(self.board, self.state, {'kind': 'attack', 'from': self.state['start'], 'to': self.state['start'],
                                             'officers': [], 'troops': 1})

    def test_same_actions_same_result(self):
        act = _first_attack(self.board, self.state)
        a, ra = R.apply(self.board, self.state, act)
        b, rb = R.apply(self.board, self.state, act)
        self.assertEqual(a, b)
        self.assertEqual(ra, rb)

    def test_runs_out_of_ap(self):
        s = self.state
        while not s['over']:
            s, _ = R.apply(self.board, s, {'kind': 'develop', 'city': s['start']})
        self.assertEqual(R.ap_left(s), 0)
        self.assertEqual(s['seasons'], R.AP_BASE // R.SEASON_AP)
        with self.assertRaises(R.RuleError):
            R.apply(self.board, s, {'kind': 'develop', 'city': s['start']})
        self.assertEqual(R.add_bonus(s, 9), R.AP_BONUS_MAX)
        self.assertFalse(s['over'])
        self.assertEqual(R.ap_left(s), R.AP_BONUS_MAX)

    def test_recruit_needs_enough_persuasion(self):
        old_board = {**self.board, 'rules': 1}
        self.state = R.new_run(old_board, 'wei', 0, seed=1234)
        self.assertEqual((R.ap_left(self.state), self.state['food']), (10, 1000))
        city = self.state['start']
        code = self.board['free'][city][0]
        target = D.GENERAL[code]
        by = D.GENERAL[self.state['cities'][city]['officers'][0]]
        gold = R.recruit_gold_needed(self.state, by, target, captive=False)
        if gold is None:
            with self.assertRaises(R.RuleError):
                R.apply(self.board, self.state, {'kind': 'recruit', 'city': city, 'target': code, 'by': by.code,
                                                 'gold': self.state['gold']})
            return
        if gold > 0:
            with self.assertRaises(R.RuleError):
                R.apply(self.board, self.state, {'kind': 'recruit', 'city': city, 'target': code, 'by': by.code,
                                                 'gold': gold - 50})
        s, res = R.apply(self.board, self.state, {'kind': 'recruit', 'city': city, 'target': code, 'by': by.code,
                                                  'gold': gold})
        self.assertIn(code, s['cities'][city]['officers'])
        self.assertIn(code, s['recruited'])
        self.assertEqual(R.score(s)['recruits'], D.RECRUIT_SCORE[target.tier])

    def test_captive_joins_after_dialogue_at_server_price(self):
        city = self.state['start']
        for code, total in (('liru', 2), ('guanyu', 3)):
            with self.subTest(code=code):
                self.assertEqual(R.recruit_offer(self.state, D.GENERAL[code], True)['total'], total)
                state = {**self.state, 'captives': {city: [code]}}
                action = {'kind': 'recruit', 'city': city, 'target': code, 'gold': -9999, 'by': 'forged'}
                for turn in range(1, total + 1):
                    state, result = R.apply(self.board, state, action)
                    self.assertEqual(result['progress'], turn)
                    self.assertEqual(R.ap_left(state), R.AP_BASE - turn)
                    self.assertEqual(state['gold'], self.state['gold'])
                    if turn < total:
                        self.assertEqual(result['kind'], 'parley')
                        self.assertNotIn(code, state['recruited'])
                self.assertIn(code, state['recruited'])
                self.assertNotIn(code, state['captives'][city])

    def test_free_recruit_uses_fixed_stipend(self):
        city = self.state['start']
        state = {**self.state, 'free': {city: ['guanyu']}}
        action = {'kind': 'recruit', 'city': city, 'target': 'guanyu', 'gold': 0}
        with self.assertRaises(R.RuleError):
            R.apply(self.board, {**state, 'gold': 399}, action)
        next_state, result = R.apply(self.board, state, action)
        self.assertEqual(next_state['gold'], state['gold'] - 400)
        self.assertEqual(result['kind'], 'recruit')

    def test_capture_scores_city(self):
        s = self.state
        for _ in range(3):
            s, _ = R.apply(self.board, s, {'kind': 'conscript', 'city': s['start']})
        act = _first_attack(self.board, s)
        s2, res = R.apply(self.board, s, act)
        if res['win']:
            self.assertEqual(s2['cities'][act['to']]['owner'], R.ME)
            self.assertGreaterEqual(R.score(s2)['cities'], D.CITY[act['to']].value)

    def test_end(self):
        s, res = R.apply(self.board, self.state, {'kind': 'end'})
        self.assertTrue(s['over'])
        self.assertEqual(R.add_bonus(s, 2), 2)
        self.assertTrue(s['over'])                                  # 직접 끝낸 판은 보너스로 다시 열리지 않는다

    def test_score_parts_sum(self):
        sc = R.score(self.state)
        self.assertEqual(sc['total'], sum(v for k, v in sc.items() if k != 'total'))


class TutorialTests(SimpleTestCase):
    def test_tutorial_is_fixed_and_luckless(self):
        board = B.tutorial()
        a = R.new_run(board, 'wei', 0, seed=1)
        b = R.new_run(board, 'wei', 0, seed=999)
        self.assertEqual(R.ap_left(a), B.TUTORIAL_AP)
        act = {'kind': 'attack', 'from': 'xuchang', 'to': 'chenliu', 'officers': ['xiahoudun'], 'troops': 2000}
        ra = R.apply(board, a, act)[1]
        rb = R.apply(board, b, act)[1]
        self.assertEqual(ra['ratio'], rb['ratio'])
        self.assertEqual(ra['luck'], 1.0)
