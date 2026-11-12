from copy import deepcopy
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from community.models import Question, Category
from office import editorial as E, genres, schedule as S, pipeline as P
from office.models import ColumnDraft, Meeting, Decision, AuditEvent
from office.management.commands.hold_meeting import validate_column_agenda, mark_gsc_targets


def track_report(track, quote='이 원고의 근거와 성립 조건을 직접 비교해 설명해요.'):
    return {'column_track': track, 'track_review': {'track': track, 'items': [
        {'id': key, 'met': True, 'quote': quote, 'reason': label}
        for key, label in E.CRITERIA[track].items()]}}


class EditorialContractTests(SimpleTestCase):
    def test_context_is_restored_and_research_genre_is_independent_of_old_switch(self):
        self.assertEqual(E.current_track(), '')
        with E.use_track('research'), patch('office.switches.get', return_value=False):
            self.assertEqual(genres.genre_for('data'), 'research')
            self.assertIn('검색량·트래픽과 독립', E.guidance())
            self.assertEqual(P.search_target_rule({'gsc_target': '대출 금리'}), '')
            with E.use_track('practical'):
                self.assertIn('실행 가능한 절차', E.guidance())
            self.assertEqual(E.current_track(), 'research')
        self.assertEqual(E.current_track(), '')

    def test_review_rejects_missing_fabricated_duplicate_and_string_true_evidence(self):
        quote = '이 원고의 근거와 성립 조건을 직접 비교해 설명해요.'
        good = track_report('research', quote)
        self.assertEqual(E.review_failures(good, quote, 'research'), [])
        for kind in ('missing', 'fabricated', 'duplicate', 'string_true', 'heading', 'wrong_track'):
            bad = deepcopy(good)
            if kind == 'missing':
                bad['track_review']['items'].pop()
            elif kind == 'fabricated':
                bad['track_review']['items'][0]['quote'] = '최종 원고에는 없는 근거를 지어냈어요.'
            elif kind == 'duplicate':
                bad['track_review']['items'].append(bad['track_review']['items'][0])
            elif kind == 'string_true':
                bad['track_review']['items'][0]['met'] = 'true'
            elif kind == 'heading':
                bad['track_review']['items'][0]['quote'] = '## 탐구 질문과 근거를 정리하는 제목'
            else:
                bad['track_review']['track'] = 'practical'
            with self.subTest(kind=kind):
                self.assertTrue(E.review_failures(bad, quote, 'research'))

    def test_search_demand_does_not_reorder_or_recommend_research(self):
        from office.trends import rank_options
        research = {'kind': 'column', 'column_track': 'research', 'options': [
            {'key': 'a', 'title': '중요한 연구', 'keywords': ['낮음']},
            {'key': 'b', 'title': '검색량 큰 후보', 'keywords': ['높음']}]}
        practical = {**deepcopy(research), 'column_track': 'practical'}
        with patch('office.trends.measure', return_value=({'낮음': 1, '높음': 9999}, 'volume')):
            rank_options([research, practical])
        self.assertEqual(research['options'][0]['title'], '중요한 연구')
        self.assertFalse(any(o['recommended'] for o in research['options']))
        self.assertEqual(practical['options'][0]['title'], '검색량 큰 후보')
        self.assertTrue(practical['options'][0]['recommended'])
        self.assertEqual(mark_gsc_targets([research], [{'query': '중요한 연구'}]), [])

    def test_agenda_requires_six_distinct_topic_track_pairs_and_no_cloned_titles(self):
        agenda = [{'kind': 'column', 'topic': topic, 'column_track': track, 'options': [
            {'title': f'{topic} {track} 선택 {n}'} for n in range(2)]}
            for topic in ('hrd', 'data', 'coding') for track in E.TRACKS]
        validate_column_agenda(agenda)
        with self.assertRaises(ValueError):
            validate_column_agenda(agenda[:-1])
        agenda[-1]['options'][0]['title'] = agenda[0]['options'][0]['title']
        with self.assertRaises(ValueError):
            validate_column_agenda(agenda)

    def test_scheduled_command_defaults_to_two_independent_runs_even_when_one_fails(self):
        from office.management.commands.office_publish import Command
        command = Command(stdout=StringIO(), stderr=StringIO())
        with patch.object(command, '_handle_one', side_effect=[RuntimeError('첫 유형 실패'), None]) as one:
            with self.assertRaises(CommandError):
                command.handle(topic='data', prepare=True)
        self.assertEqual([c.kwargs['track'] for c in one.call_args_list], ['research', 'practical'])

    def test_pipeline_review_itself_blocks_missing_track_evidence(self):
        from office.test_publish_flow import column
        body = column(30)
        scores = {key: 5 for key in P.RUBRIC}
        with E.use_track('research'), patch('office.arsenal.exemplar_block', return_value=''), patch('office.pipeline.ask_agent_json', return_value={
                'scores': scores, 'fatal': [], 'issues': []}) as ask:
            qa = P.step_review('심화 원고', body, {'verdict': 'pass', 'claims': []}, '')
        self.assertIn('editorial_mismatch', qa['fatal'])
        self.assertIn('track_review', ask.call_args.args[1])
        self.assertEqual(qa['column_track'], 'research')
        self.assertNotEqual(qa['verdict'], 'accept')


class EditorialSlotTests(TestCase):
    def setUp(self):
        self.at = S.column_slot('data')

    def test_each_type_has_one_reservation_and_failed_retry_reuses_it(self):
        first = S.reserve_column(self.at, topic='data', track='research')
        self.assertIsNone(S.reserve_column(self.at, topic='data', track='research'))
        from datetime import timezone as dt_timezone
        self.assertIsNone(S.reserve_column(self.at.astimezone(dt_timezone.utc), topic='data', track='research'))
        second = S.reserve_column(self.at, topic='data', track='practical')
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(S.taken(self.at, topic='data', track='research').pk, first.pk)
        first.status = 'failed'
        first.save(update_fields=['status'])
        self.assertEqual(S.reserve_column(self.at, topic='data', track='research').pk, first.pk)
        self.assertEqual(ColumnDraft.objects.count(), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ColumnDraft.objects.create(topic='data', status='hold', slot_key=first.slot_key)

    def test_legacy_reservation_counts_only_toward_practical_during_transition(self):
        old = ColumnDraft.objects.create(topic='data', status='ready', publish_at=self.at)
        self.assertEqual(S.taken(self.at, topic='data', track='practical'), old)
        self.assertIsNone(S.taken(self.at, topic='data', track='research'))

    def test_briefs_cannot_cross_tracks(self):
        from office.services import take_column_brief
        meeting = Meeting.objects.create(week_start=timezone.localdate())
        practical = Decision.objects.create(meeting=meeting, kind='column', topic='data', column_track='practical',
            question='생활 문제', chosen_key='a', options=[{'key': 'a', 'title': '생활 해결'}])
        self.assertIsNone(take_column_brief('data', track='research'))
        research = Decision.objects.create(meeting=meeting, kind='column', topic='data', column_track='research',
            question='연구 질문', chosen_key='a', options=[{'key': 'a', 'title': '원리 탐구'}])
        self.assertEqual(take_column_brief('data', track='research'), research)
        self.assertEqual(take_column_brief('data', track='practical'), practical)

    def test_track_change_alters_approval_snapshot(self):
        from office.audit import snapshot, fingerprint
        draft = ColumnDraft.objects.create(topic='data', status='hold')
        before = fingerprint(snapshot(draft))
        draft.column_track = 'research'
        self.assertNotEqual(before, fingerprint(snapshot(draft)))
        from office.approval import policy
        with self.assertRaisesMessage(ValueError, '유형에 맞는 편집 심사'):
            policy(draft)


class EditorialPublicTests(TestCase):
    def setUp(self):
        bot = User.objects.create_user(Question.BOT_USERNAME)
        category = Category.objects.create(name='데이터분석')
        self.questions = [Question.objects.create(author=bot, category=category, subject='원고 '+(track or '기존'),
            column_track=track, content='검토할 본문이에요.', create_date=timezone.now())
            for track in ('research', 'practical', '')]

    def test_map_filters_and_search_retains_type_in_both_templates(self):
        for ua in ('Mozilla/5.0 Windows NT 10.0', 'Mozilla/5.0 iPhone Mobile/15E148'):
            for track, expected in zip(('research', 'practical', 'legacy'), self.questions):
                response = self.client.get('/map/', {'track': track, 'q': '원고'}, HTTP_USER_AGENT=ua)
                self.assertEqual(response.status_code, 200)
                self.assertEqual([e['q'].pk for e in response.context['results']], [expected.pk])
                self.assertContains(response, f'name="track" value="{track}"')

    def test_manual_classification_changes_only_type_and_records_reason(self):
        old = self.questions[-1]
        original_body, original_date = old.content, old.create_date
        with self.assertRaises(CommandError):
            call_command('classify_columns', question=old.pk, track='research', stdout=StringIO())
        call_command('classify_columns', question=old.pk, track='practical',
                     reason='본문의 중심이 카드 배분 계산 절차예요.', stdout=StringIO())
        old.refresh_from_db()
        self.assertEqual(old.column_track, 'practical')
        self.assertEqual((old.content, old.create_date), (original_body, original_date))
        self.assertEqual(AuditEvent.objects.get(action='column_classified').payload['after'], 'practical')

    def test_research_exemplar_cannot_fall_back_to_high_traffic_practical_article(self):
        from office.arsenal import exemplar
        research, practical = self.questions[:2]
        ColumnDraft.objects.create(topic='data', status='published', question=research,
            column_track='research', qa_report={'score': 86})
        ColumnDraft.objects.create(topic='data', status='published', question=practical,
            column_track='practical', qa_report={'score': 100})
        with E.use_track('research'):
            self.assertEqual(exemplar('data')['title'], research.subject)
        with E.use_track('practical'):
            self.assertEqual(exemplar('data')['title'], practical.subject)

    def test_admin_creation_defaults_to_two_and_rejects_invalid_track(self):
        from django.urls import reverse
        owner = User.objects.create_superuser('track-owner', '', 'x')
        self.client.force_login(owner)
        with patch('office.views._spawn') as spawn:
            response = self.client.post(reverse('office:run_job'), {'job': 'publish', 'topic': 'data'},
                                        HTTP_USER_AGENT='Mozilla/5.0')
            self.assertEqual(response.status_code, 302)
            self.assertEqual(spawn.call_args.args[1], ['office_publish', '--topic', 'data', '--track', 'both'])
            spawn.reset_mock()
            self.client.post(reverse('office:run_job'), {'job': 'publish', 'topic': 'data', 'track': 'unknown'},
                             HTTP_USER_AGENT='Mozilla/5.0')
            spawn.assert_not_called()

    def test_report_track_totals_include_old_runs_without_execution_metadata(self):
        import json
        import tempfile
        import uuid
        from pathlib import Path
        from office.models import StageRun
        for track in ('research', 'practical', ''):
            StageRun.objects.create(run_id=uuid.uuid4(), seq=1, stage='review',
                output={'score': 86, 'verdict': 'accept', **({'execution': {'column_track': track}} if track else {})})
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'report.json'
            call_command('lab_quality_report', output=str(output), stdout=StringIO())
            report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(report['sample_size'], 3)
        self.assertEqual({k: v['sample_size'] for k, v in report['editorial_tracks'].items()},
                         {'research': 1, 'practical': 1, 'legacy': 1})
