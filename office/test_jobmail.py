"""운영자 메일 — 구독 한도 중단(해제 시각·다시 실행 버튼), 준비 미달(재심 요청 버튼), 서명 링크 예약, 10분 실행기."""
import os
from datetime import datetime, timedelta
from unittest import mock

from django.core import mail, signing
from django.test import TestCase, override_settings
from django.utils import timezone

from office import jobmail as J
from office.models import CliLimit, ColumnDraft, JobRequest

LIMIT = "exit=1 subtype=success You've hit your session limit · resets 2:50am (Asia/Seoul)"
ENV = {'DJANGO_ADMIN_EMAIL': 'ops@example.com'}


def kst(*a):
    return timezone.make_aware(datetime(*a))


class ResetParseTests(TestCase):
    def test_reset_time_is_read_from_the_cli_message(self):
        self.assertEqual(J.reset_at(LIMIT, kst(2026, 10, 14, 23, 31)), kst(2026, 10, 15, 2, 50))
        self.assertEqual(J.reset_at("hit your usage limit · resets 1pm", kst(2026, 10, 15, 9, 0)), kst(2026, 10, 15, 13, 0))
        self.assertEqual(J.reset_at('session limit reached', kst(2026, 10, 15, 9, 0)), kst(2026, 10, 15, 9, 30))
        self.assertIsNone(J.reset_at('토큰이 만료되었습니다'))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
@mock.patch.dict(os.environ, ENV)
class MailTests(TestCase):
    def test_limit_mail_has_reset_time_and_rerun_button(self):
        self.assertTrue(J.limit_mail(['office_publish', '--topic', 'data', '--prepare'], LIMIT, 'claude-sonnet-5-5'))
        m = mail.outbox[0]
        self.assertEqual(m.to, ['ops@example.com'])
        self.assertIn('구독 한도로 작업 중단', m.subject)
        self.assertIn('한도 해제 예정', m.body)
        self.assertIn('/lab/job/', m.body)
        self.assertIn('한도 풀리면 다시 실행', m.alternatives[0][0])
        self.assertEqual(CliLimit.objects.count(), 1)

    def test_unlisted_command_gets_no_button(self):
        J.limit_mail(['flush', '--noinput'], LIMIT)
        self.assertNotIn('/lab/job/', mail.outbox[0].body)

    def test_not_ready_mail_offers_review_or_retry(self):
        held = ColumnDraft.objects.create(topic='data', subject='보류 원고', status=ColumnDraft.STATUS_HOLD,
                                          publish_at=timezone.now() + timedelta(hours=10),
                                          qa_report={'score': 68, 'verdict': 'minor',
                                                     'must_fix': [{'where': '서두', 'problem': '논지 끊김', 'fix': '잇기'}]})
        J.not_ready_mail(held, '데이터분석 칼럼', '심사를 통과하지 못했습니다(68점)')
        body = mail.outbox[0].body
        self.assertIn('지적대로 고쳐 재심 요청', body)
        self.assertIn('논지 끊김', body)
        token = body.split('/lab/job/')[1].split('/')[0]
        data = J.read_token(token)
        self.assertEqual(data['a'][:3], ['office_revise', '--draft', str(held.pk)])
        failed = ColumnDraft.objects.create(topic='data', status=ColumnDraft.STATUS_FAILED, publish_at=held.publish_at)
        J.not_ready_mail(failed, '데이터분석 칼럼', '제작 중 오류로 멈췄습니다',
                         rerun_args=['office_publish', '--topic', 'data', '--prepare'])
        self.assertIn('다시 준비', mail.outbox[1].body)

    def test_claude_alert_uses_the_button_mail_when_fallback_is_off(self):
        from common.services import claude as C
        C._fallback_alerted = False
        try:
            with mock.patch('office.jobmail.limit_mail', return_value=True) as lm:
                C._alert_fallback({'model': 'm', 'fallback': LIMIT}, fallback_enabled=False)
            lm.assert_called_once()
            self.assertEqual(lm.call_args.args[1], LIMIT)
        finally:
            C._fallback_alerted = False


class TokenAndPageTests(TestCase):
    def test_tokens_only_carry_allowed_commands(self):
        ok = J.make_token('rerun', ['office_publish', '--topic', 'hrd', '--prepare'], '다시 실행')
        self.assertEqual(J.read_token(ok)['a'][0], 'office_publish')
        evil = signing.dumps({'k': 'rerun', 'a': ['flush', '--noinput'], 'l': 'x'}, salt=J.SALT, compress=True)
        with self.assertRaises(signing.BadSignature):
            J.read_token(evil)
        with self.assertRaises(signing.BadSignature):
            J.read_token(ok[:-3] + 'abc')

    def test_get_shows_confirmation_and_post_enqueues_once(self):
        run = timezone.now() + timedelta(hours=3)
        token = J.make_token('rerun', ['office_publish', '--topic', 'hrd', '--prepare'], '다시 실행: hrd', run_after=run)
        url = f'/lab/job/{token}/'
        r = self.client.get(url, HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(r, '다시 실행 예약')
        self.assertEqual(JobRequest.objects.count(), 0)            # 링크를 여는 것만으로는 예약되지 않는다
        self.client.post(url, HTTP_USER_AGENT='Mozilla/5.0')
        r = self.client.post(url, HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(r, '이미 같은 작업이 예약')
        job = JobRequest.objects.get()
        self.assertGreaterEqual(job.run_after, run)
        self.assertEqual(self.client.get('/lab/job/garbage/', HTTP_USER_AGENT='Mozilla/5.0').status_code, 400)

    def test_request_during_limit_waits_for_reset(self):
        CliLimit.objects.create(reset_at=timezone.now() + timedelta(hours=2))
        token = J.make_token('rerun', ['make_newsletter'], '다시 실행')
        self.client.post(f'/lab/job/{token}/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertGreaterEqual(JobRequest.objects.get().run_after, timezone.now() + timedelta(hours=2))


class RunnerTests(TestCase):
    def job(self, **kw):
        return JobRequest.objects.create(kind=kw.pop('kind', 'rerun'), args=kw.pop('args', ['make_newsletter']),
                                         run_after=kw.pop('run_after', timezone.now() - timedelta(minutes=1)), **kw)

    def test_due_jobs_start_once(self):
        j = self.job()
        later = self.job(args=['hold_meeting'], run_after=timezone.now() + timedelta(hours=1))
        with mock.patch('office.jobs.spawn') as sp:
            J.run_due()
            J.run_due()
        sp.assert_called_once()
        self.assertEqual(sp.call_args.args[0], ['make_newsletter'])
        j.refresh_from_db(); later.refresh_from_db()
        self.assertEqual((j.status, later.status), (JobRequest.ST_STARTED, JobRequest.ST_PENDING))

    def test_limit_defers_and_handled_draft_is_skipped(self):
        CliLimit.objects.create(reset_at=timezone.now() + timedelta(hours=1))
        j = self.job()
        with mock.patch('office.jobs.spawn') as sp:
            J.run_due()
        sp.assert_not_called()
        j.refresh_from_db()
        self.assertGreater(j.run_after, timezone.now() + timedelta(minutes=60))
        CliLimit.objects.all().delete()
        done = ColumnDraft.objects.create(topic='hrd', status=ColumnDraft.STATUS_READY)
        r = self.job(kind='revise', args=['office_revise', '--draft', str(done.pk)], draft=done)
        with mock.patch('office.jobs.spawn') as sp:
            J.run_due(now=timezone.now() + timedelta(hours=2))
        r.refresh_from_db()
        self.assertEqual(r.status, JobRequest.ST_SKIPPED)        # 이미 공개 대기 — 재심할 필요 없음


@mock.patch.dict(os.environ, {**ENV, 'CLAUDE_BACKEND': 'cli', 'AI_FALLBACK_BACKEND': 'codex_cli'})
class SubscriptionRunnerTests(TestCase):
    def state(self, provider, minutes):
        from office.models import AiProviderState
        return AiProviderState.objects.create(provider=provider, failure_kind='limit',
                                              retry_at=timezone.now() + timedelta(minutes=minutes))

    def test_claude_limit_does_not_delay_a_job_when_codex_is_available(self):
        self.state('claude', 120)
        CliLimit.objects.create(reset_at=timezone.now() + timedelta(hours=4))
        job = JobRequest.objects.create(kind='rerun', args=['make_newsletter'], run_after=timezone.now())
        with mock.patch('office.jobs.spawn') as spawn:
            J.run_due(out=lambda _: None)
        spawn.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, JobRequest.ST_STARTED)

    def test_both_limits_wait_for_earliest_provider_not_latest(self):
        self.state('claude', 120)
        codex = self.state('codex', 20)
        self.assertEqual(J.limited_until(), codex.retry_at)
        job = JobRequest.objects.create(kind='rerun', args=['make_newsletter'], run_after=timezone.now())
        with mock.patch('office.jobs.spawn') as spawn:
            J.run_due(out=lambda _: None)
        spawn.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.run_after, codex.retry_at + J.AFTER_RESET)

    def test_success_mail_does_not_say_job_stopped_or_api_was_used(self):
        self.state('claude', 120)
        J.subscription_mail(['make_newsletter'], {'backend': 'codex_cli', 'model': 'gpt-6.1-sol',
                                                 'fallback': 'usage limit reached'})
        self.assertIn('Codex 구독 전환', mail.outbox[0].subject)
        self.assertNotIn('작업 중단', mail.outbox[0].subject)
        self.assertNotIn('과금 발생', mail.outbox[0].body)

    def test_failure_mail_can_follow_success_mail(self):
        from common.services import claude
        claude._subscription_alerted.clear()
        self.addCleanup(claude._subscription_alerted.clear)
        with mock.patch('office.jobmail.subscription_mail', return_value=True) as send:
            claude._alert_fallback({'backend': 'codex_cli'}, fallback_enabled=False, subscription=True)
            claude._alert_fallback({'backend': ''}, fallback_enabled=False, subscription=True)
        self.assertEqual(send.call_count, 2)
