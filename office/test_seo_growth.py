"""SEO 2단계 — 검색 기회·관련 칼럼·IndexNow·제목 다시 쓰기 후보 (외부 API 없이)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from community.models import Category, Question
from office import pipeline as P
from office.datasources import gsc_gaps_from_rows
from office.management.commands.hold_meeting import mark_gsc_targets
from office.seo_audit import aggregate_page_rows, retitle_candidates

KEY = '0123456789abcdef0123456789abcdef'


def row(keys, impr, clicks=0, pos=10.0):
    return {'keys': keys, 'impressions': impr, 'clicks': clicks, 'position': pos}


class GscGapTests(TestCase):
    def test_near_miss_and_weak_ctr_are_kept_and_pages_merged(self):
        rows = [
            row(['로컬 llm', 'https://www.techchang.com/54/'], 5, pos=40),
            row(['로컬 llm', 'https://techchang.com/54/?sort=recommend'], 3, pos=42),
            row(['kpc hrd 아카이브', 'https://techchang.com/13/'], 22, pos=8.9),
            row(['jujutsu vs git', 'https://techchang.com/79/'], 1, clicks=1, pos=6),   # 노출 1회 — 제외
            row(['테크창', 'https://techchang.com/'], 30, clicks=10, pos=1),          # 이미 1위·CTR 좋음 — 제외
        ]
        gaps = gsc_gaps_from_rows(rows)
        self.assertEqual([g['query'] for g in gaps], ['kpc hrd 아카이브', '로컬 llm'])
        local = gaps[1]
        self.assertEqual((local['impr'], local['page']), (8, '/54/'))
        self.assertAlmostEqual(local['position'], 40.8, places=1)

    def test_meeting_options_are_marked_when_keywords_hit_a_gap(self):
        decisions = [{'options': [{'title': '로컬 LLM을 왜 쓰나', 'keywords': ['로컬LLM', '온프레미스 AI']},
                                  {'title': '다른 주제', 'keywords': ['무관']}]}]
        hits = mark_gsc_targets(decisions, [{'query': '로컬 llm'}])
        self.assertEqual(hits, ['로컬 llm'])
        self.assertEqual(decisions[0]['options'][0]['gsc_target'], '로컬 llm')
        self.assertNotIn('gsc_target', decisions[0]['options'][1])

    def test_writer_and_headline_get_the_search_target(self):
        chosen = {'title': 't', 'gsc_target': '로컬 llm', 'keywords': ['로컬 llm', '온디바이스']}
        self.assertIn('「로컬 llm」', P.search_target_rule(chosen))
        self.assertEqual(P.search_target_rule({'title': 't'}), '')
        self.assertEqual(P.headline_keywords(chosen), ['로컬 llm', '온디바이스'])


class RetitleTests(TestCase):
    def setUp(self):
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        cat = Category.objects.create(name='HRD')
        old = timezone.now() - timedelta(days=40)
        self.weak = Question.objects.create(author=bot, category=cat, subject='약한 제목', content='본문', create_date=old)
        self.fresh = Question.objects.create(author=bot, category=cat, subject='새 글', content='본문',
                                             create_date=timezone.now())

    def test_page_rows_merge_variants_and_skip_non_articles(self):
        stats = aggregate_page_rows([
            row(['https://www.techchang.com/5/', 'a'], 10, pos=4),
            row(['https://techchang.com/5/?sort=recent', 'b'], 30, clicks=1, pos=8),
            row(['https://techchang.com/?category=HRD', 'c'], 99),
        ])
        self.assertEqual(list(stats), [5])
        self.assertEqual((stats[5]['impr'], stats[5]['clicks'], stats[5]['queries'][0]), (40, 1, 'b'))
        self.assertEqual(stats[5]['position'], 7.0)

    def test_only_old_columns_with_weak_ctr_near_page_one(self):
        stats = {self.weak.id: {'impr': 50, 'clicks': 0, 'position': 9.0, 'queries': ['q']},
                 self.fresh.id: {'impr': 80, 'clicks': 0, 'position': 5.0, 'queries': ['q']}}
        self.assertEqual([c['id'] for c in retitle_candidates(stats)], [self.weak.id])
        stats[self.weak.id]['position'] = 30.0                     # 1페이지와 멀면 제목 문제가 아니다
        self.assertEqual(retitle_candidates(stats), [])


class RelatedColumnsTests(TestCase):
    def setUp(self):
        self.bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        self.cat = Category.objects.create(name='데이터분석')

    def make(self, subject, content):
        return Question.objects.create(author=self.bot, category=self.cat, subject=subject, content=content,
                                       create_date=timezone.now())

    def test_related_block_links_topically_close_columns(self):
        base = '합성 데이터 개인정보 HR 데이터 분석 모델 학습 데이터 품질 검증 ' * 20
        a = self.make('합성 데이터가 HR을 바꾸는 법', base)
        b = self.make('데이터 계보, 신뢰의 지도', '데이터 품질 검증 계보 추적 HR 데이터 분석 모델 ' * 20)
        self.make('조선 백자 감상법', '도자기 유약 가마 백자 조선 미술 감상 ' * 20)
        html = self.client.get(f'/{a.id}/').content.decode()
        self.assertIn('함께 읽으면 좋은 칼럼', html)
        self.assertIn(f'href="/{b.id}/"', html)
        self.assertNotIn('조선 백자 감상법', html)


@override_settings(INDEXNOW_KEY=KEY)
class IndexNowTests(TestCase):
    def test_key_file_is_served_only_for_the_real_key(self):
        res = self.client.get(f'/{KEY}.txt')
        self.assertEqual((res.status_code, res.content.decode()), (200, KEY))
        self.assertEqual(self.client.get('/ffffffffffffffffffffffffffffffff.txt').status_code, 404)

    def test_saving_an_indexable_post_notifies_once(self):
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        member = User.objects.create_user('m', password='x')
        cat = Category.objects.create(name='HRD')
        with mock.patch('common.services.indexnow.notify') as notify, \
                self.captureOnCommitCallbacks(execute=True):
            col = Question.objects.create(author=bot, category=cat, subject='칼럼', content='본문', create_date=timezone.now())
            Question.objects.create(author=member, category=cat, subject='짧은 글', content='짧음', create_date=timezone.now())
        notify.assert_called_once_with(f'https://techchang.com/{col.id}/')

    def test_submit_posts_to_indexnow_with_key_location(self):
        from common.services import indexnow
        with mock.patch('urllib.request.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            self.assertEqual(indexnow.submit(['https://techchang.com/1/', 'https://evil.example/x']), 200)
        req = urlopen.call_args[0][0]
        import json
        body = json.loads(req.data)
        self.assertEqual(body['urlList'], ['https://techchang.com/1/'])
        self.assertEqual(body['keyLocation'], f'https://techchang.com/{KEY}.txt')
