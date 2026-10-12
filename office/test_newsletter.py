"""연구실 위클리 — 사실 모으기·문구 검사·한 호 만들기·공개 페이지(office.newsletter, views.newsletter_*)."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office import newsletter as N
from office.models import Newsletter, WorkLog


def no_gsc():
    return mock.patch.object(N, '_gsc', return_value={})


class WindowTests(TestCase):
    def test_friday_run_covers_last_friday_to_thursday(self):
        start, end = N.window(date(2026, 10, 16))          # 금요일
        self.assertEqual((start, end), (date(2026, 10, 9), date(2026, 10, 15)))
        self.assertEqual(N.week_code(date(2026, 10, 16)), ('2026 W42', '2026-w42'))


class CollectTests(TestCase):
    def setUp(self):
        self.bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        self.cat = Category.objects.create(name='HRD')
        with mock.patch('office.signals.transaction.on_commit'):
            self.new = Question.objects.create(author=self.bot, category=self.cat, subject='새 칼럼', content='본문',
                                               create_date=timezone.now())
            self.old = Question.objects.create(author=self.bot, category=self.cat, subject='다듬은 칼럼', content='본문',
                                               create_date=timezone.now())
        WorkLog.objects.create(agent='editor', action='publish', text=f'발행: 새 칼럼 (id={self.new.pk}, 84점)')
        WorkLog.objects.create(agent='editor', action='publish', text=f'리메이크 발행: 다듬은 칼럼 (id={self.old.pk})')
        WorkLog.objects.create(agent='editor', action='publish', text='발행: 사라진 글 (id=99999)')
        self.run = timezone.localdate() + timedelta(days=1)

    def test_published_lists_new_first_and_marks_remakes(self):
        with no_gsc():
            facts = N.collect(self.run)
        pub = facts['published']
        self.assertEqual([p['id'] for p in pub], [self.new.pk, self.old.pk])   # 없는 글은 빠지고 새 글이 먼저
        self.assertEqual(pub[0]['score'], 84)
        self.assertEqual(pub[0]['cat'], 'HRD')
        self.assertTrue(pub[1]['cat'].startswith('갱신 · '))
        self.assertEqual(len(facts['visits']), 7)
        self.assertEqual(len(facts['next']), 5)
        self.assertEqual(facts['next'], sorted(facts['next'], key=lambda r: r['date']))

    def test_default_copy_fits_the_limits(self):
        with no_gsc():
            facts = N.collect(self.run)
        copy = N.default_copy(facts)
        self.assertEqual(N._problems(copy, facts), [])


FACTS = {'start': '2026-10-09', 'end': '2026-10-15',
         'published': [{'id': 7, 'title': '코칭 문화', 'cat': 'HRD', 'remake': False, 'score': 84, 'author_key': 'hrd',
                        'date': '10.13', 'summary': '실무자는 122,974명입니다. 효과는 조직에서 재야 합니다.', 'url': '/7/'}],
         'ledger': [{'label': '검증한 주장', 'value': '12', 'unit': '건'}],
         'numbers': [{'value': '377', 'unit': '일', 'label': '운영', 'note': ''}],
         'visits': [], 'visits_peak': 0, 'next': [{'day': '토', 'what': '프로그래밍 칼럼', 'note': '10.17(토)'}]}


def good(**kw):
    c = {'theme': '숫자를 *원문*으로', 'intro': '이번 주 칼럼 1편을 냈습니다. 검증한 주장은 12건입니다.',
         'takeaways': {'7': '코칭 효과는 자기 조직에서 재야 합니다.'},
         'behind': {'agent': 'checker', 'line': '원문에 있는 숫자만 남겼습니다.'}}
    c.update(kw)
    return c


class CurateTests(TestCase):
    def test_invented_number_is_sent_back_once(self):
        calls = []

        def ask(key, prompt, **kw):
            calls.append(prompt)
            return good(intro='이번 주 칼럼 1편을 냈습니다. 조회는 5,321회였습니다.') if len(calls) == 1 else good()
        copy = N.curate(FACTS, ask_json=ask)
        self.assertEqual(copy['source'], 'curator')
        self.assertEqual(len(calls), 2)
        self.assertIn('5,321', calls[1])

    def test_falls_back_when_still_wrong_or_failing(self):
        long = N.curate(FACTS, ask_json=lambda *a, **k: good(theme='가' * 40))
        self.assertEqual(long['source'], 'default')

        def boom(*a, **k):
            raise RuntimeError('CLI 없음')
        self.assertEqual(N.curate(FACTS, ask_json=boom)['source'], 'default')

    def test_unknown_agent_is_a_problem(self):
        self.assertTrue(N._problems(good(behind={'agent': 'nobody', 'line': '안녕하세요'}), FACTS))


class MakeTests(TestCase):
    def setUp(self):
        self.run = date(2026, 10, 16)

    def fake_renderer(self, overflow_first=()):
        state = {'n': 0, 'dirs': []}

        def r(nl, out_dir):
            if out_dir:
                state['dirs'].append(out_dir)
                return []
            state['n'] += 1
            return list(overflow_first) if state['n'] == 1 else []
        return r, state

    def test_make_publishes_and_rerun_updates_same_issue(self):
        r, state = self.fake_renderer()
        with no_gsc():
            a = N.make(self.run, ask_json=lambda *a, **k: good(takeaways={}), renderer=r, out=lambda *_: None)
            b = N.make(self.run, renderer=r, use_model=False, out=lambda *_: None)
        self.assertEqual((a.issue_no, a.slug, b.pk), (1, '2026-w42', a.pk))
        self.assertEqual(Newsletter.objects.count(), 1)
        b.refresh_from_db()
        self.assertEqual(b.status, Newsletter.STATUS_PUBLISHED)
        self.assertEqual(len(b.cards), 5)
        self.assertIn('/newsletter/2026-w42/og.png', b.og_image)
        self.assertTrue(state['dirs'][0].endswith('2026-w42'))

    def test_overflow_asks_curator_to_shorten(self):
        r, _ = self.fake_renderer(overflow_first=['theme'])
        prompts = []

        def ask(key, prompt, **kw):
            prompts.append(prompt)
            return good(takeaways={})
        with no_gsc():
            N.make(self.run, ask_json=ask, renderer=r, out=lambda *_: None)
        self.assertEqual(len(prompts), 2)
        self.assertIn('넘쳤습니다', prompts[1])

    def test_dry_run_saves_nothing(self):
        r, state = self.fake_renderer()
        with no_gsc():
            res = N.make(self.run, dry=True, renderer=r, use_model=False, out=lambda *_: None)
        self.assertEqual(Newsletter.objects.count(), 0)
        self.assertTrue(state['dirs'][0].endswith('_dry'))
        self.assertEqual(len(res['cards']), 6)


class PageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.issue = Newsletter.objects.create(
            issue_no=1, slug='2026-w42', week_start=date(2026, 10, 9), week_end=date(2026, 10, 15),
            title='숫자를 원문으로', intro='이번 주 칼럼 1편을 냈습니다.', data={'facts': FACTS, 'copy': good()},
            cards=[f'/media/newsletter/2026-w42/card-{i}.png' for i in range(1, 6)],
            og_image='/media/newsletter/2026-w42/og.png', status=Newsletter.STATUS_PUBLISHED, published_at=timezone.now())
        Newsletter.objects.create(issue_no=2, slug='2026-w43', week_start=date(2026, 10, 16), week_end=date(2026, 10, 22),
                                  title='보류된 호', status=Newsletter.STATUS_HOLD)

    def test_list_and_detail_show_published_only(self):
        r = self.client.get('/newsletter/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(r, '숫자를 원문으로')
        self.assertNotContains(r, '보류된 호')
        r = self.client.get('/newsletter/2026-w42/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(r, 'card-5.png')
        self.assertContains(r, '코칭 효과는 자기 조직에서 재야 합니다.')
        self.assertContains(r, 'http://testserver/media/newsletter/2026-w42/og.png')
        self.assertEqual(self.client.get('/newsletter/2026-w43/', HTTP_USER_AGENT='Mozilla/5.0').status_code, 404)

    def test_mobile_detail_renders(self):
        self.client.cookies['force_version'] = 'mobile'
        r = self.client.get('/newsletter/2026-w42/', HTTP_USER_AGENT='Mozilla/5.0 (iPhone)')
        self.assertContains(r, 'nl-track')

    def test_sitemap_and_home_link(self):
        self.assertContains(self.client.get('/sitemap.xml', HTTP_USER_AGENT='Mozilla/5.0'), 'sitemap-newsletter.xml')
        r = self.client.get('/sitemap-newsletter.xml', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(r, '/newsletter/2026-w42/')
        self.assertNotContains(r, '/newsletter/2026-w43/')
        r = self.client.get('/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(r, '/newsletter/2026-w42/')
