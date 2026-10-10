"""칼럼 지도 — 칼럼이 저장되면 요약을 다시 만들고, 관리자만 지도를 본다(office.digest·signals·views.column_map)."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import Category, ColumnSeries, Question
from office import digest as D
from office.models import ColumnDigest

BODY = ('ICF 2025 조사는 코칭 실무자를 122,974명으로 집계했습니다. 시장 성장은 효과의 증거가 아닙니다.\n\n'
        '## 참고 자료\n- ICF 2025')


def reply(summary='ICF 2025 조사는 실무자를 122,974명으로 집계했습니다. 효과는 자기 조직에서 재야 합니다.',
          subtopic='교육 효과 측정·전이'):
    return {'subtopic': subtopic, 'keywords': ['ICF Global Coaching Study', '코칭 문화', '메타분석'], 'summary': summary}


class DigestTests(TestCase):
    def setUp(self):
        self.bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        self.cat = Category.objects.create(name='HRD')
        with mock.patch('office.signals.transaction.on_commit'):
            self.q = Question.objects.create(author=self.bot, category=self.cat, subject='코칭 문화',
                                             content=BODY, create_date=timezone.now())

    def test_summary_numbers_must_come_from_the_column(self):
        calls = []

        def ask(key, prompt, **kw):
            calls.append(prompt)
            if len(calls) == 1:   # 본문에 없는 수치(10,035)를 쓰면 다시 쓰게 한다
                return reply('응답은 10,035건이었습니다. 효과는 자기 조직에서 재야 합니다.')
            return reply()
        item = D.make(self.q, ask_json=ask)
        self.assertEqual(len(calls), 2)
        self.assertIn('10,035', calls[1])
        self.assertIn('122,974', item['summary'])

    def test_sentence_with_unsourced_number_is_dropped_after_retry(self):
        item = D.make(self.q, ask_json=lambda *a, **k: reply('응답은 10,035건이었습니다. 효과는 자기 조직에서 재야 합니다.'))
        self.assertEqual(item['summary'], '효과는 자기 조직에서 재야 합니다.')

    def test_refresh_fills_missing_and_redoes_changed_columns_only(self):
        res = D.refresh(ask_json=lambda *a, **k: reply())
        self.assertEqual(res['done'], 1)
        self.assertEqual(D.pending(), [])
        Question.objects.filter(pk=self.q.pk).update(content=BODY + '\n추가 문단입니다.')   # 내용이 바뀌면 낡은 것
        self.assertEqual([q.pk for q in D.pending()], [self.q.pk])

    def test_existing_subtopics_are_offered_to_keep_names_consistent(self):
        D.save(self.q, reply())
        seen = []
        with mock.patch('office.signals.transaction.on_commit'):
            q2 = Question.objects.create(author=self.bot, category=self.cat, subject='전이', content=BODY,
                                         create_date=timezone.now())
        D.make(q2, ask_json=lambda key, prompt, **kw: seen.append(prompt) or reply())
        self.assertIn('교육 효과 측정·전이', seen[0])

    def test_series_episode_sits_under_series_title(self):
        s = ColumnSeries.objects.create(slug='agent', title='AI 에이전트, 직접 만들어 봅니다', category=self.cat,
                                        total_episodes=10)
        with mock.patch('office.signals.transaction.on_commit'):
            ep = Question.objects.create(author=self.bot, category=self.cat, subject='0편', content=BODY,
                                         create_date=timezone.now(), series=s, episode_number=0)
        self.assertEqual(D.make(ep, ask_json=lambda *a, **k: reply())['subtopic'], s.title)

    def test_import_uses_current_content_hash(self):
        n = D.import_items([{'id': self.q.pk, **reply()}, {'id': 999999, **reply()}])
        self.assertEqual(n, 1)
        self.assertEqual(D.pending(), [])
        self.assertEqual(ColumnDigest.objects.get().source, 'import')


class SignalTests(TestCase):
    def setUp(self):
        self.bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        self.cat = Category.objects.create(name='HRD')

    def test_new_or_changed_column_launches_refresh_after_commit(self):
        with mock.patch('office.jobs.spawn') as spawn:
            with self.captureOnCommitCallbacks(execute=True):
                q = Question.objects.create(author=self.bot, category=self.cat, subject='새 칼럼', content=BODY,
                                            create_date=timezone.now())
            self.assertEqual(spawn.call_args.args[0][0], 'update_column_map')
            self.assertEqual(spawn.call_args.kwargs['env'], {'CLAUDE_CLI_FALLBACK': 'false'})   # 유료 API 쓰지 않음
            D.save(q, reply())
            spawn.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                q.save()                                            # 내용이 같으면 띄우지 않는다
                q.save(update_fields=['view_count'])
            spawn.assert_not_called()
            with self.captureOnCommitCallbacks(execute=True):
                q.content = BODY + '\n고친 문단입니다.'
                q.save()
            spawn.assert_called_once()

    def test_member_posts_are_ignored(self):
        member = User.objects.create_user('member', password='x')
        with mock.patch('office.jobs.spawn') as spawn:
            with self.captureOnCommitCallbacks(execute=True):
                Question.objects.create(author=member, category=self.cat, subject='질문', content='본문',
                                        create_date=timezone.now())
        spawn.assert_not_called()


class ColumnMapViewTests(TestCase):
    def setUp(self):
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        cat = Category.objects.create(name='HRD')
        with mock.patch('office.signals.transaction.on_commit'):
            self.q = Question.objects.create(author=bot, category=cat, subject='코칭 문화', content=BODY,
                                             create_date=timezone.now())
            Question.objects.create(author=bot, category=cat, subject='아직 요약 없음', content=BODY + ' 다른 글',
                                    create_date=timezone.now())
        D.save(self.q, reply())
        self.url = reverse('office:column_map')

    def test_admin_sees_grouped_map_with_pdf_button(self):
        User.objects.create_superuser('boss', 'b@x.com', 'x')
        self.client.login(username='boss', password='x')
        r = self.client.get(self.url, HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('교육 효과 측정·전이', html)
        self.assertIn('ICF Global Coaching Study', html)
        self.assertIn('요약을 만드는 중입니다', html)                    # 요약 없는 글도 지도에 오른다
        self.assertIn('PDF로 저장', html)
        self.assertIn('@media print', html)
        hrd = r.context['groups'][0]
        self.assertEqual(hrd['count'], 2)
        self.assertEqual(r.context['stale'], 1)

    def test_members_cannot_open_the_map(self):
        User.objects.create_user('member', password='x')
        self.client.login(username='member', password='x')
        r = self.client.get(self.url, HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(r.status_code, 302)

    def test_refresh_button_launches_job(self):
        User.objects.create_superuser('boss', 'b@x.com', 'x')
        self.client.login(username='boss', password='x')
        with mock.patch('office.jobs.spawn') as spawn:
            r = self.client.post(reverse('office:run_job'), {'job': 'column_map'}, HTTP_USER_AGENT='Mozilla/5.0')
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertEqual(spawn.call_args.args[0], ['update_column_map'])
