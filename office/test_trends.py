"""편집회의 트렌드 정찰·검색 수요 잣대(office/trends.py, 2026-10-16)."""
import io
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from office import trends as T

AD_KEYS = {'NAVER_SEARCHAD_API_KEY': 'ak', 'NAVER_SEARCHAD_SECRET_KEY': 'sk', 'NAVER_SEARCHAD_CUSTOMER_ID': '77'}
HUB_KEYS = {'NAVER_API_HUB_CLIENT_ID': 'i', 'NAVER_API_HUB_CLIENT_SECRET': 's'}
NO_AD = {k: '' for k in AD_KEYS}


def resp(obj):
    return io.BytesIO(json.dumps(obj, ensure_ascii=False).encode('utf-8'))


GEEK = b"""<?xml version='1.0' encoding='UTF-8'?><feed xmlns='http://www.w3.org/2005/Atom'><title>GeekNews</title>
<entry><title>Claude Code 2.0 \xec\xb6\x9c\xec\x8b\x9c</title><link href='https://news.hada.io/topic?id=1'/></entry>
<entry><title>uv 0.9</title><link href='https://news.hada.io/topic?id=2'/></entry></feed>"""
GT = """<?xml version="1.0" encoding="UTF-8"?><rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>제미나이</title><ht:approx_traffic>2,000+</ht:approx_traffic>
<ht:news_item><ht:news_item_title>제미나이 새 모델 공개</ht:news_item_title></ht:news_item></item>
<item><title>야구</title><ht:approx_traffic>100+</ht:approx_traffic></item></channel></rss>""".encode('utf-8')


class SourceTests(TestCase):
    def test_geeknews_and_google_trends_parse(self):
        with mock.patch('office.trends._fetch', return_value=GEEK):
            g = T.geeknews()
        self.assertEqual(g[0], {'title': 'Claude Code 2.0 출시', 'url': 'https://news.hada.io/topic?id=1'})
        with mock.patch('office.trends._fetch', return_value=GT):
            t = T.google_trends()
        self.assertEqual(t[0], {'title': '제미나이', 'traffic': '2,000+', 'news': '제미나이 새 모델 공개'})
        self.assertEqual(t[1]['news'], '')

    def test_sources_fail_soft(self):
        with mock.patch('office.trends._fetch', side_effect=OSError('down')):
            self.assertEqual(T.geeknews(), [])
            self.assertEqual(T.google_trends(), [])


class DemandTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_searchad_volume_signs_request_and_maps_spaced_keywords(self):
        rows = {'keywordList': [{'relKeyword': '클로드코드', 'monthlyPcQcCnt': 1200, 'monthlyMobileQcCnt': 3400},
                                {'relKeyword': '직무교육', 'monthlyPcQcCnt': '< 10', 'monthlyMobileQcCnt': 20},
                                {'relKeyword': '관련없는말', 'monthlyPcQcCnt': 99999, 'monthlyMobileQcCnt': 0}]}
        with mock.patch.dict('os.environ', AD_KEYS), \
                mock.patch('office.trends.urllib.request.urlopen', return_value=resp(rows)) as op:
            out = T.searchad_volumes(['클로드 코드', '직무교육'])
        req = op.call_args.args[0]
        self.assertEqual(req.get_header('X-api-key'), 'ak')
        self.assertEqual(req.get_header('X-customer'), '77')
        self.assertTrue(req.get_header('X-signature'))
        self.assertIn('hintKeywords=%ED%81%B4', req.full_url)          # 띄어쓰기를 뺀 검색어로 묻는다
        self.assertEqual(out, {'클로드 코드': 4600, '직무교육': 25})

    def test_datalab_index_scales_by_anchor_and_counts_missing_weeks_as_zero(self):
        res = {'results': [{'title': '파이썬', 'data': [{'ratio': 100}, {'ratio': 80}, {'ratio': 60}, {'ratio': 60}]},
                           {'title': '직무교육', 'data': [{'ratio': 15}, {'ratio': 5}]},       # 두 주는 응답에 없다
                           {'title': '없는말', 'data': []}]}
        with mock.patch.dict('os.environ', dict(HUB_KEYS, **NO_AD)), \
                mock.patch('office.trends.urllib.request.urlopen', return_value=resp(res)):
            out = T.datalab_index(['직무교육', '없는말'])
        self.assertEqual(out, {'직무교육': 6.67, '없는말': 0.0})            # (20/4) / (300/4) * 100

    def test_measure_prefers_searchad_and_caches(self):
        with mock.patch.dict('os.environ', AD_KEYS), \
                mock.patch('office.trends.searchad_volumes', return_value={'a': 10}) as sv:
            self.assertEqual(T.measure(['a']), ({'a': 10}, 'volume'))
            self.assertEqual(T.measure(['a']), ({'a': 10}, 'volume'))
        self.assertEqual(sv.call_count, 1)
        with mock.patch.dict('os.environ', NO_AD), \
                mock.patch('office.trends.datalab_index', return_value={'b': 3.5}):
            self.assertEqual(T.measure(['b']), ({'b': 3.5}, 'index'))
        self.assertEqual(T.demand_label(4600, 'volume'), '월 4,600회 검색')
        self.assertEqual(T.demand_label(3.5, 'index'), '수요 지수 3.5')


SCOUTED = {
    'hrd': [{'topic': '국민내일배움카드 개편', 'why': '11월 제도 변경', 'url': 'https://x', 'keywords': ['내일배움카드']},
            {'topic': '온보딩 체크리스트', 'why': '채용 시즌', 'url': 'https://y', 'keywords': ['온보딩', '신입 온보딩']}],
    'data': [], 'coding': [{'topic': '클로드 코드 쓰는 법', 'why': '새 버전', 'url': 'https://z',
                            'keywords': ['클로드 코드']}],
}


class ScoutTests(TestCase):
    def setUp(self):
        cache.clear()
        for p in (mock.patch('office.trends.geeknews', return_value=[{'title': 'uv 0.9', 'url': ''}]),
                  mock.patch('office.trends.google_trends', return_value=[])):
            p.start()
            self.addCleanup(p.stop)

    def test_candidates_sorted_by_demand_and_briefed(self):
        seen = {}

        def ask(prompt, tools):
            seen.update(prompt=prompt, tools=tools)
            return SCOUTED

        vols = {'내일배움카드': 90000, '온보딩': 3000, '신입 온보딩': 400, '클로드 코드': 5000}
        with mock.patch('office.trends.measure', return_value=(vols, 'volume')):
            tr = T.scout(['지난 칼럼 제목'], ask_json=ask, tools=('WebSearch', 'WebFetch'))
        self.assertIn('uv 0.9', seen['prompt'])
        self.assertIn('지난 칼럼 제목', seen['prompt'])
        self.assertEqual(seen['tools'], ('WebSearch', 'WebFetch'))
        hrd = tr['fields']['hrd']
        self.assertEqual([i['topic'] for i in hrd], ['국민내일배움카드 개편', '온보딩 체크리스트'])
        self.assertEqual((hrd[1]['demand_kw'], hrd[1]['demand']), ('온보딩', 3000))
        text = '\n'.join(T.brief_lines(tr))
        self.assertIn('[이번 주 트렌드·검색 수요]', text)
        self.assertIn("검색어 '내일배움카드' 월 90,000회 검색", text)
        self.assertIn('네이버 월간 검색수', text)
        self.assertNotIn('데이터분석:', text)                               # 후보 없는 분야는 줄을 만들지 않는다

    def test_scout_failure_does_not_block(self):
        tr = T.scout([], ask_json=mock.Mock(side_effect=ValueError('json')))
        self.assertEqual(tr['fields'], {})
        self.assertIn('정찰 실패', tr['note'])
        self.assertEqual(T.brief_lines(tr), [])


class RankOptionsTests(TestCase):
    def test_column_options_reordered_rekeyed_and_top_recommended(self):
        decisions = [
            {'kind': 'column', 'topic': 'hrd', 'options': [
                {'key': 'a', 'title': 'A', 'keywords': ['적은말']},
                {'key': 'b', 'title': 'B', 'keywords': ['많은말', '적은말']},
                {'key': 'c', 'title': 'C', 'keywords': []}]},
            {'kind': 'series', 'options': [{'key': 'a', 'title': 'S1', 'keywords': ['적은말']},
                                           {'key': 'b', 'title': 'S2', 'keywords': ['많은말']}]},
            {'kind': 'dev', 'options': [{'key': 'a', 'title': '로그 정리'}]},
        ]
        with mock.patch('office.trends.measure', return_value=({'적은말': 50, '많은말': 7000}, 'volume')):
            r = T.rank_options(decisions)
        col = decisions[0]['options']
        self.assertEqual([(o['key'], o['title']) for o in col], [('a', 'B'), ('b', 'A'), ('c', 'C')])
        self.assertTrue(col[0]['recommended'])
        self.assertFalse(col[1]['recommended'])
        self.assertEqual(col[0]['demand_note'], "네이버 검색어 '많은말' 월 7,000회 검색")
        self.assertEqual([o['title'] for o in decisions[1]['options']], ['S1', 'S2'])   # 연재는 수요만 달고 순서 유지
        self.assertNotIn('recommended', decisions[1]['options'][0])
        self.assertNotIn('demand', decisions[2]['options'][0])
        self.assertEqual(r['measured'], 4)

    def test_no_measurement_keeps_order(self):
        decisions = [{'kind': 'column', 'options': [{'key': 'a', 'title': 'A', 'keywords': ['x']},
                                                    {'key': 'b', 'title': 'B', 'keywords': ['y']}]}]
        with mock.patch('office.trends.measure', return_value=({}, 'index')):
            T.rank_options(decisions)
        self.assertEqual([o['title'] for o in decisions[0]['options']], ['A', 'B'])
        self.assertFalse(any(o.get('recommended') for o in decisions[0]['options']))
