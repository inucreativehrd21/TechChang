"""에이전트 무기 P0 — 본문 대조 중복 검사·검증 원장·경쟁 글 비교·점수 안정화."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office import ledger, pipeline as P
from office.models import VerifiedFact
from office.similarity import compare, similar_columns, similarity_block

BODY = ('교육 담당자는 수료 직후 만족도 설문으로 평가를 끝내는 경우가 많습니다. 전이를 확인하려면 복귀 후 '
        '시점별로 질문을 달리해야 합니다. 상사와 수료자에게 같은 문항을 보내면 자기보고의 한계를 보완할 수 있습니다. ') * 6
OTHER = ('파이썬 장고 프레임워크로 모델과 마이그레이션을 다루는 방법을 설명합니다. 데이터베이스 테이블이 '
         '바뀌면 마이그레이션 파일을 만들어 적용합니다. ') * 6


def column(subject, content):
    bot, _ = User.objects.get_or_create(username='techchang연구팀')
    cat, _ = Category.objects.get_or_create(name='칼럼')
    return Question.objects.create(author=bot, category=cat, subject=subject, content=content,
                                   create_date=timezone.now())


class SimilarityTests(TestCase):
    def test_copy_is_duplicate_and_unrelated_is_not(self):
        self.assertGreater(compare(BODY, BODY)['shingle'], 0.9)
        r = compare(BODY, OTHER)
        self.assertLess(r['shingle'], 0.01)
        self.assertLess(r['topic'], 0.2)

    def test_template_headings_do_not_count_as_shared_topic(self):
        a = '## 왜 지금인가\n\n## 숫자로 보는 현황\n\n## 시사점\n\n' + BODY
        b = '## 왜 지금인가\n\n## 숫자로 보는 현황\n\n## 시사점\n\n' + OTHER
        self.assertNotIn('현황', compare(a, b)['shared'])

    def test_block_flags_copy_and_explains_threshold(self):
        column('전이 점검 설계', BODY)
        column('장고 마이그레이션', OTHER)
        rows = similar_columns(BODY)
        self.assertEqual(rows[0]['subject'], '전이 점검 설계')
        self.assertTrue(rows[0]['duplicate'])
        self.assertFalse(rows[1]['duplicate'])
        block = similarity_block(BODY)
        self.assertIn('← 중복 후보', block)
        self.assertIn('기준 미만이면', block)


class LedgerTests(TestCase):
    CHECK = {'claims': [
        {'claim': '2024년 재직자 교육훈련 실시 기업 51.8%', 'status': 'verified',
         'note': '확인 방법 (2): 보도 3곳 일치 https://www.korea.kr/briefing/x'},
        {'claim': '한국 기업 90%가 매출로 측정', 'status': 'unverifiable', 'note': '찾지 못함'},
        {'claim': 'URL 없이 verified 된 주장 12%', 'status': 'verified', 'note': '확인했습니다'},
    ]}

    def test_only_claims_with_urls_are_recorded(self):
        self.assertEqual(ledger.record(self.CHECK), 1)
        fact = VerifiedFact.objects.get()
        self.assertEqual(fact.method, '보도 2곳+')
        self.assertEqual(fact.urls, ['https://www.korea.kr/briefing/x'])
        ledger.record(self.CHECK)
        fact.refresh_from_db()
        self.assertEqual(fact.times_seen, 2)            # 같은 주장은 쌓지 않고 갱신
        self.assertEqual(VerifiedFact.objects.count(), 1)

    def test_block_matches_same_number_in_new_draft(self):
        ledger.record(self.CHECK)
        self.assertIn('51.8%', ledger.ledger_block('올해 원고에도 51.8%가 나옵니다.'))
        self.assertEqual(ledger.ledger_block('수치가 다른 원고 33%'), '')


class CheckStepTests(TestCase):
    def test_check_prompt_has_body_comparison_and_ledger_and_records(self):
        column('전이 점검 설계', BODY)
        ledger.record(LedgerTests.CHECK)
        seen = {}

        def fake(key, prompt, **kw):
            seen['prompt'] = prompt
            return {'verdict': 'pass', 'claims': [
                {'claim': '새 주장 62%', 'status': 'verified', 'note': '확인 방법 (3) https://api.crossref.org/x'}]}

        with mock.patch('office.pipeline.ask_agent_json', side_effect=fake):
            P.step_check('제목', BODY + ' 51.8%', [])
        self.assertIn('[본문 대조', seen['prompt'])
        self.assertIn('[검증 원장', seen['prompt'])
        self.assertTrue(VerifiedFact.objects.filter(claim='새 주장 62%', method='학술 초록').exists())


class CriticCompetitionTests(TestCase):
    def test_critic_searches_and_competition_reaches_editor(self):
        def fake(key, prompt, **kw):
            self.assertEqual(kw.get('tools'), ('WebSearch', 'WebFetch'))
            self.assertIn('[경쟁 글 비교', prompt)
            return {'verdict': 'recommend', 'reason': '좋음',
                    'competition': [{'title': '전이 평가 가이드', 'url': 'https://ex.com/a', 'covers': '4수준 모형 소개'},
                                    {'title': 'URL 없는 글'}],
                    'edge': '시점별 점검표와 후속 조치는 경쟁 글에 없습니다'}
        with mock.patch('office.pipeline.ask_agent_json', side_effect=fake):
            cr = P.step_critique('제목', BODY)
        self.assertEqual(len(cr['competition']), 1)       # URL 없는 항목은 버린다
        text = P.critique_text(cr)
        self.assertIn('경쟁 글', text)
        self.assertIn('시점별 점검표와 후속 조치', text)


class ReviewPanelTests(TestCase):
    def review(self, sequence):
        calls = []

        def fake(key, prompt, **kw):
            calls.append(1)
            return sequence[len(calls) - 1]
        with mock.patch('office.pipeline.ask_agent_json', side_effect=fake):
            qa = P.step_review('제목', '## 숫자로 보는 현황\n\n![그림](x.png)\n\n' + '본문입니다. ' * 600,
                               {'verdict': 'pass'}, 'x.png')
        return qa, len(calls)

    @staticmethod
    def make(v, fatal=()):
        return {'scores': {k: v for k in P.RUBRIC}, 'fatal': list(fatal), 'issues': [f'지적 {v}'], 'notes': ''}

    def test_clear_cases_are_judged_once(self):
        qa, n = self.review([self.make(5)])
        self.assertEqual((n, qa['score'], qa['verdict']), (1, 100, 'accept'))
        qa, n = self.review([self.make(2)])
        self.assertEqual(n, 1)

    def test_borderline_uses_median_of_three(self):
        # 78점 근처 → 3회: 4(80점)·4(80점)·3(60점) → 중앙값 4 → 80점 발행
        mixed = self.make(3)
        qa, n = self.review([self.make(4), self.make(4), mixed])
        self.assertEqual(n, 3)
        self.assertEqual(qa['score'], 80)
        self.assertEqual(qa['panel'], [80, 80, 60])
        self.assertEqual(qa['verdict'], 'accept')

    def test_fatal_needs_majority(self):
        qa, _ = self.review([self.make(4, ['overclaim']), self.make(4), self.make(4)])
        self.assertNotIn('overclaim', qa['fatal'])
        qa, _ = self.review([self.make(4, ['overclaim']), self.make(4, ['overclaim']), self.make(4)])
        self.assertIn('overclaim', qa['fatal'])
