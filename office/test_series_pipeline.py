"""연재 회차 연구실 검증(office.series_pipeline) — 모델 호출은 가짜로 바꿔 흐름만 확인한다."""
from datetime import datetime, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from community import series_catalog as C
from community.models import Category, ColumnSeries, Question
from office import series_pipeline as S
from office.models import ColumnDraft, WorkLog

BODY = ('Django는 요청을 받으면 주소를 보고 알맞은 함수를 찾아 실행합니다. 이 과정을 차근차근 따라가 보겠습니다. ' * 40)


def episode(title='URL 한 줄의 정체', body=BODY, key='django'):
    heads = C.REQUIRED_HEADINGS[key]
    sections = '\n\n'.join(f'{h} 소제목\n{body[:len(body) // len(heads)]}' for h in heads)
    return (f'TITLE: {title}\n---\n리드 문단입니다. 오늘은 주소와 함수의 연결을 살펴보겠습니다.\n\n'
            f'```python\npath("", views.index)\n```\n\n{sections}\n\n---\n*📚 시리즈 · 2편*\n*테크창 연구팀*\n')


def fake_json(score=5, critical=()):
    def _ask(key, prompt, **kw):
        if key == 'checker':
            return {'claims': [{'claim': 'path() 사용법', 'status': 'verified',
                                'note': 'https://docs.djangoproject.com/en/5.2/ref/urls/'}],
                    'critical': list(critical)}
        return {'scores': {k: score for k in S.SERIES_RUBRIC}, 'fatal': [], 'issues': ['예시를 하나 더'],
                'strengths': '코드가 실제와 같다', 'notes': '좋습니다'}
    return _ask


CRITIQUE = {'verdict': 'recommend', 'reason': '따라 하기 쉽다', 'issues': [], 'strengths': []}


class SeriesPipelineTests(TestCase):
    def setUp(self):
        self.cat = Category.objects.create(name='프로그래밍')
        self.bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        cfg = C.SERIES['django']
        self.series = ColumnSeries.objects.create(slug=cfg['slug'], title=cfg['title'], category=self.cat,
                                                  total_episodes=10)
        for p in (mock.patch('office.series_pipeline.live'), mock.patch('office.pipeline.live'),
                  mock.patch('office.pipeline.step_critique', return_value=CRITIQUE)):
            p.start()
            self.addCleanup(p.stop)

    def run_new(self, score=5, critical=(), text=None):
        with mock.patch('office.series_pipeline.ask_agent', return_value=text or episode()), \
             mock.patch('office.series_pipeline.ask_agent_json', side_effect=fake_json(score, critical)):
            return S.produce_episode('django', 2, out=lambda *_: None)

    def test_passing_episode_is_published_with_making_of(self):
        res = self.run_new(score=5)
        self.assertEqual(res['status'], 'published')
        q = res['question']
        self.assertEqual((q.series_id, q.episode_number, q.subject), (self.series.id, 2, '2편 — URL 한 줄의 정체'))
        draft = q.office_draft
        self.assertEqual((draft.series_key, draft.qa_report['rubric'], draft.qa_score), ('django', 'series', 100))
        from office.making import build_making
        mk = build_making(draft)
        self.assertEqual([r['label'] for r in mk['rubric']][0], '정확성')
        self.assertTrue(WorkLog.objects.filter(draft=draft, action='check').exists())

    def test_failing_episode_is_held_and_admin_can_publish_it(self):
        res = self.run_new(score=3)
        self.assertEqual(res['status'], 'hold')
        self.assertFalse(Question.objects.filter(series=self.series).exists())
        admin = User.objects.create_user('boss', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        with mock.patch('office.views.admin_required', lambda f: f):
            from office.views import draft_publish
            from django.test import RequestFactory
            req = RequestFactory().post('/')
            req.user = admin
            req._messages = mock.MagicMock()
            draft_publish(req, res['draft'].id)
        q = Question.objects.get(series=self.series)
        self.assertEqual(q.episode_number, 2)

    def test_critical_code_issue_left_unresolved_blocks_publishing(self):
        res = self.run_new(score=5, critical=['views.index 가 정의되지 않아 실행 불가'])
        self.assertEqual(res['status'], 'hold')
        self.assertIn('code_wrong', res['draft'].qa_report['fatal'])

    def test_remake_updates_in_place_only_when_it_passes(self):
        old = Question.objects.create(author=self.bot, category=self.cat, series=self.series, episode_number=2,
                                      subject='2편 — 옛 제목', content='옛 본문', create_date=timezone.now())
        Question.objects.filter(pk=old.pk).update(view_count=52)
        with mock.patch('office.series_pipeline.ask_agent', return_value=episode()), \
             mock.patch('office.series_pipeline.ask_agent_json', side_effect=fake_json(2)):
            res = S.produce_episode('django', 2, target=old, out=lambda *_: None)
        old.refresh_from_db()
        self.assertEqual((res['status'], old.content), ('hold', '옛 본문'))      # 미달 → 원문 유지
        with mock.patch('office.series_pipeline.ask_agent', return_value=episode()), \
             mock.patch('office.series_pipeline.ask_agent_json', side_effect=fake_json(5)):
            res = S.produce_episode('django', 2, target=old, out=lambda *_: None)
        old.refresh_from_db()
        self.assertEqual(res['status'], 'updated')
        self.assertEqual((old.subject, old.view_count, Question.objects.filter(series=self.series).count()),
                         ('2편 — URL 한 줄의 정체', 52, 1))                        # 같은 글·조회수 유지
        self.assertEqual(old.office_draft.target_question_id, old.id)

    def test_rewrite_without_column_sections_is_accepted_and_rescored(self):
        """연재에는 칼럼의 '참고 자료' 섹션이 없다 — 재작성본을 잘림으로 버리면 보완 기회가 사라진다(10/10 0편)."""
        scores = iter([3, 5])

        def ask_json(key, prompt, **kw):
            if key == 'checker':
                return fake_json()(key, prompt)
            score = next(scores)                       # 첫 심사 3점(60) → 보완 → 재심 5점(100)
            return {'scores': {k: score for k in S.SERIES_RUBRIC}, 'fatal': [], 'issues': ['코드 설명 보강'],
                    'notes': ''}

        rewrite = episode(title='URL 한 줄의 정체 — 고친 판', body=BODY + '보강한 설명입니다. ' * 30)
        with mock.patch('office.series_pipeline.ask_agent', side_effect=[episode(), rewrite]), \
             mock.patch('office.series_pipeline.ask_agent_json', side_effect=ask_json):
            res = S.produce_episode('django', 2, out=lambda *_: None)
        self.assertEqual(res['status'], 'published')
        self.assertIn('고친 판', res['question'].subject)
        self.assertEqual(S.looks_truncated('django', episode()), '')
        self.assertIn('서명', S.looks_truncated('django', episode().rsplit('---', 1)[0]))

    def test_code_changed_by_editor_rewrite_is_rechecked(self):
        """편집장 지적으로 코드가 바뀐 재작성본은 검증관이 다시 본다(10/10 0편: 재검증 없이 발행됐다)."""
        calls, scores = [], iter([3, 5])

        def ask_json(key, prompt, **kw):
            calls.append(key)
            if key == 'checker':
                return fake_json()(key, prompt)
            score = next(scores)
            return {'scores': {k: score for k in S.SERIES_RUBRIC}, 'fatal': [], 'issues': ['코드 보강'], 'notes': ''}

        new_code = episode().replace('path("", views.index)', 'path("", views.index, name="index")')
        with mock.patch('office.series_pipeline.ask_agent', side_effect=[episode(), new_code]), \
             mock.patch('office.series_pipeline.ask_agent_json', side_effect=ask_json):
            S.produce_episode('django', 2, out=lambda *_: None)
        self.assertEqual(calls.count('checker'), 2)

    def test_full_outline_reaches_writer_and_checker(self):
        prompts = {}

        def ask(key, prompt, **kw):
            prompts['writer'] = prompt
            return episode()

        def ask_json(key, prompt, **kw):
            prompts.setdefault(key, prompt)
            return fake_json()(key, prompt)

        with mock.patch('office.series_pipeline.ask_agent', side_effect=ask), \
             mock.patch('office.series_pipeline.ask_agent_json', side_effect=ask_json):
            S.produce_episode('django', 2, out=lambda *_: None)
        last = C.OUTLINES['django'][-1]['title']
        for who in ('writer', 'checker', 'editor'):
            self.assertIn(last, prompts[who])
        self.assertIn('2편: URL 한 줄의 정체 (라우팅)  ← 이번 회차', prompts['writer'])

    def test_precheck_ignores_comments_inside_code(self):
        text = episode().replace('path("", views.index)', '# config/urls.py\npath("", views.index)')
        self.assertFalse(any('H1' in i for i in S.precheck('django', text)))
        self.assertTrue(any('H1' in i for i in S.precheck('django', '# 제목\n' + text)))

    def test_precheck_catches_structure_and_length(self):
        issues = S.precheck('django', '짧은 글입니다.')
        self.assertTrue(any('하한' in i for i in issues))
        self.assertTrue(any('필수 소제목' in i for i in issues))

    def test_command_remake_all_runs_each_published_episode(self):
        for no in (0, 1):
            Question.objects.create(author=self.bot, category=self.cat, series=self.series, episode_number=no,
                                    subject=f'{no}편', content='x', create_date=timezone.now())
        with mock.patch('office.series_pipeline.produce_episode', return_value={'status': 'failed'}) as prod, \
             mock.patch('office.live.finish'), mock.patch('django.core.management.call_command'):
            call_command('auto_write_series', '--series', 'django', '--remake', 'all', stdout=mock.MagicMock(),
                         stderr=mock.MagicMock())
        self.assertEqual([c.args[1] for c in prod.call_args_list], [0, 1])
        self.assertTrue(all(c.kwargs['target'] is not None for c in prod.call_args_list))


class LimitRetryTests(TestCase):
    """구독 사용 한도에 걸리면 남은 회차를 헛돌리지 않고 멈추거나(기본), 초기화 뒤 이어 간다(--wait-on-limit)."""
    LIMIT = "Claude CLI 호출 실패(API 폴백 꺼짐): You've hit your session limit · resets 1am (Asia/Seoul)"

    def test_wait_seconds_until_reset(self):
        from common.management.commands.auto_write_series import limit_wait_seconds
        now = timezone.make_aware(datetime(2026, 10, 10, 0, 40))
        self.assertEqual(limit_wait_seconds(self.LIMIT, now), 20 * 60 + 180)
        self.assertEqual(limit_wait_seconds('resets 2pm', now), None)               # 한도 문구가 아니면 대기 없음
        self.assertEqual(limit_wait_seconds("hit your usage limit", now), 1800)    # 시각을 못 읽으면 30분

    def test_remake_stops_on_limit_and_retries_with_flag(self):
        cat = Category.objects.create(name='프로그래밍')
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        s = ColumnSeries.objects.create(slug=C.SERIES['django']['slug'], title='t', category=cat, total_episodes=10)
        for no in (0, 1):
            Question.objects.create(author=bot, category=cat, series=s, episode_number=no, subject=f'{no}편',
                                    content='x', create_date=timezone.now())
        failed = {'status': 'failed', 'reason': self.LIMIT, 'draft': None}
        ok = {'status': 'hold', 'score': 70, 'draft': mock.MagicMock(target_question_id=1)}
        quiet = {'stdout': mock.MagicMock(), 'stderr': mock.MagicMock()}
        with mock.patch('office.series_pipeline.produce_episode', return_value=failed) as prod, \
             mock.patch('office.live.finish'), mock.patch('django.core.management.call_command'):
            call_command('auto_write_series', '--series', 'django', '--remake', 'all', **quiet)
        self.assertEqual(prod.call_count, 1)                       # 첫 회차에서 멈춤 — 나머지를 헛돌리지 않는다
        with mock.patch('office.series_pipeline.produce_episode', side_effect=[failed, ok, ok]) as prod, \
             mock.patch('common.management.commands.auto_write_series.time.sleep') as slept, \
             mock.patch('office.live.finish'), mock.patch('django.core.management.call_command'):
            call_command('auto_write_series', '--series', 'django', '--remake', 'all', '--wait-on-limit', **quiet)
        self.assertEqual((prod.call_count, slept.call_count), (3, 1))   # 0편 재시도 후 1편까지


class ScheduleTests(TestCase):
    def test_series_alternate_and_respect_min_gap(self):
        now = timezone.make_aware(datetime(2026, 10, 10, 15))
        self.assertEqual(C.next_publish_at('agent', now, now).date().isoformat(), '2026-10-26')
        self.assertEqual(C.next_publish_at('django', now - timedelta(days=5), now).date().isoformat(), '2026-10-19')
        self.assertTrue(C.too_soon(now - timedelta(days=2), now))
        self.assertFalse(C.too_soon(now - timedelta(days=14), now))


class SeriesPagesTests(TestCase):
    def setUp(self):
        cat = Category.objects.create(name='프로그래밍')
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        cfg = C.SERIES['agent']
        self.s = ColumnSeries.objects.create(slug=cfg['slug'], title=cfg['title'], category=cat, total_episodes=10)
        self.ep = Question.objects.create(author=bot, category=cat, series=self.s, episode_number=0,
                                          subject='오리엔테이션', content='본문 ' * 300, create_date=timezone.now())

    def test_index_and_detail_show_planned_episodes_on_pc_and_mobile(self):
        for ua in ('Mozilla/5.0 (Windows NT 10.0) Chrome/130', 'Mozilla/5.0 (iPhone) Mobile/15E148'):
            index = self.client.get('/series/', HTTP_USER_AGENT=ua).content.decode()
            self.assertIn(self.s.title, index)
            self.assertIn('다음 공개', index)
            detail = self.client.get(f'/series/{self.s.slug}/', HTTP_USER_AGENT=ua).content.decode()
            self.assertIn(C.OUTLINES['agent'][9]['title'], detail)          # 아직 안 나온 마지막 회차 제목
            self.assertIn('"@type": "ItemList"', detail)

    def test_carousel_arrows_appear_only_with_two_or_more_series(self):
        index = self.client.get('/series/').content.decode()
        self.assertIn('data-sr-carousel', index)
        self.assertNotIn('sr-arrow-prev', index)                            # 연재가 하나면 넘길 것이 없다
        cfg = C.SERIES['django']
        s2 = ColumnSeries.objects.create(slug=cfg['slug'], title=cfg['title'], category=self.s.category, total_episodes=10)
        Question.objects.create(author=self.ep.author, category=self.s.category, series=s2, episode_number=0,
                                subject='django 0편', content='본문', create_date=timezone.now() - timedelta(days=90))
        index = self.client.get('/series/').content.decode()
        self.assertIn('sr-arrow-prev', index)
        self.assertEqual(index.count('class="sr-dot"'), 2)
        self.assertLess(index.index(f'data-slug="{self.s.slug}"'), index.index(f'data-slug="{s2.slug}"'))  # 최근 시작한 연재가 첫 장
        self.assertNotIn(f'id="{self.s.slug}"', index)                      # 해시와 같은 id 가 있으면 브라우저가 스크롤한다
