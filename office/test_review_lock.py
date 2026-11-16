"""원고 검수 화면 — 재작성 요청 뒤 중복 전송 방지(2026-11-16)와 감사 기록 타임라인.

- 재작성은 작업 대기열에 들어가 cron 이 나중에 집으므로, 그동안 원고 상태는 '검수 대기' 그대로다. 화면과 서버가 같은 판정으로
  수정 지시·승인·반려를 막는지, 막지 않아야 할 때(작업이 끝났을 때)는 다시 열리는지.
- 감사 기록 화면이 원고 전문 없이 요약만 보이는지, 운영자만 열 수 있는지, 해시 체인이 끊기면 알리는지.
"""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.utils import timezone

from office import audit, audit_timeline, draft_state
from office.models import AuditEvent, AuditHead, ColumnDraft, JobRequest

UA = {'HTTP_USER_AGENT': 'Mozilla/5.0'}
OTP_OK = mock.patch('common.views._admin_otp_session_ok', return_value=True)


def make_draft(**kw):
    data = dict(topic='hrd', subject='검수할 원고', content='본문입니다.', status=ColumnDraft.STATUS_HOLD,
                qa_report={'score': 78, 'verdict': 'major'})
    data.update(kw)
    return ColumnDraft.objects.create(**data)


def make_job(draft, status='pending', args=None):
    return JobRequest.objects.create(kind='rerun', args=args or ['office_revise', '--draft', str(draft.pk)], label='office_revise',
                                     draft=draft, run_after=timezone.now(), status=status, requested_via='admin',
                                     active_key=f'job-{draft.pk}-{status}')


class DraftStateTests(TestCase):
    def test_state_follows_the_queue_not_only_the_draft_status(self):
        d = make_draft()
        self.assertIsNone(draft_state.state_of(d, None))
        self.assertEqual(draft_state.state_of(d, make_job(d, 'pending')), draft_state.QUEUED)
        self.assertEqual(draft_state.state_of(d, make_job(d, 'started')), draft_state.RUNNING)
        self.assertEqual(draft_state.state_of(d, make_job(d, 'quarantined')), draft_state.ATTENTION)
        d.status = ColumnDraft.STATUS_REVISING
        self.assertEqual(draft_state.state_of(d, None), draft_state.RUNNING)       # 작업 기록 없이 revising 이어도 진행 중

    def test_finished_jobs_do_not_lock_and_guard_messages_name_the_action(self):
        d = make_draft()
        for status in ('completed', 'failed', 'cancelled', 'skipped', 'interrupted'):
            make_job(d, status)
        self.assertIsNone(draft_state.guard(d, '반려'))
        make_job(d, 'pending')
        self.assertIn('반려', draft_state.guard(d, '반려'))
        self.assertIn('대기 중', draft_state.guard(d, '반려'))

    def test_active_jobs_maps_each_draft_to_its_latest_job(self):
        a, b, c = make_draft(), make_draft(), make_draft()
        make_job(a, 'pending')
        j2 = make_job(b, 'started')
        make_job(c, 'completed')
        found = draft_state.active_jobs([a.pk, b.pk, c.pk])
        self.assertEqual(set(found), {a.pk, b.pk})
        self.assertEqual(found[b.pk].pk, j2.pk)


class ReviewGuardTests(TestCase):
    def setUp(self):
        from unittest import mock as _otp_mock   # 관리 화면은 모두 OTP 경계 — 여기서는 인증된 운영자로 본다
        _otp = _otp_mock.patch('common.views._admin_otp_session_ok', return_value=True)
        _otp.start()
        self.addCleanup(_otp.stop)
        self.owner = User.objects.create_superuser('admin', '', 'x')
        self.client.force_login(self.owner)
        self.draft = make_draft()

    def post(self, name, data=None):
        return self.client.post(f'/lab/admin/draft/{self.draft.pk}/{name}/', data or {}, **UA)

    def flashes(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    def revise_jobs(self):
        return JobRequest.objects.filter(draft=self.draft, status__in=('pending', 'started')).count()

    def test_revise_twice_creates_one_job_one_audit_event_and_keeps_the_first_note(self):
        self.post('revise', {'note': '첫 지시'})
        self.post('revise', {'note': '두 번째 지시(연타)'})
        self.post('revise', {'note': '세 번째 지시(연타)'})
        self.draft.refresh_from_db()
        self.assertEqual(self.revise_jobs(), 1)
        self.assertEqual(AuditEvent.objects.filter(draft_id=self.draft.pk, action='revision_requested').count(), 1)
        self.assertEqual(self.draft.admin_note, '첫 지시')

    def test_second_revise_tells_the_operator_it_was_already_requested(self):
        self.post('revise', {'note': '첫 지시'})
        response = self.post('revise', {'note': '또 지시'})
        self.assertTrue(any('이미 재작성을 요청했어요' in text for text in self.flashes(response)))

    def test_revise_opens_again_after_the_job_finishes(self):
        self.post('revise', {'note': '첫 지시'})
        JobRequest.objects.filter(draft=self.draft).update(status='completed', active_key=None)
        self.post('revise', {'note': '다음 지시'})
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.admin_note, '다음 지시')
        self.assertEqual(AuditEvent.objects.filter(draft_id=self.draft.pk, action='revision_requested').count(), 2)

    def test_empty_note_is_rejected_without_a_job(self):
        self.post('revise', {'note': '   '})
        self.assertEqual(self.revise_jobs(), 0)
        self.assertFalse(AuditEvent.objects.filter(action='revision_requested').exists())

    def test_publish_and_reject_are_refused_while_a_rewrite_is_queued(self):
        make_job(self.draft, 'pending')
        for name, data in (('publish', {'version': 'x'}), ('reject', {})):
            response = self.post(name, data)
            self.assertTrue(any('재작성 요청이 대기 중이에요' in text for text in self.flashes(response)), name)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, ColumnDraft.STATUS_HOLD)      # 반려로 바뀌지도, 공개되지도 않았다
        self.assertFalse(AuditEvent.objects.filter(action__in=('rejected', 'approved')).exists())

    def test_reject_is_refused_while_a_job_runs_or_needs_confirmation(self):
        for status in ('started', 'quarantined'):
            job = make_job(self.draft, status)
            self.post('reject')
            self.draft.refresh_from_db()
            self.assertEqual(self.draft.status, ColumnDraft.STATUS_HOLD, status)
            job.delete()

    def test_ready_draft_cannot_be_published_now_while_a_job_is_active(self):
        ready = make_draft(status=ColumnDraft.STATUS_READY, publish_at=timezone.now() + timedelta(hours=3))
        make_job(ready, 'pending')
        self.client.post(f'/lab/admin/draft/{ready.pk}/publish/', {'version': 'x', 'now': '1'}, **UA)
        ready.refresh_from_db()
        self.assertEqual(ready.status, ColumnDraft.STATUS_READY)

    def test_reject_without_a_job_works_and_is_audited(self):
        self.post('reject')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, ColumnDraft.STATUS_REJECTED)
        event = AuditEvent.objects.get(action='rejected', draft_id=self.draft.pk)
        self.assertEqual(event.actor_id, self.owner.pk)
        self.assertTrue(audit.verify())


class ReviewPageTests(TestCase):
    def setUp(self):
        from unittest import mock as _otp_mock   # 관리 화면은 모두 OTP 경계 — 여기서는 인증된 운영자로 본다
        _otp = _otp_mock.patch('common.views._admin_otp_session_ok', return_value=True)
        _otp.start()
        self.addCleanup(_otp.stop)
        self.owner = User.objects.create_superuser('admin', '', 'x')
        self.client.force_login(self.owner)

    def page(self, ua=UA):
        return self.client.get('/lab/admin/', **ua)

    def test_idle_draft_shows_revise_decide_and_reject_with_a_lock_hook(self):
        make_draft()
        response = self.page()
        self.assertContains(response, 'class="dr-revise"', count=1)
        self.assertContains(response, 'class="dr-decide"', count=1)
        self.assertContains(response, 'class="dr-reject"', count=1)
        self.assertContains(response, 'data-lock>', count=3)               # 스크립트 속 '[data-lock]' 선택자와 구분한다
        self.assertNotContains(response, '<footer class="dr-status')          # 작업 중 상태 패널은 없다(숨은 전송 중 패널과 구분)

    def test_queued_rewrite_hides_every_action_and_shows_what_was_sent(self):
        d = make_draft(admin_note='사례를 국내 중심으로')
        make_job(d, 'pending')
        for ua in (UA, {'HTTP_USER_AGENT': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'}):
            response = self.page(ua)
            self.assertContains(response, '재작성 요청을 보냈어요')
            self.assertContains(response, '사례를 국내 중심으로')                       # 보낸 수정 지시가 보인다
            self.assertContains(response, '요청 취소')
            for hidden in ('class="dr-revise"', 'class="dr-decide"', 'class="dr-reject"'):
                self.assertNotContains(response, hidden, msg_prefix=hidden)
            self.assertContains(response, f'data-progress="{d.pk}"')
            self.assertNotContains(response, ' data-progress-live>')                  # 대기 중엔 옛 로그를 진행처럼 보이지 않는다

    def test_running_rewrite_is_live_and_has_no_actions(self):
        d = make_draft(status=ColumnDraft.STATUS_REVISING)
        make_job(d, 'started')
        response = self.page()
        self.assertContains(response, '연구팀이 재작성 중이에요')
        self.assertContains(response, ' data-progress-live>')
        self.assertNotContains(response, 'class="dr-decide"')

    def test_stuck_job_shows_confirmation_not_actions(self):
        d = make_draft()
        make_job(d, 'quarantined')
        response = self.page()
        self.assertContains(response, '작업 종료 확인이 필요해요')
        self.assertContains(response, '종료 확인')
        self.assertNotContains(response, 'data-progress=')                            # 자동 갱신 대상이 아니다(새로고침 루프 방지)
        self.assertNotContains(response, 'class="dr-revise"')

    def test_actions_return_once_the_job_is_done(self):
        d = make_draft()
        make_job(d, 'pending')
        self.assertNotContains(self.page(), 'class="dr-revise"')
        JobRequest.objects.filter(draft=d).update(status='completed', active_key=None)
        self.assertContains(self.page(), 'class="dr-revise"', count=1)

    def test_status_strip_does_not_count_locked_drafts_as_waiting_for_review(self):
        make_draft()
        queued = make_draft()
        stuck = make_draft()
        make_job(queued, 'pending')
        make_job(stuck, 'quarantined')
        item = next(s for s in self.page().context['status'] if s['label'] == '검수 대기 원고')
        self.assertEqual(item['n'], 1)
        self.assertEqual(item['note'], '재작성 중 1 · 종료 확인 1')

    def test_jobs_are_listed_with_readable_names_active_first(self):
        d = make_draft(subject='작업 이름 점검 원고')
        make_job(d, 'pending')
        make_job(d, 'completed', args=['office_revise', '--draft', str(d.pk), '--note', '지난 지시'])
        response = self.page()
        self.assertContains(response, '재작성 · 작업 이름 점검 원고')
        self.assertEqual(len(response.context['jobs_active']), 1)
        self.assertEqual(len(response.context['jobs_past']), 1)
        self.assertNotContains(response, '<b title="office_revise">office_revise')      # 명령어가 제목 자리에 나오지 않는다

    def test_long_review_notes_are_folded(self):
        make_draft(check_report={'notes': '근거 보강이 필요해요. ' * 30})
        self.assertContains(self.page(), 'class="dr-more"')

    def test_activity_lists_queued_rewrites_so_the_page_can_refresh_itself(self):
        queued = make_draft()
        make_job(queued, 'pending')
        revising = make_draft(status=ColumnDraft.STATUS_REVISING)
        quiet = make_draft()
        make_job(quiet, 'completed')
        with OTP_OK:
            data = json.loads(self.client.get('/lab/admin/activity.json', **UA).content)
        ids = {row['id'] for row in data['running'] if isinstance(row['id'], int)}
        self.assertEqual(ids, {queued.pk, revising.pk})


class AuditTimelineTests(TestCase):
    def setUp(self):
        from unittest import mock as _otp_mock   # 관리 화면은 모두 OTP 경계 — 여기서는 인증된 운영자로 본다
        _otp = _otp_mock.patch('common.views._admin_otp_session_ok', return_value=True)
        _otp.start()
        self.addCleanup(_otp.stop)
        self.owner = User.objects.create_superuser('admin', '', 'x')
        self.client.force_login(self.owner)
        self.draft = make_draft(subject='감사 대상 원고')

    def url(self, pk=None):
        return f'/lab/admin/draft/{pk or self.draft.pk}/audit/'

    def get(self, **kw):
        with OTP_OK:
            return self.client.get(self.url(**kw), **UA)

    def test_timeline_is_newest_first_and_translates_each_event(self):
        pk, who = self.draft.pk, self.owner.pk
        audit.append('revision_requested', actor_id=who, draft_id=pk, payload={'note': '분량을 줄여 주세요', 'before': {'review': {'score': 78}}})
        audit.append('job_started', draft_id=pk, payload={'job': 41})
        audit.append('job_finished', draft_id=pk, payload={'job': 41, 'status': 'failed', 'exit_code': 1, 'business_result': 'hold'})
        audit.append('approved', actor_id=who, draft_id=pk, payload={'reason': '', 'mode': 'normal', 'snapshot': {'review': {'score': 82}}})
        audit.append('published', actor_id=who, draft_id=pk, payload={'approval': 4, 'question_id': 77})
        response = self.get()
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        for text in ('재작성을 요청했어요', '분량을 줄여 주세요', '재작성을 시작했어요', '작업이 실패했어요', '종료 코드',
                     '검수를 승인했어요', '칼럼으로 공개했어요', '요청 당시 심사', '78점', '82점', '공개된 칼럼 보기'):
            self.assertIn(text, html, text)
        self.assertLess(html.index('칼럼으로 공개했어요'), html.index('재작성을 요청했어요'))       # 최신이 위
        self.assertIn('/77/', html)                                                   # 공개된 칼럼으로 가는 링크
        self.assertContains(response, '기록이 바뀐 흔적이 없어요')
        self.assertEqual(response.context['total'], 5)
        self.assertEqual(response.context['counts']['asked'], 1)

    def test_full_draft_text_inside_payloads_is_never_rendered(self):
        secret = '절대 화면에 나오면 안 되는 원고 전문입니다'
        audit.append('approved', actor_id=self.owner.pk, draft_id=self.draft.pk,
                     payload={'reason': '', 'mode': 'normal', 'snapshot': {'content': secret, 'review': {'score': 82}}})
        audit.append('revision_requested', actor_id=self.owner.pk, draft_id=self.draft.pk,
                     payload={'note': '짧은 지시', 'before': {'content': secret, 'review': {'score': 70}}})
        self.assertNotContains(self.get(), secret)

    def test_exception_approval_revocation_reject_and_unknown_events(self):
        pk, who = self.draft.pk, self.owner.pk
        audit.append('exception_approved', actor_id=who, draft_id=pk, payload={'reason': '문체 예외', 'mode': 'exception', 'snapshot': {}})
        audit.append('approval_revoked', actor_id=who, draft_id=pk, payload={'approval': 1, 'reason': '수정 지시'})
        audit.append('rejected', actor_id=who, draft_id=pk, payload={})
        audit.append('something_new', draft_id=pk, payload={})
        response = self.get()
        for text in ('예외로 승인했어요', '문체 예외', '승인을 취소했어요', '원고를 반려했어요', 'something_new', '자동 실행'):
            self.assertContains(response, text)
        self.assertEqual(response.context['counts']['exception'], 1)

    def test_other_drafts_events_do_not_leak_in(self):
        other = make_draft(subject='다른 원고')
        audit.append('rejected', actor_id=self.owner.pk, draft_id=other.pk, payload={})
        audit.append('revision_requested', actor_id=self.owner.pk, draft_id=self.draft.pk, payload={'note': '내 원고 지시'})
        response = self.get()
        self.assertEqual(response.context['total'], 1)
        self.assertNotContains(response, '원고를 반려했어요')

    def test_empty_history_and_deleted_draft(self):
        self.assertContains(self.get(), '아직 없어요')
        gone = self.draft.pk
        audit.append('rejected', actor_id=self.owner.pk, draft_id=gone, payload={})
        self.draft.delete()
        self.assertContains(self.get(pk=gone), '삭제됐거나 제목이 없는 원고')
        with OTP_OK:
            self.assertEqual(self.client.get(self.url(pk=999999), **UA).status_code, 404)

    def test_broken_hash_chain_is_reported(self):
        audit.append('revision_requested', actor_id=self.owner.pk, draft_id=self.draft.pk, payload={'note': '정상'})
        head = AuditHead.objects.get(pk=1)
        AuditEvent(sequence=head.sequence + 1, created_at=timezone.now(), action='rejected', actor_id=self.owner.pk,
                   draft_id=self.draft.pk, payload={}, previous_digest=head.digest, digest='0' * 64).save()
        response = self.get()
        self.assertContains(response, '해시가 맞지 않는 기록이 있어요')
        self.assertContains(response, '해시 불일치')

    def test_only_operators_can_open_it(self):
        member = User.objects.create_user('member')
        staff = User.objects.create_user('staff', is_staff=True)
        for user in (None, member, staff):
            self.client.logout()
            if user:
                self.client.force_login(user)
            with OTP_OK:
                response = self.client.get(self.url(), **UA)
            self.assertEqual(response.status_code, 302, user)

    def test_owner_without_otp_is_sent_to_verify(self):
        with mock.patch('common.views._admin_otp_session_ok', return_value=False):
            response = self.client.get(self.url(), **UA)
        self.assertEqual(response.status_code, 302)
        self.assertIn('otp', response.url)

    def test_review_card_links_to_the_readable_page_not_raw_json(self):
        response = self.client.get('/lab/admin/', **UA)
        self.assertContains(response, self.url())
        self.assertNotContains(response, f'<a href="/lab/admin/draft/{self.draft.pk}/audit.json">')


class DescribeTests(TestCase):
    def event(self, action, payload=None, actor=None):
        return SimpleNamespace(action=action, payload=payload or {}, actor_id=actor)

    def test_score_scale_of_old_records_is_converted(self):
        row = audit_timeline.describe(self.event('approved', {'snapshot': {'review': {'score': 8}}}), '운영자')
        self.assertIn(('승인 당시 심사', '80점'), row['facts'])

    def test_tones_follow_meaning(self):
        cases = {'revision_requested': 'ask', 'approved': 'ok', 'published': 'ok', 'exception_approved': 'warn',
                 'approval_revoked': 'warn', 'job_cancelled': 'warn', 'rejected': 'bad', 'job_started': 'sys'}
        for action, tone in cases.items():
            self.assertEqual(audit_timeline.describe(self.event(action), 'x')['tone'], tone, action)
        failed = audit_timeline.describe(self.event('job_finished', {'status': 'failed', 'exit_code': 2}), 'x')
        done = audit_timeline.describe(self.event('job_finished', {'status': 'completed', 'exit_code': 0}), 'x')
        self.assertEqual((failed['tone'], done['tone']), ('bad', 'sys'))
        self.assertNotIn('종료 코드', [k for k, _ in done['facts']])

    def test_malformed_payload_does_not_break_the_page(self):
        row = audit_timeline.describe(SimpleNamespace(action='approved', payload=None, actor_id=None), '자동 실행')
        self.assertEqual(row['label'], '승인')
