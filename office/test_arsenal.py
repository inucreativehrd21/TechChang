"""무기고 P1 — 분야 지식 팩·모범 칼럼 서고·링크 점검·제목 실험실."""
import urllib.error
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office import arsenal, pipeline as P
from office.models import ColumnDraft


def published(topic, score, subject, content, strengths='도입이 구체적'):
    bot, _ = User.objects.get_or_create(username='techchang연구팀')
    cat, _ = Category.objects.get_or_create(name='칼럼')
    q = Question.objects.create(author=bot, category=cat, subject=subject, content=content, create_date=timezone.now())
    return ColumnDraft.objects.create(topic=topic, subject=subject, status=ColumnDraft.STATUS_PUBLISHED, question=q,
                                      qa_report={'score': score, 'strengths': strengths})


BODY = '교육 담당자의 실제 장면으로 시작하는 도입 문단입니다.\n\n## 왜 지금인가\n\n이유입니다.\n\n## 숫자로 보는 현황\n\n2024년 51.8%였습니다.\n'


class KnowledgePackTests(TestCase):
    def test_each_topic_gets_house_style_and_its_own_pack(self):
        for topic, marker in (('hrd', '커크패트릭'), ('data', '선택 편향'), ('coding', '버전과 날짜')):
            pack = arsenal.knowledge_pack(topic)
            self.assertIn('[하우스 스타일', pack)
            self.assertIn(marker, pack)
        self.assertNotIn('커크패트릭', arsenal.knowledge_pack('coding'))

    def test_writing_standard_carries_pack_only_when_topic_known(self):
        self.assertNotIn('[분야 지식 팩', P.writing_standard())
        self.assertIn('[분야 지식 팩 — HRD]', P.writing_standard('hrd'))


class ExemplarTests(TestCase):
    def test_prefers_same_topic_then_score(self):
        published('data', 95, '데이터 최고작', BODY)
        published('hrd', 86, 'HRD 모범작', BODY)
        published('hrd', 70, 'HRD 저득점', BODY)
        ex = arsenal.exemplar('hrd')
        self.assertEqual((ex['title'], ex['same_topic']), ('HRD 모범작', True))
        self.assertEqual(ex['data_para'], '2024년 51.8%였습니다.')
        self.assertIn('교육 담당자의 실제 장면', ex['lede'])
        self.assertEqual(arsenal.exemplar('coding')['title'], '데이터 최고작')   # 같은 분야가 없으면 전체 최고

    def test_blocks(self):
        published('hrd', 90, 'HRD 모범작', BODY)
        self.assertIn('[모범 칼럼', P.writing_standard('hrd'))
        self.assertIn('[채점 기준점', arsenal.exemplar_block(for_editor=True))

    def test_none_when_no_high_scorer(self):
        published('hrd', 70, '저득점', BODY)
        self.assertEqual(arsenal.exemplar_block('hrd'), '')


class LinkCheckTests(TestCase):
    def fake_open(self, req, timeout=0):
        url = req.full_url
        if 'gone' in url:
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
        if 'bot-wall' in url:
            raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)
        if 'down' in url:
            raise urllib.error.URLError('connection refused')
        resp = mock.MagicMock()
        resp.__enter__.return_value.status = 200
        return resp

    def test_dead_vs_blocked(self):
        content = ('출처 https://ok.example/a 와 https://gone.example/b, https://bot-wall.example/c '
                   '그리고 https://down.example/d.')
        with mock.patch('office.arsenal.urllib.request.urlopen', side_effect=self.fake_open):
            res = arsenal.dead_links(content)
        self.assertEqual({u for u, _ in res['dead']}, {'https://gone.example/b', 'https://down.example/d'})
        self.assertEqual([u for u, _ in res['blocked']], ['https://bot-wall.example/c'])
        block = arsenal.link_block(res)
        self.assertIn('gone.example', block)
        self.assertNotIn('bot-wall', block)        # 봇 차단은 죽은 링크로 몰지 않는다

    def test_check_step_reports_dead_links(self):
        seen = {}

        def fake_agent(key, prompt, **kw):
            seen['prompt'] = prompt
            return {'verdict': 'pass', 'claims': []}
        with mock.patch('office.arsenal.urllib.request.urlopen', side_effect=self.fake_open), \
                mock.patch('office.pipeline.ask_agent_json', side_effect=fake_agent):
            check = P.step_check('제목', '근거 https://gone.example/x', [])
        self.assertIn('[링크 점검', seen['prompt'])
        self.assertEqual(check['dead_links'], ['https://gone.example/x'])


class HeadlineTests(TestCase):
    def run_lab(self, res, recent=()):
        with mock.patch('office.pipeline.ask_agent_json', return_value=res):
            return P.step_headline('원래 제목입니다 충분히 긴', BODY, keywords=['학습 전이'], recent=recent)

    def test_valid_pick_is_used(self):
        title, _ = self.run_lab({'candidates': ['학습 전이, 언제 물어야 할까요', '짧음'], 'pick': 0, 'reason': '검색어 포함'})
        self.assertEqual(title, '학습 전이, 언제 물어야 할까요')

    def test_invalid_pick_falls_back_to_next_valid_candidate(self):
        title, _ = self.run_lab({'candidates': ['반드시 알아야 할 전이 점검의 모든 것', '복귀 후 세 번 묻는 학습 전이 점검'], 'pick': 0})
        self.assertEqual(title, '복귀 후 세 번 묻는 학습 전이 점검')     # 단정 표현 후보는 건너뛴다

    def test_keep_and_duplicates_keep_original(self):
        self.assertEqual(self.run_lab({'candidates': ['다른 제목 후보입니다 충분히'], 'keep': True})[0], '원래 제목입니다 충분히 긴')
        title, _ = self.run_lab({'candidates': ['이미 쓴 제목입니다 정말로'], 'pick': 0}, recent=['이미 쓴 제목입니다 정말로'])
        self.assertEqual(title, '원래 제목입니다 충분히 긴')
