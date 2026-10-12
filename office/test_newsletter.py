"""연구실 위클리 — 사실 모으기·문구 검사·한 호 만들기·공개 페이지(office.newsletter, views.newsletter_*)."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office import newsletter as N
from office.models import ColumnDraft, Decision, Meeting, Newsletter, WorkLog


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

    def making_setup(self):
        m = Meeting.objects.create(week_start=timezone.localdate(), transcript=[
            {'agent': 'lead', 'round': 1, 'text': '방문자는 늘었는데 검색 클릭은 10회뿐이었습니다.'},
            {'agent': 'hrd', 'round': 1, 'text': '한빈입니다. "피어러닝"이 노출 4회에 클릭 0이라 '
                                                 '「피어러닝이 성과로 이어지는 조건」을 제안합니다. 검색하는 사람은 있는데 답이 없습니다.'}])
        d = Decision.objects.create(meeting=m, kind='column', topic='hrd', question='다음 주 HRD 칼럼 주제', chosen_key='a',
                                    options=[{'key': 'a', 'title': '피어러닝이 성과로 이어지는 조건', 'proposed_by': '한빈'}])
        dr = ColumnDraft.objects.create(topic='hrd', decision=d, subject='새 칼럼', status=ColumnDraft.STATUS_PUBLISHED,
                                        question=self.new, revisions=2)
        for action, text in (('draft', '초안 완성: 동료에게 배우면 다 잘될까 (3845자)'),
                             ('qa', '편집 심사 62/100 (4291자) → 보류: 결론이 문장 중간에서 끊겼습니다.'),
                             ('admin_note', '운영자 수정 지시 접수: 비밀 지시문'),
                             ('revise', '재작성 실패 — 재작성본이 너무 짧아(1464자 < 6266자의 60%) 이전 원고 유지'),
                             ('qa', '재심 84/100 (4832자) → 발행: 발행에 동의합니다.')):
            WorkLog.objects.create(agent='editor', action=action, text=text, draft=dr)

    def test_making_tells_why_and_how_it_went(self):
        self.making_setup()
        with no_gsc():
            facts = N.collect(self.run)
        s = facts['making'][0]
        self.assertEqual(s['id'], self.new.pk)
        self.assertEqual(facts['hero_id'], self.new.pk)
        self.assertEqual(s['scores'], [62, 84])
        self.assertEqual(s['working_title'], '동료에게 배우면 다 잘될까')
        self.assertIn('한빈 제안', s['origin']['from'])
        self.assertIn('클릭 0', s['origin']['why'])
        self.assertTrue(any(n.startswith('사고:') for n in s['notes']))
        self.assertNotIn('비밀 지시문', N._facts_text(facts))      # 운영자 지시문은 싣지 않는다
        copy = N.default_copy(facts)
        self.assertEqual(N._problems(copy, facts), [])
        nl = N.context(facts, copy, 1, self.run)
        self.assertEqual([b['v'] for b in nl['hero']['bars']], [62, 84])
        self.assertEqual(nl['hero']['working'], '동료에게 배우면 다 잘될까')

    def test_default_copy_fits_the_limits_without_story(self):
        with no_gsc():
            facts = N.collect(self.run)
        self.assertIsNone(facts['hero_id'])
        copy = N.default_copy(facts)
        self.assertEqual(N._problems(copy, facts), [])


FACTS = {'start': '2026-10-09', 'end': '2026-10-15',
         'published': [{'id': 7, 'title': '코칭 문화', 'cat': 'HRD', 'remake': False, 'score': 84, 'author_key': 'hrd',
                        'date': '10.13', 'summary': '실무자는 122,974명입니다. 효과는 조직에서 재야 합니다.', 'url': '/7/'}],
         'ledger': [{'label': '검증한 주장', 'value': '12', 'unit': '건'}],
         'numbers': [{'value': '377', 'unit': '일', 'label': '운영', 'note': ''}],
         'visits': [], 'visits_peak': 0, 'next': [{'day': '토', 'what': '프로그래밍 칼럼', 'note': '10.17(토)'}],
         'making': [{'id': 7, 'title': '코칭 문화', 'remake': False, 'author_key': 'hrd', 'tries': 1,
                     'origin': {'from': '10.04 편집회의 · 한빈 제안', 'proposer': 'hrd', 'pitch': '코칭 문화',
                                'why': '코칭 검색은 많은데 우리 글이 없었습니다.'},
                     'working_title': '코칭은 왜 유행인가', 'scores': [62, 84], 'revisions': 2, 'fact_issues': 3, 'notes': []}],
         'hero_id': 7, 'week': {'rejected': 1, 'holds': 1}, 'meetings': []}


def good(**kw):
    c = {'theme': '62점에서 *살아난* 코칭', 'intro': '이번 주 칼럼 1편을 냈어요. 심사에서 한 번 넘어졌다 일어났어요.',
         'whys': {'7': '코칭 검색은 많은데 우리 글이 비어 있었어요.'},
         'hero': {'id': 7, 'headline': '62점의 굴욕', 'events': ['가제는 「코칭은 왜 유행인가」', '84점으로 통과했어요'],
                  'line': '제목부터 겸손해졌어요.'}}
    c.update(kw)
    return c


def quiet():
    """발행·제작기가 없는 주의 문구(숫자 없음)."""
    return {"theme": "조용한 *한 주*", "intro": "원고를 다듬었어요. 다음 주를 준비했어요.", "whys": {},
            "behind": {"agent": "checker", "line": "숫자만 남겼어요."}}


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

    def test_hero_must_match_and_fit(self):
        self.assertEqual(N._problems(good(), FACTS), [])
        self.assertTrue(N._problems(good(hero={'id': 8, 'headline': '남의 글', 'events': ['a', 'b'], 'line': '음'}), FACTS))
        self.assertTrue(N._problems(good(hero={'id': 7, 'headline': '짧게', 'events': ['하나뿐'], 'line': '음'}), FACTS))

    def test_without_hero_behind_needs_a_real_agent(self):
        facts = {**FACTS, 'hero_id': None}
        self.assertTrue(N._problems(good(behind={'agent': 'nobody', 'line': '안녕하세요'}), facts))
        self.assertEqual(N._problems(good(behind={'agent': 'checker', 'line': '안녕하세요'}), facts), [])


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
            a = N.make(self.run, ask_json=lambda *a, **k: quiet(), renderer=r, out=lambda *_: None)
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
            return quiet()
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
        self.assertContains(r, '코칭 검색은 많은데 우리 글이 비어 있었어요.')
        self.assertContains(r, '제작 일지 — 62점의 굴욕')
        self.assertContains(r, '코칭은 왜 유행인가')
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
