"""원장 대조 사실 관문 — 웹을 다시 열지 않고 저장된 발췌로 판정한다(office.grounded)."""
from unittest import mock

from django.test import SimpleTestCase, TestCase

from office import code_check as CC
from office import evidence as E
from office import grounded as GR
from office import model_router as R
from office import pipeline as P

URL = 'https://docs.djangoproject.com/en/5.2/ref/models/querysets/#prefetch-related'
ROWS = [
    {'status': 'verified', 'claim': 'select_related는 단일값 관계만 지원해요.',
     'quote': 'single-valued relationships - foreign key and one-to-one.',
     'context': 'select_related is limited to single-valued relationships - foreign key and one-to-one.',
     'url': URL, 'source_locator': 'prefetch_related()', 'population': 'QuerySet API', 'period': 'Django 5.2'},
    {'status': 'unverifiable', 'claim': '확인 못 한 주장', 'quote': '', 'url': ''},
    {'status': 'verified', 'claim': 'select_related는 단일값 관계만 지원해요.',      # 같은 사실은 한 번만
     'quote': 'single-valued relationships - foreign key and one-to-one.', 'url': URL},
]
CODE = CC.facts({'ran': True, 'django': '5.2.6', 'tests': [
    {'name': 'test_post_list_queries', 'status': 'passed', 'message': '', 'expected': [2]}]})


class EntriesTests(SimpleTestCase):
    def test_keeps_sourced_facts_once_and_execution_results(self):
        items = GR.entries(ROWS, code_facts=CODE)
        self.assertEqual([e['id'] for e in items], ['E1', 'E2', 'E3'])      # 실행 환경 요약 + 테스트 1개
        self.assertEqual([e.get('kind') for e in items[1:]], ['execution', 'execution'])
        self.assertIn('앞뒤 문단', GR.ledger_text(items))


class AttachTests(SimpleTestCase):
    def setUp(self):
        self.items = {e['id']: e for e in GR.entries(ROWS, code_facts=CODE)}

    def test_quote_must_come_from_the_ledger_excerpt(self):
        ok = GR.attach({'claim': 'a', 'status': 'verified', 'evidence': 'E1',
                        'quote': 'select_related is limited to single-valued relationships'}, self.items)
        self.assertEqual((ok['status'], ok['url'], ok['entailment']), ('verified', URL, 'supported'))
        made_up = GR.attach({'claim': 'a', 'status': 'verified', 'evidence': 'E1',
                             'quote': 'select_related always uses one query'}, self.items)
        self.assertEqual(made_up['status'], 'needs_source')
        self.assertEqual(GR.attach({'claim': 'a', 'status': 'verified', 'evidence': 'E9', 'quote': 'x'},
                                   self.items)['status'], 'needs_source')

    def test_punctuation_ellipsis_and_wrong_number_are_tolerated_but_short_or_absent_are_not(self):
        excerpt = 'select_related is limited to single-valued relationships - foreign key and one-to-one.'
        self.assertTrue(GR.quoted_in('"Select_related is limited… foreign key and one-to-one"', excerpt))
        self.assertFalse(GR.quoted_in('limited', excerpt))                                  # 너무 짧다
        self.assertFalse(GR.quoted_in('select_related is limited … to many-to-many', excerpt))
        two = 'select_related is limited to single-valued relationships. It follows foreign keys in one query.'
        self.assertTrue(GR.quoted_in('It follows foreign keys in one query. select_related is limited to single', two))
        self.assertFalse(GR.quoted_in('공식 문서는 select_related가 단일값 관계에만 쓰인다고 설명합니다.', excerpt))
        moved = GR.attach({'claim': 'a', 'status': 'verified', 'evidence': 'E3',
                           'quote': 'single-valued relationships - foreign key and one-to-one'}, self.items)
        self.assertEqual((moved['status'], moved['grounded']), ('verified', 'E1'))   # 번호만 잘못 적은 경우

    def test_execution_evidence_passes_contract_without_url(self):
        c = GR.attach({'claim': '사례 1 테스트는 assertNumQueries 2회로 통과해요.', 'status': 'verified',
                       'evidence': 'E3', 'quote': 'test_post_list_queries: 통과 (assertNumQueries 2회)'}, self.items)
        with R.use_profile('b'):
            checked = E.validate_check({'claims': [c]})
        self.assertEqual(checked['claims'][0]['status'], 'verified', checked['claims'][0].get('note'))
        self.assertEqual(checked['verdict'], 'pass')


class CheckTests(SimpleTestCase):
    def _ask(self, gathered):
        def ask_json(agent, prompt, **kw):
            if prompt.startswith('근거 확인입니다'):
                gathered.append(kw.get('tools'))
                return {'claims': [{'claim': '원장 밖 주장', 'status': 'verified', 'value': '원장 밖 주장',
                                    'quote': 'outside fact', 'url': 'https://example.org/x'}]}
            self.assertNotIn('tools', kw)                     # 원장 대조 호출에는 웹 도구가 없다
            return {'claims': [
                {'claim': '단일값만 지원', 'status': 'verified', 'evidence': 'E1',
                 'quote': 'single-valued relationships - foreign key and one-to-one.'},
                {'claim': '원장 밖 주장', 'status': 'needs_source'},
                {'claim': '두 번째 원장 밖 주장', 'status': 'needs_source'}]}
        return ask_json

    def test_only_missing_claims_go_to_the_web_within_the_cap(self):
        gathered = []
        items = GR.entries(ROWS)
        with mock.patch.object(GR, 'GROUNDED_WEB_MAX', 1):
            res = GR.check('제목', '본문', items, ask_json=self._ask(gathered), web_tools=('WebSearch',))
        self.assertEqual(gathered, [('WebSearch',)])
        self.assertEqual([c['status'] for c in res['claims']], ['verified', 'verified', 'unverifiable'])
        self.assertEqual(res['grounded'], {'ledger': 1, 'claims': 3, 'web_checked': 1, 'needs_source': 2})

    def test_disabled_by_setting(self):
        with mock.patch.dict('os.environ', {'OFFICE_GROUNDED_CHECK': '0'}):
            self.assertFalse(GR.enabled())


class StepCheckRouteTests(TestCase):
    def test_profile_b_with_ledger_uses_grounded_path(self):
        calls = []

        def ask(agent, prompt, **kw):
            calls.append(kw.get('tools'))
            return {'claims': [{'claim': '단일값만 지원', 'status': 'verified', 'evidence': 'E1',
                                'quote': 'single-valued relationships - foreign key and one-to-one.'}]}
        with R.use_profile('b'), mock.patch.object(P, 'ask_agent_json', side_effect=ask):
            check = P.step_check('제목', '본문입니다.', [], evidence=GR.entries(ROWS))
        self.assertEqual(calls, [None])
        self.assertEqual(check['verdict'], 'pass')
        self.assertEqual(check['grounded']['web_checked'], 0)


class NoWebDefaultTests(SimpleTestCase):
    """웹 확인 기본 끔 — 원장 밖 주장은 좁히거나 지울 수정 대상(2026-11-01 v3: 웹 확인 6개가 643k 토큰)."""

    def test_out_of_ledger_claims_are_marked_without_web_calls(self):
        def ask_json(agent, prompt, **kw):
            self.assertFalse(prompt.startswith('근거 확인입니다'))      # 웹 수집 호출이 없어야 한다
            return {'claims': [{'claim': '원장 밖 주장', 'status': 'needs_source'}]}
        with mock.patch.object(GR, 'GROUNDED_WEB_MAX', 0):
            res = GR.check('제목', '본문', GR.entries(ROWS), ask_json=ask_json, web_tools=('WebSearch',))
        c = res['claims'][0]
        self.assertEqual((c['status'], c['out_of_ledger']), ('unverifiable', True))
        self.assertIn('좁히거나', c['note'])

    def test_early_hold_counts_only_real_failures(self):
        out = [{'status': 'unverifiable', 'out_of_ledger': True}] * 8
        self.assertEqual(P.early_hold({'score': 70}, {'claims': out}), '')
        self.assertIn('6건', P.early_hold({'score': 70}, {'claims': out + [{'status': 'wrong'}] * 6}))


class VerifyClaimsTests(SimpleTestCase):
    def test_blueprint_claims_are_judged_against_ledger_in_order(self):
        items = GR.entries(ROWS)

        def ask_json(agent, prompt, **kw):
            self.assertNotIn('tools', kw)
            return {'claims': [{'n': 2, 'status': 'needs_source'},
                               {'n': 1, 'status': 'verified', 'evidence': 'E1',
                                'quote': 'single-valued relationships - foreign key and one-to-one.'}]}
        rows = GR.verify_claims([{'claim': '단일값만'}, {'claim': '원장 밖'}], items, ask_json=ask_json)
        self.assertEqual([r['claim'] for r in rows], ['단일값만', '원장 밖'])
        self.assertEqual([r['status'] for r in rows], ['verified', 'unverifiable'])
        self.assertTrue(rows[1]['out_of_ledger'])


class BlueprintGroundedTests(SimpleTestCase):
    def test_blueprint_uses_fetched_documents_instead_of_web_gather(self):
        from office import blueprint as B
        from office import sources as SRC
        para = {'url': URL, 'title': 'QuerySet API reference', 'version': '5.2', 'n': 3, 'section': 'select_related()',
                'text': 'select_related is limited to single-valued relationships - foreign key and one-to-one.'}

        def ask_json(agent, prompt, **kw):
            if 'thesis' in prompt:
                return {'thesis_ok': True}
            self.assertTrue(prompt.startswith('집필 전 근거 확인입니다'))   # 웹 수집(GATHER_PROMPT)이 아니다
            return {'claims': [{'n': 1, 'status': 'verified', 'evidence': 'E1',
                                'quote': 'select_related is limited to single-valued relationships'}]}
        bp = {'thesis': '답', 'claims': [{'claim': 'select_related는 단일값 관계만 지원해요.', 'source': URL}]}
        with R.use_profile('b'), mock.patch.object(SRC.Corpus, 'add'), \
                mock.patch.object(SRC.Corpus, 'select', return_value=[para]), \
                mock.patch.object(E, 'gather', side_effect=AssertionError('웹 수집을 부르면 안 돼요')):
            ver = B.verify_blueprint(bp, ask_json=ask_json)
        self.assertEqual(ver['coverage']['verified'], 1)
        self.assertIn('single-valued', ver['pack'])


class AssertEvidenceTests(SimpleTestCase):
    """2026-11-03 atomic 4차 — 테스트가 통과해도 '0건·1건' 결과 주장을 인용할 발췌가 없어 원장 밖이 됐다."""
    def test_result_claim_can_quote_the_checked_assert(self):
        facts = CC.facts({'ran': True, 'django': '5.2.6', 'tests': [
            {'name': 'test_with_atomic_leaves_no_rows', 'status': 'passed', 'message': '', 'expected': [],
             'asserts': ['self.assertEqual(Order.objects.count(), 0)']}]})
        items = {e['id']: e for e in GR.entries(code_facts=facts)}
        self.assertIn('Django 5.2.6', items['E1']['quote'])
        c = GR.attach({'claim': 'atomic으로 감싸면 주문이 0건 남아요.', 'status': 'verified', 'evidence': 'E2',
                       'quote': 'self.assertEqual(Order.objects.count(), 0)'}, items)
        self.assertEqual((c['status'], c['grounded']), ('verified', 'E2'))
