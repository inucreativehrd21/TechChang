from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth.models import User
from django.http import QueryDict
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from office.models import Meeting, Decision, ColumnDraft, Task, WorkLog, AuditEvent
from office.decision_review import decorate, save_review


class MeetingDecisionReviewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('meeting-owner', '', 'x')
        self.client.force_login(self.owner)
        self.meeting = Meeting.objects.create(week_start=timezone.localdate(), summary='심화와 실용을 독립 편성해요.')
        self.decisions = [Decision.objects.create(meeting=self.meeting, kind=kind, topic=topic,
            column_track=track, question=question, options=[
                {'key': 'a', 'title': question+' 첫째', 'detail': '첫째 선택지의 비교 근거예요.'},
                {'key': 'b', 'title': question+' 둘째', 'detail': '둘째 선택지의 한계도 살펴봐요.'}])
            for kind, topic, track, question in [('column', 'data', 'research', '심화 주제'),
                ('column', 'data', 'practical', '실용 주제'), ('ops', '', '', '운영 점검')]]
        self.url = reverse('office:meeting_decisions_save', args=[self.meeting.pk])

    def payload(self, selections=None, notes=None):
        value = QueryDict(mutable=True)
        for d in self.meeting.decisions.all():
            decorate(d)
            value.appendlist('decision_ids', str(d.pk))
            value[f'version_{d.pk}'] = d.review_token
            value[f'choice_{d.pk}'] = (selections or {}).get(d.pk, d.chosen_key)
            value[f'note_{d.pk}'] = (notes or {}).get(d.pk, d.note)
        return value

    def post(self, value):
        # django.test.Client의 QueryDict 인코딩은 다중 값을 리스트로 넘겨야 보존해요.
        with patch('office.views._spawn') as spawn:
            response = self.client.post(self.url, dict(value.lists()), HTTP_USER_AGENT='Mozilla/5.0')
        return response, spawn

    def test_page_has_one_batch_form_and_distinct_radio_names(self):
        response = self.client.get(reverse('office:admin'), HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(response, 'data-meeting-review', count=1)
        for d in self.decisions:
            self.assertContains(response, f'name="choice_{d.pk}"', count=2)
        self.assertNotContains(response, 'name="key"')
        self.assertContains(response, '선택·의견 한 번에 저장')

    def test_partial_selection_and_pending_note_saved_together_and_survive_reload(self):
        a, b, c = self.decisions
        response, spawn = self.post(self.payload({a.pk: 'a', b.pk: 'b'}, {a.pk: '원리를 비교해 주세요.', c.pk: '담당 범위를 먼저 확인해요.'}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith('#decisions'))
        for d in self.decisions:
            d.refresh_from_db()
        self.assertEqual((a.chosen_key, b.chosen_key, c.chosen_key), ('a', 'b', ''))
        self.assertEqual(c.note, '담당 범위를 먼저 확인해요.')
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.status, 'open')
        spawn.assert_not_called()
        page = self.client.get(reverse('office:admin'), HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(page, '원리를 비교해 주세요.')
        self.assertContains(page, '담당 범위를 먼저 확인해요.')
        self.assertContains(page, f'name="choice_{b.pk}" value="b" checked')

    def test_all_choices_close_meeting_and_duplicate_post_does_not_duplicate_work(self):
        value = self.payload({d.pk: 'a' for d in self.decisions}, {self.decisions[2].pk: '로컬 확인 후 처리해요.'})
        first, spawn = self.post(value)
        self.assertEqual(first.status_code, 302)
        spawn.assert_called_once()
        self.assertEqual(Task.objects.count(), 1)
        self.assertIn('로컬 확인 후 처리해요.', Task.objects.get().body)
        second, again = self.post(value)
        self.assertEqual(second.status_code, 302)
        again.assert_not_called()
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(WorkLog.objects.filter(action='decision').count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action='meeting_decision_saved').count(), 3)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.status, 'closed')

    def test_invalid_choice_rolls_back_all_and_preserves_input_in_error_page(self):
        a, b, _ = self.decisions
        response, spawn = self.post(self.payload({a.pk: 'b', b.pk: 'not-an-option'}, {a.pk: '유지해야 하는 검토 의견'}))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Decision.objects.exclude(chosen_key='').exists())
        self.assertFalse(AuditEvent.objects.exists())
        self.assertContains(response, '유지해야 하는 검토 의견', status_code=409)
        self.assertContains(response, f'name="choice_{a.pk}" value="b" checked', status_code=409)
        spawn.assert_not_called()

    def test_overlong_note_is_not_silently_truncated_or_partially_saved(self):
        a = self.decisions[0]
        response, _ = self.post(self.payload({a.pk: 'a'}, {a.pk: '긴'*301}))
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, '긴'*301, status_code=409)
        self.assertFalse(Decision.objects.exclude(chosen_key='').exists())

    def test_stale_modified_choice_is_rejected_but_other_input_is_preserved(self):
        a, b, _ = self.decisions
        value = self.payload({a.pk: 'a', b.pk: 'b'}, {b.pk: '비교 기준 유지'})
        Decision.objects.filter(pk=a.pk).update(chosen_key='b', chosen_by=self.owner, chosen_at=timezone.now())
        response, _ = self.post(value)
        self.assertEqual(response.status_code, 409)
        b.refresh_from_db()
        self.assertEqual(b.chosen_key, '')
        self.assertContains(response, '비교 기준 유지', status_code=409)
        self.assertContains(response, '다른 화면에서 결정이 바뀌었어요', status_code=409)

    def test_untouched_stale_row_does_not_overwrite_another_tabs_choice(self):
        a, b, _ = self.decisions
        value = self.payload({b.pk: 'b'})
        Decision.objects.filter(pk=a.pk).update(chosen_key='a', note='다른 화면의 의견', chosen_at=timezone.now())
        response, _ = self.post(value)
        self.assertEqual(response.status_code, 302)
        a.refresh_from_db()
        self.assertEqual((a.chosen_key, a.note), ('a', '다른 화면의 의견'))

    def test_already_saved_unused_choice_can_be_reconsidered(self):
        a = self.decisions[0]
        self.post(self.payload({a.pk: 'a'}))
        response, _ = self.post(self.payload({a.pk: 'b'}, {a.pk: '대안의 한계를 더 살펴봐요.'}))
        self.assertEqual(response.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.chosen_key, 'b')

    def test_used_or_in_production_choice_is_locked_including_legacy_endpoint(self):
        a = self.decisions[0]
        self.post(self.payload({a.pk: 'a'}))
        ColumnDraft.objects.create(topic='data', decision=a, status='hold')
        response, _ = self.post(self.payload({a.pk: 'b'}))
        self.assertEqual(response.status_code, 409)
        with patch('office.views._spawn'):
            old = self.client.post(reverse('office:decision_choose', args=[a.pk]), {'key': 'b'})
        self.assertEqual(old.status_code, 409)
        a.refresh_from_db()
        self.assertEqual(a.chosen_key, 'a')

    def test_changed_option_definition_is_rejected(self):
        a = self.decisions[0]
        value = self.payload({a.pk: 'a'})
        a.options[0]['detail'] = '선택 근거가 바뀌었어요.'
        a.save(update_fields=['options'])
        self.assertEqual(self.post(value)[0].status_code, 409)

    def test_tampered_token_and_duplicate_or_cross_meeting_ids_rejected(self):
        a = self.decisions[0]
        for kind in ('token', 'duplicate', 'other'):
            value = self.payload({a.pk: 'a'})
            if kind == 'token':
                value[f'version_{a.pk}'] = 'tampered'
            elif kind == 'duplicate':
                value.appendlist('decision_ids', str(a.pk))
            else:
                value.appendlist('decision_ids', '999999')
            self.assertEqual(self.post(value)[0].status_code, 409)
        self.assertFalse(Decision.objects.exclude(chosen_key='').exists())

    def test_backend_error_rolls_back_choices_and_audit_together(self):
        value = self.payload({d.pk: 'a' for d in self.decisions})
        with patch('office.decision_review.Task.objects.create', side_effect=RuntimeError('store failed')):
            with self.assertRaises(RuntimeError):
                save_review(self.meeting.pk, value, self.owner)
        self.assertFalse(Decision.objects.exclude(chosen_key='').exists())
        self.assertFalse(AuditEvent.objects.exists())
        self.assertFalse(WorkLog.objects.exists())

    def test_non_operator_and_csrf_cannot_save(self):
        staff = User.objects.create_user('not-owner', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.post(self.payload({self.decisions[0].pk: 'a'}))[0].status_code, 302)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.owner)
        self.assertEqual(secure.post(self.url, dict(self.payload().lists())).status_code, 403)
        self.assertFalse(Decision.objects.exclude(chosen_key='').exists())

    def test_operator_note_reaches_actual_draft_prompt_without_mutating_options(self):
        from office import pipeline as P
        a = self.decisions[0]
        a.chosen_key, a.note = 'a', '분포의 꼬리 위험과 반례를 비교해 주세요.'
        original = deepcopy(a.options)
        with patch('office.pipeline.ask_agent', return_value='TITLE: 제목\n---\n본문') as writer:
            P.step_draft('data', a, {'angle': '원리 탐구'}, [])
        self.assertIn(a.note, writer.call_args.args[1])
        self.assertEqual(a.options, original)
        self.assertNotIn(a.note, a.chosen['detail'])

    def test_saved_change_clears_the_previous_public_summary(self):
        self.meeting.public_summary = '이전 선택을 설명하는 공개 소개'
        self.meeting.save(update_fields=['public_summary'])
        response, _ = self.post(self.payload({self.decisions[0].pk: 'a'}))
        self.assertEqual(response.status_code, 302)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.public_summary, '')
