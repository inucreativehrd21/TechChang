import io
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from office import datasources as DS
from office import pipeline as P

KEYS = {'KOSIS_API_KEY': 'k', 'NAVER_API_HUB_CLIENT_ID': 'i', 'NAVER_API_HUB_CLIENT_SECRET': 's'}


def resp(obj):
    return io.BytesIO(json.dumps(obj, ensure_ascii=False).encode('utf-8'))


class KosisTests(TestCase):
    def setUp(self):
        cache.clear()
        p = mock.patch.dict('os.environ', KEYS)
        p.start()
        self.addCleanup(p.stop)
        s = mock.patch('office.datasources.time.sleep')
        s.start()
        self.addCleanup(s.stop)

    SEARCH = [{'ORG_ID': '387', 'ORG_NM': '한국산업인력공단', 'TBL_ID': 'DT_A', 'TBL_NM': '재직근로자 교육훈련 실시',
               'STRT_PRD_DE': '2018', 'END_PRD_DE': '2024'},
              {'ORG_ID': '101', 'ORG_NM': '통계청', 'TBL_ID': 'DT_OLD', 'TBL_NM': '옛 표', 'END_PRD_DE': '2015'}]
    DATA = [{'PRD_DE': '2024', 'C1_NM': '전체', 'ITM_NM': '실시 비율', 'DT': '51.8', 'UNIT_NM': '%'},
            {'PRD_DE': '2024', 'C1_NM': '300인 이상', 'ITM_NM': '실시 비율', 'DT': '90.1', 'UNIT_NM': '%'}]

    def fake_urlopen(self, url, timeout=0):
        if 'statisticsSearch' in url:
            return resp(self.SEARCH)
        # 1~2단계로는 objL 누락 오류, 3단계에서 성공하는 표
        if 'objL3=ALL' in url:
            return resp(self.DATA)
        return resp({'err': '20', 'errMsg': '필수요청변수값이 누락되었습니다. (objL)'})

    def test_search_prefers_recent_tables_and_builds_https_url(self):
        with mock.patch('office.datasources.urllib.request.urlopen', side_effect=self.fake_urlopen):
            rows = DS.kosis_search('교육훈련')
        self.assertEqual(rows[0]['tbl_id'], 'DT_A')
        self.assertTrue(rows[0]['url'].startswith('https://kosis.kr/statHtml/'))

    def test_latest_retries_levels_and_prefers_total_rows(self):
        with mock.patch('office.datasources.urllib.request.urlopen', side_effect=self.fake_urlopen) as op:
            out = DS.kosis_latest('387', 'DT_A')
        self.assertEqual(out['period'], '2024')
        self.assertEqual(out['rows'], [{'label': '실시 비율', 'value': '51.8', 'unit': '%'}])
        self.assertEqual(op.call_count, 3)                  # 1·2단계 실패 후 3단계

    def test_brief_gets_official_lines_and_facts(self):
        def fake_agent(key, prompt, **kw):
            if key == 'lead':
                return {'angle': '각도'}
            return {'metrics': ['재직자 교육훈련 실시 비율'], 'kosis_terms': ['재직자 교육훈련']}
        logs = []
        with mock.patch('office.datasources.urllib.request.urlopen', side_effect=self.fake_urlopen), \
                mock.patch('office.pipeline.ask_agent_json', side_effect=fake_agent):
            brief = P.step_brief('hrd', None, [], rec=lambda *a: logs.append(a))
        first = brief['data_needed'][0]
        self.assertIn('[KOSIS 공식 통계] 재직근로자 교육훈련 실시', first)
        self.assertIn('실시 비율 51.8%', first)
        self.assertIn('https://kosis.kr/statHtml/', first)
        facts = P.brief_facts(brief)
        self.assertIn('verified', facts)
        self.assertIn('51.8%', facts)
        self.assertTrue(any('KOSIS 공식 통계표' in a[2] for a in logs))

    def test_no_key_means_silent_empty(self):
        with mock.patch.dict('os.environ', {'KOSIS_API_KEY': ''}), \
                mock.patch('office.datasources.urllib.request.urlopen') as op:
            self.assertEqual(DS.kosis_lookup(['고용률']), [])
        op.assert_not_called()


class NaverTrendTests(TestCase):
    def test_trend_summary_and_note(self):
        series = [{'period': f'2025-{m:02d}-01', 'ratio': r} for m, r in
                  zip(range(1, 13), [10, 10, 10, 10, 10, 10, 20, 20, 20, 40, 40, 40])]
        body = {'results': [{'title': '학습 전이 점검', 'data': series}]}
        with mock.patch.dict('os.environ', KEYS), \
                mock.patch('office.datasources.urllib.request.urlopen', return_value=resp(body)) as op:
            out = DS.naver_trend([{'name': '학습 전이 점검', 'keywords': ['학습 전이']}])
        req = op.call_args.args[0]
        self.assertEqual(req.get_header('X-ncp-apigw-api-key-id'), 'i')
        d = out['학습 전이 점검']
        self.assertEqual((d['recent'], d['prev'], d['change']), (40.0, 20.0, 100))
        self.assertIn('직전 3개월 대비 +100%', DS.demand_note(d))

    def test_meeting_attaches_demand_to_options(self):
        from office.management.commands.hold_meeting import Command
        decisions = [{'kind': 'column', 'options': [{'key': 'a', 'title': '주제 A', 'keywords': ['검색어 A']},
                                                    {'key': 'b', 'title': '주제 B', 'keywords': []}]}]
        with mock.patch('office.datasources.naver_trend',
                        return_value={'주제 A': {'recent': 55.0, 'prev': 50.0, 'change': 10, 'peak': 100}}):
            Command._attach_demand(decisions)
        self.assertIn('네이버 검색 수요 55', decisions[0]['options'][0]['demand_note'])
        self.assertNotIn('demand_note', decisions[0]['options'][1])


class KosisLabelTests(TestCase):
    def test_case_counts_and_repeated_title_are_dropped(self):
        cache.clear()
        rows = [{'PRD_DE': '2024', 'TBL_NM': '재직근로자 교육훈련 미치는 효과', 'C1_NM': '직원의 직무능력 향상',
                 'C2_NM': '재직근로자 교육훈련 미치는 효과', 'ITM_NM': '사례수', 'DT': '72267', 'UNIT_NM': '개'},
                {'PRD_DE': '2024', 'TBL_NM': '재직근로자 교육훈련 미치는 효과', 'C1_NM': '직원의 직무능력 향상',
                 'C2_NM': '재직근로자 교육훈련 미치는 효과', 'ITM_NM': '점수', 'DT': '3.92', 'UNIT_NM': '점'}]
        with mock.patch.dict('os.environ', KEYS), mock.patch('office.datasources.time.sleep'), \
                mock.patch('office.datasources.urllib.request.urlopen', return_value=resp(rows)):
            out = DS.kosis_latest('387', 'DT_X')
        self.assertEqual(out['rows'], [{'label': '점수', 'value': '3.92', 'unit': '점'}])

    def test_measure_in_class_column_is_handled(self):
        # 실제 표(DT_118041_B020 류): 측정값이 C2 에, 표 이름이 항목명에 들어 있다
        cache.clear()
        rows = [{'PRD_DE': '2024', 'C1_NM': c1, 'C2_NM': c2, 'ITM_NM': '재직근로자 교육훈련 미치는 효과', 'DT': dt, 'UNIT_NM': u}
                for c1, c2, dt, u in (('직무능력 향상', '사례수', '72267', '개'), ('직무능력 향상', '점수', '3.92', '점'),
                                      ('동기부여', '사례수', '72267', '개'), ('동기부여', '점수', '3.71', '점'))]
        with mock.patch.dict('os.environ', KEYS), mock.patch('office.datasources.time.sleep'), \
                mock.patch('office.datasources.urllib.request.urlopen', return_value=resp(rows)):
            out = DS.kosis_latest('387', 'DT_Y')
        self.assertEqual([r['label'] for r in out['rows']], ['직무능력 향상', '동기부여'])
        self.assertEqual([r['value'] for r in out['rows']], ['3.92', '3.71'])


class KosisBaseRowTests(TestCase):
    def test_hundred_percent_base_rows_are_dropped(self):
        cache.clear()
        rows = [{'PRD_DE': '2024', 'C1_NM': c1, 'ITM_NM': '비율', 'DT': dt, 'UNIT_NM': '%'}
                for c1, dt in (('전체', '100'), ('예', '60.2'), ('아니오', '39.8'))]
        with mock.patch.dict('os.environ', KEYS), mock.patch('office.datasources.time.sleep'), \
                mock.patch('office.datasources.urllib.request.urlopen', return_value=resp(rows)):
            out = DS.kosis_latest('387', 'DT_Z')
        self.assertEqual([(r['label'], r['value']) for r in out['rows']], [('예', '60.2'), ('아니오', '39.8')])
