"""판 나란히 비교·최고 판 지키기·제목 점검(2026-11-23)."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase

from office import headline as H
from office import pairwise as PW
from office.models import ColumnDraft, JobRequest

UA = {'HTTP_USER_AGENT': 'Mozilla/5.0'}


def judge(*answers):
    """순서대로 'better' 값을 돌려주는 가짜 심사."""
    replies = iter(answers)
    return lambda agent, prompt, **kw: {'better': next(replies), 'reason': '근거가 더 분명해요'}


class PairwiseTests(SimpleTestCase):
    A, B = ('제목 A', '본문 A'), ('제목 B', '본문 B')

    def test_same_winner_in_both_orders_is_a_verdict(self):
        self.assertEqual(PW.compare(self.A, self.B, ask_json=judge('1', '2'))['winner'], 'a')
        self.assertEqual(PW.compare(self.A, self.B, ask_json=judge('2', '1'))['winner'], 'b')

    def test_position_bias_becomes_a_tie(self):
        result = PW.compare(self.A, self.B, ask_json=judge('1', '1'))   # 두 번 모두 '먼저 본 쪽'
        self.assertEqual((result['winner'], result['consistent']), ('tie', False))

    def test_second_order_really_swaps_the_drafts(self):
        prompts = []
        PW.compare(self.A, self.B, ask_json=lambda a, p, **k: prompts.append(p) or {'better': 'same'})
        self.assertLess(prompts[0].index('제목 A'), prompts[0].index('제목 B'))
        self.assertLess(prompts[1].index('제목 B'), prompts[1].index('제목 A'))


@mock.patch.dict('os.environ', {'OFFICE_PAIRWISE_GUARD': '1'})
class RevisionPairwiseTests(SimpleTestCase):
    def session(self):
        from office.revision_requests import RevisionRequests
        draft = SimpleNamespace(subject='제목', content='기존 본문이에요.', qa_report={'score': 80}, check_report={'verdict': 'pass'},
                                chart_path='', chart_note='', revisions=1, STATUS_HOLD='hold', save=mock.Mock(), admin_note='')
        s = RevisionRequests(draft, '도입을 고쳐 주세요.', 'hrd', mock.Mock())
        s.commit = nullcontext
        s.verify = mock.Mock(return_value={'reasons': [], 'items': [], 'verified': True})
        return s

    def test_candidate_losing_both_orders_is_not_adopted(self):
        s = self.session()
        with mock.patch('office.revision_requests.ask_agent_json', side_effect=judge('1', '2')):
            adopted = s.finish('제목', '새 본문이에요.', {'score': 82}, {'verdict': 'pass'}, retain=False)
        self.assertFalse(adopted)
        self.assertEqual(s.report['pairwise']['winner'], 'a')
        self.assertTrue(any('나란히 비교' in r for r in s.report['reasons']))

    def test_tie_falls_back_to_the_score_rule(self):
        s = self.session()
        qa = {'score': 82}
        with mock.patch('office.revision_requests.ask_agent_json', side_effect=judge('1', '1')):
            self.assertTrue(s.finish('제목', '새 본문이에요.', qa, {'verdict': 'pass'}, retain=False))
        self.assertEqual(qa['admin_revision']['pairwise']['winner'], 'tie')


@mock.patch.dict('os.environ', {'OFFICE_PAIRWISE_GUARD': '1'})
class KeepBestTests(SimpleTestCase):
    def version(self, attempt, score, body, fatal=()):
        from office import pipeline as P
        return {'subject': '제목', 'content': body, 'attempt': attempt, 'chart_rel': '', 'chart_note': '', 'visual_report': '',
                'qa': {'score': score, 'verdict': 'minor', 'fatal': list(fatal), 'must_fix': [{'problem': 'x'}]},
                'check': {'verdict': 'pass', 'subject': '제목', 'verification_hash': P.verification_hash(body)}}

    def keep(self, versions, answers):
        from office.management.commands.office_publish import Command
        with mock.patch('office.services.ask_agent_json', side_effect=judge(*answers)):
            return Command._keep_best(versions, stages=mock.Mock(), rec=mock.Mock())

    def test_better_earlier_draft_is_restored_when_it_wins_both_orders(self):
        best = self.keep([self.version(0, 78, '초안'), self.version(1, 70, '재작성')], ['1', '2'])
        self.assertEqual(best['content'], '초안')

    def test_no_restore_on_tie_or_when_last_is_better(self):
        self.assertIsNone(self.keep([self.version(0, 78, '초안'), self.version(1, 70, '재작성')], ['1', '1']))
        self.assertIsNone(self.keep([self.version(0, 70, '초안'), self.version(1, 78, '재작성')], []))

    def test_earlier_version_needs_its_own_fact_check(self):
        stale = self.version(0, 78, '초안')
        stale['check']['verification_hash'] = 'other'
        self.assertIsNone(self.keep([stale, self.version(1, 70, '재작성')], []))


class HeadlineTests(SimpleTestCase):
    BODY = '## 도입\n\n복귀 첫 2주에 상사가 묻지 않으면 교육은 현업에 닿지 않아요.' * 3

    def fake(self, candidates, results):
        replies = iter([{'candidates': candidates}, {'results': results}])
        return lambda agent, prompt, **kw: next(replies)

    def test_checklist_grades_current_title_and_keeps_one_candidate_per_style(self):
        cands = [{'title': '복귀 첫 2주, 교육 효과가 갈리는 시간', 'style': 'image'},
                 {'title': '교육 뒤 상사가 묻지 않으면 생기는 일', 'style': 'question'},
                 {'title': '교육 전이를 높이는 복귀 후 첫 대화', 'style': 'search'},
                 {'title': '너무 짧음', 'style': 'search'}]
        subject = '교육 전이율, 복귀 후 점검 설계 방법'
        order = H._shuffled([subject] + [c['title'] for c in cands], self.BODY[:200])
        results = [{'n': i, **{k: (t != subject) for k, _ in H.CHECKS}} for i, t in enumerate(order, 1)]
        out = H.review(subject, self.BODY, ask_json=self.fake(cands, results))
        self.assertFalse(out['current']['ok'])
        self.assertEqual(len(out['candidates']), 3)
        self.assertEqual({c['style'] for c in out['candidates']}, {'image', 'question', 'search'})
        self.assertNotIn('너무 짧음', [c['title'] for c in out['candidates']])   # 길이 검사를 통과해야 후보예요

    def test_missing_judgement_is_not_counted_as_a_pass(self):
        out = H.review('교육 전이율, 복귀 후 점검 설계 방법', self.BODY,
                       ask_json=self.fake([{'title': '복귀 첫 2주, 교육 효과가 갈리는 시간', 'style': 'image'}], []))
        self.assertEqual(out['candidates'], [])
        self.assertFalse(out['current']['ok'])

    def test_title_prompt_no_longer_pushes_keyword_first_titles(self):
        from office.pipeline import HEADLINE_PROMPT
        self.assertIn('"검색어, 설명" 공식을 쓰지 마세요', HEADLINE_PROMPT)


class TitlePickViewTests(TestCase):
    def setUp(self):
        otp = mock.patch('common.views._admin_otp_session_ok', return_value=True)
        otp.start()
        self.addCleanup(otp.stop)
        self.client.force_login(User.objects.create_superuser('admin', '', 'x'))
        review = {'subject': '원래 제목입니다 충분히', 'current': {'ok': False, 'passed': 3, 'total': 5, 'misses': ['말투가 딱딱함']},
                  'candidates': [{'title': '복귀 첫 2주, 교육 효과가 갈리는 시간', 'style': 'image', 'style_label': '은유형',
                                  'passed': 5, 'total': 5}]}
        self.draft = ColumnDraft.objects.create(topic='hrd', subject='원래 제목입니다 충분히', content='본문', status='hold',
                                                qa_report={'score': 75, 'verdict': 'minor', 'title_review': review},
                                                check_report={'verdict': 'pass'})

    def test_card_offers_title_candidates_and_pick_becomes_a_title_request(self):
        html = self.client.get('/lab/admin/', **UA).content.decode()
        self.assertIn('제목 점검', html)
        self.assertIn('value="복귀 첫 2주, 교육 효과가 갈리는 시간"', html)
        self.client.post(f'/lab/admin/draft/{self.draft.pk}/revise/', {'title_pick': '복귀 첫 2주, 교육 효과가 갈리는 시간'}, **UA)
        args = JobRequest.objects.get(draft=self.draft).args
        self.assertIn('제목을 「복귀 첫 2주, 교육 효과가 갈리는 시간」로 바꿔 주세요.', args[args.index('--note') + 1])

    def test_unknown_title_is_refused(self):
        response = self.client.post(f'/lab/admin/draft/{self.draft.pk}/revise/', {'title_pick': '지어낸 제목'}, **UA)
        self.assertFalse(JobRequest.objects.filter(draft=self.draft).exists())
        self.assertIn('제목 후보가 바뀌었어요', ' '.join(str(m) for m in get_messages(response.wsgi_request)))


class TitleCtrTests(SimpleTestCase):
    def test_title_styles_and_groups(self):
        from datetime import timedelta
        from django.utils import timezone
        from office import seo_audit as S
        self.assertEqual(S.title_style('ADsP 점수와 합격 기준, 총점만 보면 놓치는 과락'), '검색어, 설명 공식')
        self.assertEqual(S.title_style('일터의 스승은 동료다: 피어러닝의 귀환'), '콜론 부제형')
        self.assertEqual(S.title_style('AI 역량을 자기진단 점수로 판정해도 될까요?'), '질문형')
        old = timezone.now() - timedelta(days=60)
        cols = [SimpleNamespace(id=1, subject='ADsP 점수와 합격 기준, 총점만 보면 놓치는 과락', create_date=old),
                SimpleNamespace(id=2, subject='일터의 스승은 동료다: 피어러닝의 귀환', create_date=old),
                SimpleNamespace(id=3, subject='방금 쓴 글, 아직 순위가 흔들려요', create_date=timezone.now())]
        stats = {1: {'impr': 400, 'clicks': 4, 'position': 8.0}, 2: {'impr': 200, 'clicks': 6, 'position': 9.0},
                 3: {'impr': 999, 'clicks': 99, 'position': 3.0}}
        rows = {r['style']: r for r in S.title_ctr_groups(stats, cols)}
        self.assertEqual(set(rows), {'검색어, 설명 공식', '콜론 부제형'})       # 발행 직후 글은 빼요
        self.assertEqual(rows['콜론 부제형']['ctr'], 3.0)
        self.assertTrue(rows['검색어, 설명 공식']['small_sample'])
