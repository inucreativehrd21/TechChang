import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from office import live
from office.models import Decision, Meeting
from office.pipeline import live_step


class LiveTests(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / 'live.json'
        patcher = override_settings(OFFICE_LIVE_PATH=str(self.path))
        patcher.enable()
        self.addCleanup(patcher.disable)

    def test_idle_without_file(self):
        snap = live.snapshot()
        self.assertEqual(snap['state'], 'idle')
        self.assertIsNone(snap['step'])
        self.assertIn('쉬는 중', snap['message'])
        self.assertTrue(snap['next']['label'])

    def test_running_step_with_agent_and_particle(self):
        live.mark('draft', 'coding', 'coding')
        snap = live.snapshot()
        self.assertEqual((snap['step'], snap['state']), ('draft', 'running'))
        self.assertIn('프로그래밍 칼럼 — 지금 프로그래밍 칼럼니스트 윤성이 원고를 쓰고 있습니다', snap['message'])
        live.mark('brief', 'lead', 'hrd')
        self.assertIn('은혜가', live.snapshot()['message'])   # 받침 없는 이름

    def test_internal_stages_fold_into_public_steps(self):
        for stage, step in (('fix', 'draft'), ('editor_revise', 'draft'), ('recheck', 'check'), ('reverify', 'check')):
            live.mark(stage, 'hrd', 'hrd')
            self.assertEqual(live.snapshot()['step'], step)

    def test_same_step_keeps_start_time(self):
        live.mark('check', 'checker')
        first = json.loads(self.path.read_text(encoding='utf-8'))['since']
        live.mark('recheck', 'checker')
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['since'], first)

    def test_stale_running_is_ignored(self):
        live.mark('review', 'editor')
        later = timezone.now() + live.STALE_AFTER + timedelta(minutes=1)
        self.assertEqual(live.snapshot(now=later)['state'], 'idle')

    def test_publish_stays_done_then_expires(self):
        live.mark('publish', 'lead', 'data')
        live.finish()  # 발행으로 끝난 작업은 finish 가 지우지 않는다
        snap = live.snapshot()
        self.assertEqual((snap['step'], snap['state']), ('publish', 'done'))
        later = timezone.now() + live.DONE_VISIBLE + timedelta(minutes=1)
        self.assertEqual(live.snapshot(now=later)['state'], 'idle')

    def test_finish_clears_failed_job(self):
        live.mark('critique', 'critic')
        live.finish()
        self.assertEqual(live.snapshot()['state'], 'idle')

    def test_waiting_for_operator_decision(self):
        m = Meeting.objects.create(week_start=date(2026, 10, 12))
        Decision.objects.create(meeting=m, kind='column', topic='hrd', question='HRD 주제', options=[{'key': 'a', 'title': 'x'}])
        snap = live.snapshot()
        self.assertEqual((snap['step'], snap['state']), ('decision', 'waiting'))
        self.assertIn('1건', snap['message'])

    def test_next_run_follows_schedule(self):
        tz = timezone.get_current_timezone()
        wed = timezone.make_aware(datetime(2026, 10, 7, 12, 0), tz)   # 수요일 낮 → 목 10:00 데이터분석
        nxt = live.next_run(wed)
        self.assertIn('10월 8일(목) 10:00', nxt['label'])
        self.assertEqual(nxt['what'], '데이터분석 칼럼 제작')
        sun = timezone.make_aware(datetime(2026, 10, 11, 19, 0), tz)  # 일요일 저녁 → 20:00 편집회의
        self.assertEqual(live.next_run(sun)['what'], '편집회의')

    def test_step_decorator_marks_before_running(self):
        seen = {}

        @live_step('draft')
        def step_draft(topic_key, *a):
            seen['during'] = live.snapshot()['step']
            return 'ok'

        self.assertEqual(step_draft('hrd'), 'ok')
        self.assertEqual(seen['during'], 'draft')
        self.assertIn('한빈', live.snapshot()['message'])

    def test_write_failure_never_raises(self):
        with mock.patch('office.live.os.replace', side_effect=OSError('disk full')):
            live.mark('draft', 'hrd', 'hrd')   # 예외가 새면 제작이 멈춘다

    def test_endpoint(self):
        live.mark('chart', 'charter', 'hrd')
        res = self.client.get('/lab/live.json', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Cache-Control'], 'no-store')
        self.assertEqual(res.json()['step'], 'chart')


class VerifiedFactsTests(TestCase):
    """운영자 확인 사항이 검증관·편집장 프롬프트에 실려 가는지 (office_revise --facts)."""

    def test_block_is_empty_without_facts(self):
        from office.pipeline import verified_block
        self.assertEqual(verified_block('  ', 'checker'), '')

    def test_checker_and_editor_receive_facts(self):
        from office import pipeline as P
        prompts = {}

        def fake(key, prompt, **kw):
            prompts[key] = prompt
            if key == 'checker':
                return {'verdict': 'pass', 'claims': []}
            return {'scores': {k: 4 for k in P.RUBRIC}, 'fatal': [], 'issues': [], 'notes': ''}

        with mock.patch('office.pipeline.ask_agent_json', side_effect=fake):
            P.step_check('제목', '본문', [], verified='- 51.8%는 원문 확인')
            P.step_review('제목', '본문', {'verdict': 'pass'}, '', verified='- 51.8%는 원문 확인')
        for key in ('checker', 'editor'):
            self.assertIn('[운영자 확인 사항', prompts[key])
            self.assertIn('51.8%는 원문 확인', prompts[key])
        self.assertIn('"verified"', prompts['checker'])
        self.assertIn('감점하거나 치명 결함으로 잡지 마세요', prompts['editor'])

    def test_without_facts_prompts_are_unchanged(self):
        from office import pipeline as P
        seen = []
        with mock.patch('office.pipeline.ask_agent_json', side_effect=lambda k, p, **kw: seen.append(p) or {'verdict': 'pass', 'claims': []}):
            P.step_check('제목', '본문', [])
        self.assertNotIn('운영자 확인 사항', seen[0])


class WebToolsTests(TestCase):
    def test_checker_gets_web_tools_and_rules(self):
        from office import pipeline as P
        seen = {}
        def fake(key, prompt, **kw):
            seen.update(prompt=prompt, tools=kw.get('tools'))
            return {'verdict': 'pass', 'claims': []}
        with mock.patch('office.pipeline.ask_agent_json', side_effect=fake):
            P.step_check('제목', '본문', [])
        self.assertEqual(seen['tools'], ('WebSearch', 'WebFetch'))
        self.assertIn('검색 결과 요약 한 줄만 보고 verified 하지 마세요', seen['prompt'])
        self.assertIn('api.crossref.org', seen['prompt'])

    def test_charter_web_data_becomes_writer_material(self):
        from office import pipeline as P
        def fake(key, prompt, **kw):
            if key == 'lead':
                return {'angle': '각도', 'data_needed': ['옛 목록']}
            self.assertEqual(kw.get('tools'), ('WebSearch', 'WebFetch'))
            return {'metrics': ['재직자 교육훈련 실시 기업 비율', '원격훈련 비율'], 'chart_plan': '막대',
                    'data': [{'metric': '재직자 교육훈련 실시 기업 비율', 'value': '51.8%', 'year': '2024',
                              'source': '기업직업훈련 실태조사', 'url': 'https://example.go.kr/x'},
                             {'metric': '지어낸 값', 'value': '99%'}]}   # url 없는 값은 버린다
        logs = []
        with mock.patch('office.pipeline.ask_agent_json', side_effect=fake):
            brief = P.step_brief('data', None, [], rec=lambda *a: logs.append(a))
        self.assertTrue(brief['data_needed'][0].startswith('재직자 교육훈련 실시 기업 비율: 51.8% (2024'))
        self.assertIn('https://example.go.kr/x', brief['data_needed'][0])
        self.assertNotIn('99%', ' '.join(brief['data_needed']))
        self.assertIn('원격훈련 비율', brief['data_needed'])          # 확인 못 한 지표는 목록으로 남는다
        self.assertTrue(any('웹에서 원문 확인한 지표 1개' in a[2] for a in logs))
        self.assertTrue(any('필요 지표 2개 제시' in a[2] for a in logs))
