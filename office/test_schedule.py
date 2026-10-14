"""예약 공개 — 전날 미리 만들어 심사·보완을 끝내 두고(공개 대기) 정해진 시각에 공개한다(office.schedule)."""
from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office import pipeline as P
from office import schedule as S
from office.models import ColumnDraft, WorkLog
from office.publiclog import public_line
from office.test_publish_flow import column, qa


def kst(*a):
    return timezone.make_aware(datetime(*a))


class SlotTests(TestCase):
    def test_column_slot_is_the_next_publish_time(self):
        mon = kst(2026, 10, 19, 13, 0)                      # 월 13:00 → 화 10:00
        self.assertEqual(S.column_slot('hrd', mon), kst(2026, 10, 20, 10, 0))
        self.assertEqual(S.column_slot('hrd', kst(2026, 10, 20, 9, 0)), kst(2026, 10, 20, 10, 0))
        self.assertEqual(S.column_slot('hrd', kst(2026, 10, 20, 11, 0)), kst(2026, 10, 27, 10, 0))
        self.assertEqual(S.column_slot('data', mon), kst(2026, 10, 22, 10, 0))
        self.assertEqual(S.column_slot('coding', mon), kst(2026, 10, 24, 10, 0))
        # 당일 안전망 — 공개 요일이면 오늘 10시, 아니면 없음
        self.assertEqual(S.column_slot('hrd', kst(2026, 10, 20, 10, 0), upcoming=False), kst(2026, 10, 20, 10, 0))
        self.assertIsNone(S.column_slot('hrd', kst(2026, 10, 21, 10, 0), upcoming=False))

    def test_series_slot_uses_the_publish_day_week(self):
        key, at = S.series_slot(kst(2026, 10, 18, 13, 0))   # 일요일(ISO 42주) → 월요일(43주, 홀수 = django)
        self.assertEqual((key, at), ('django', kst(2026, 10, 19, 10, 0)))
        key, at = S.series_slot(kst(2026, 10, 25, 13, 0))   # 다음 일요일 → 44주(짝수 = agent)
        self.assertEqual((key, at), ('agent', kst(2026, 10, 26, 10, 0)))
        self.assertEqual(S.series_slot(kst(2026, 10, 20, 10, 0), upcoming=False), (None, None))


class ReadyAndReleaseTests(TestCase):
    def setUp(self):
        Category.objects.get_or_create(name='HRD')

    def draft(self, at, **kw):
        return ColumnDraft.objects.create(topic='hrd', subject='미리 만든 칼럼', content=column(30), publish_at=at,
                                          status=kw.pop('status', ColumnDraft.STATUS_HOLD),
                                          qa_report={'score': 84, 'verdict': 'accept'}, **kw)

    def test_future_slot_waits_and_past_slot_publishes(self):
        d = self.draft(timezone.now() + timedelta(hours=20))
        self.assertIsNone(S.finish_accepted(d, P.publish_draft))
        d.refresh_from_db()
        self.assertEqual(d.status, ColumnDraft.STATUS_READY)
        self.assertFalse(Question.objects.exists())
        late = self.draft(timezone.now() - timedelta(minutes=5))
        q = S.finish_accepted(late, P.publish_draft)          # 예정 시각이 지났으면 바로
        self.assertIsNotNone(q)
        self.assertEqual(late.status, ColumnDraft.STATUS_PUBLISHED)

    def test_release_publishes_only_due_ready_drafts(self):
        due = self.draft(timezone.now() - timedelta(minutes=1), status=ColumnDraft.STATUS_READY)
        later = self.draft(timezone.now() + timedelta(hours=3), status=ColumnDraft.STATUS_READY)
        with mock.patch('django.core.management.call_command'):
            call_command('office_release', stdout=StringIO())
        due.refresh_from_db(); later.refresh_from_db()
        self.assertEqual((due.status, later.status), (ColumnDraft.STATUS_PUBLISHED, ColumnDraft.STATUS_READY))
        log = WorkLog.objects.get(action='publish', draft=due)
        self.assertIn(f'(id={due.question_id}, 84점)', log.text)    # 프리미엄·피드가 읽는 형식 그대로

    def test_public_feed_hides_title_until_published(self):
        d = self.draft(timezone.now() + timedelta(hours=20))
        w = WorkLog.objects.create(agent='hrd', action='draft', text='초안 완성: 미리 만든 칼럼 (3000자)', draft=d)
        self.assertNotIn('미리 만든 칼럼', public_line(w))
        r = WorkLog.objects.create(agent='lead', action='ready', text=S.ready_line(d), draft=d)
        self.assertIn('공개 시각을 기다립니다', public_line(r))
        d.status = ColumnDraft.STATUS_PUBLISHED
        d.save()
        self.assertIn('미리 만든 칼럼', public_line(w))

    def test_admin_can_publish_ready_draft_now(self):
        admin = User.objects.create_superuser('admin', 'a@example.com', 'x')
        self.client.force_login(admin)
        d = self.draft(timezone.now() + timedelta(hours=20), status=ColumnDraft.STATUS_READY)
        self.client.post(f'/lab/admin/draft/{d.id}/publish/', {'now': '1'}, HTTP_USER_AGENT='Mozilla/5.0')
        d.refresh_from_db()
        self.assertEqual(d.status, ColumnDraft.STATUS_PUBLISHED)
        # 검수 대기 원고를 '그대로 발행' — 예정 시각 전이면 공개 대기로
        h = self.draft(timezone.now() + timedelta(hours=20))
        self.client.post(f'/lab/admin/draft/{h.id}/publish/', HTTP_USER_AGENT='Mozilla/5.0')
        h.refresh_from_db()
        self.assertEqual(h.status, ColumnDraft.STATUS_READY)


class PrepareFlowTests(TestCase):
    """office_publish --prepare / --if-missing (모델 호출은 가짜, test_publish_flow 와 같은 방식)."""

    def run_cmd(self, reviews, **kw):
        patches = [
            mock.patch.object(P, 'step_brief', return_value={'angle': '각도'}),
            mock.patch.object(P, 'step_blueprint', return_value=({}, {})),
            mock.patch.object(P, 'step_draft', return_value=('제목', column(30))),
            mock.patch.object(P, 'precheck_draft', return_value=[]),
            mock.patch.object(P, 'step_check', return_value={'verdict': 'pass', 'claims': []}),
            mock.patch.object(P, 'step_critique', return_value={'verdict': 'recommend', 'issues': [], 'reason': ''}),
            mock.patch.object(P, 'step_review', side_effect=list(reviews)),
            mock.patch.object(P, 'step_headline', side_effect=lambda s, c, **k: (s, '')),
            mock.patch('office.management.commands.office_publish.ask_agent', return_value=''),
            mock.patch('office.management.commands.office_publish.patch_revise',
                       side_effect=lambda w, sub, c, *a, **k: (sub, c, False, '불일치')),
            mock.patch('office.management.commands.office_publish.call_command'),
            mock.patch.object(S, 'alert_not_ready'),
        ]
        started = [p.start() for p in patches]
        try:
            out = StringIO()
            call_command('office_publish', topic='data', no_chart=True, stdout=out, **kw)
            return out.getvalue(), started[-1]
        finally:
            for p in patches:
                p.stop()

    def test_prepare_passes_and_waits_for_its_slot(self):
        out, alert = self.run_cmd([qa('accept', 86)], prepare=True)
        d = ColumnDraft.objects.latest('id')
        self.assertEqual(d.status, ColumnDraft.STATUS_READY)
        self.assertEqual(d.publish_at, S.column_slot('data'))
        self.assertFalse(Question.objects.exists())
        self.assertTrue(WorkLog.objects.filter(draft=d, action='ready').exists())
        alert.assert_not_called()
        out2, _ = self.run_cmd([], prepare=True)                  # 같은 시각 몫이 있으면 다시 만들지 않는다
        self.assertIn('이미 있습니다', out2)
        self.assertEqual(ColumnDraft.objects.count(), 1)

    def test_prepare_hold_alerts_operator_and_blocks_retry(self):
        left = {**qa('minor', 70), 'must_fix': [{'where': '서두', 'problem': '조건 개수 불일치', 'fix': '다섯 개로'}]}
        _out, alert = self.run_cmd([qa('minor', 66), left, left], prepare=True)
        d = ColumnDraft.objects.latest('id')
        self.assertEqual(d.status, ColumnDraft.STATUS_HOLD)
        alert.assert_called_once()
        out2, _ = self.run_cmd([], prepare=True)                  # 보류 중이면 22시 재시도도 건너뛴다(운영자 차례)
        self.assertIn('이미 있습니다', out2)

    def test_if_missing_publishes_immediately_when_nothing_was_prepared(self):
        Category.objects.get_or_create(name='데이터분석')
        past = timezone.now() - timedelta(minutes=1)
        with mock.patch.object(S, 'column_slot', return_value=past):
            self.run_cmd([qa('accept', 85)], if_missing=True)
            d = ColumnDraft.objects.latest('id')
            self.assertEqual(d.status, ColumnDraft.STATUS_PUBLISHED)
            out2, _ = self.run_cmd([], if_missing=True)
        self.assertIn('이미 있습니다', out2)


class SeriesPrepareTests(TestCase):
    def test_prepare_picks_series_by_slot_and_alerts_on_hold(self):
        from community.series_catalog import SERIES
        Category.objects.get_or_create(name=SERIES['django']['category_name'])
        sunday = kst(2026, 10, 18, 13, 0)
        calls = []

        def fake_produce(key, no, *, dry=False, out=print, publish_at=None, target=None):
            calls.append((key, no, publish_at))
            d = ColumnDraft.objects.create(topic='coding', series_key=key, episode_number=no, publish_at=publish_at,
                                           status=ColumnDraft.STATUS_HOLD, subject=f'{no}편', qa_report={'score': 70})
            return {'status': 'hold', 'score': 70, 'verdict': 'minor', 'draft': d}

        with mock.patch.object(S, 'series_slot', return_value=('django', kst(2026, 10, 19, 10, 0))), \
             mock.patch('office.series_pipeline.produce_episode', side_effect=fake_produce), \
             mock.patch.object(S, 'alert_not_ready') as alert, \
             mock.patch('common.management.commands.auto_write_series.call_command'):
            call_command('auto_write_series', series='auto', prepare=True, stdout=StringIO())
            call_command('auto_write_series', series='auto', prepare=True, stdout=StringIO())   # 보류 중 → 건너뜀
            out = StringIO()
            call_command('auto_write_series', series='agent', prepare=True, stdout=out)         # 이번 몫은 django
        self.assertEqual(calls, [('django', 0, kst(2026, 10, 19, 10, 0))])
        alert.assert_called_once()
        self.assertIn('django 시리즈 차례', out.getvalue())
        del sunday
