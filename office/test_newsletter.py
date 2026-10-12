"""연구실 위클리 — 추천 글·회의 대화 모으기, 문구 검사, 한 호 만들기, 공개 페이지(office.newsletter, views.newsletter_*)."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from community.models import Category, Question
from office import newsletter as N
from office.models import ColumnDigest, ColumnDraft, Decision, Meeting, Newsletter, WorkLog


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
            self.new = Question.objects.create(author=self.bot, category=self.cat, subject='피어러닝이 성과로 이어지는 조건',
                                               content='## 동료에게 묻는 순간\n본문\n## 성과로 잇는 세 가지\n본문\n## 참고 자료\n- x',
                                               create_date=timezone.now())
            self.old = Question.objects.create(author=self.bot, category=self.cat, subject='다듬은 칼럼', content='본문',
                                               create_date=timezone.now())
        ColumnDigest.objects.update_or_create(question=self.new, defaults={
            'subtopic': '학습 문화', 'keywords': ['피어러닝', '동료 학습'], 'content_hash': 'x',
            'summary': '동료 학습은 질문할 시간이 있어야 굴러갑니다. 성과로 잇는 조건 세 가지를 봅니다.'})
        WorkLog.objects.create(agent='editor', action='publish', text=f'발행: 피어러닝 (id={self.new.pk}, 84점)')
        WorkLog.objects.create(agent='editor', action='publish', text=f'리메이크 발행: 다듬은 칼럼 (id={self.old.pk})')
        WorkLog.objects.create(agent='editor', action='publish', text='발행: 사라진 글 (id=99999)')
        self.run = timezone.localdate() + timedelta(days=1)

    def meeting_setup(self):
        m = Meeting.objects.create(week_start=timezone.localdate(), transcript=[
            {'agent': 'lead', 'round': 1, 'text': '방문자는 늘었는데 검색 클릭은 10회뿐이었습니다.'},
            {'agent': 'hrd', 'round': 1, 'text': '한빈입니다. "피어러닝"이 노출 4회에 클릭 0이라 '
                                                 '「피어러닝이 성과로 이어지는 조건」을 제안합니다. 검색하는 사람은 있는데 답이 없습니다.'},
            {'agent': 'critic', 'round': 2, 'text': '피어러닝이 성과로 이어지는 조건은 사례 하나로 열면 좋겠습니다.'},
            {'agent': 'coding', 'round': 1, 'text': '서버 로그 이야기는 따로 하겠습니다.'}])
        d = Decision.objects.create(meeting=m, kind='column', topic='hrd', question='다음 주 HRD 칼럼 주제', chosen_key='a',
                                    options=[{'key': 'a', 'title': '피어러닝이 성과로 이어지는 조건', 'proposed_by': '한빈'}])
        dr = ColumnDraft.objects.create(topic='hrd', decision=d, subject='피어러닝', status=ColumnDraft.STATUS_PUBLISHED,
                                        question=self.new, revisions=4)
        WorkLog.objects.create(agent='editor', action='qa', text='편집 심사 62/100 → 보류', draft=dr)
        WorkLog.objects.create(agent='lead', action='admin_note', text='운영자 수정 지시 접수: 비밀 지시문', draft=dr)

    def test_picks_new_posts_with_digest_and_headings(self):
        facts = N.collect(self.run)
        self.assertEqual([p['id'] for p in facts['published']], [self.new.pk, self.old.pk])
        self.assertTrue(facts['published'][1]['cat'].startswith('갱신 · '))
        self.assertEqual([p['id'] for p in facts['picks']], [self.new.pk])          # 새 글이 있으면 새 글만 추천
        pick = facts['picks'][0]
        self.assertEqual(pick['keywords'], ['피어러닝', '동료 학습'])
        self.assertEqual(pick['headings'], ['동료에게 묻는 순간', '성과로 잇는 세 가지'])   # 참고 자료는 빼고
        self.assertEqual(len(facts['next']), 5)

    def test_meeting_talk_is_the_conversation_that_chose_the_topic(self):
        self.meeting_setup()
        facts = N.collect(self.run)
        pick = facts['picks'][0]
        self.assertIn('한빈 제안', pick['origin']['from'])
        lines = facts['meeting']['lines']
        self.assertEqual([ln['agent'] for ln in lines], ['lead', 'hrd', 'critic'])   # 브리핑·제안·반응, 무관한 발언은 빼고
        self.assertIn('클릭 0', lines[1]['text'])
        text = N._facts_text(facts)
        self.assertNotIn('비밀 지시문', text)          # 운영자 지시문은 싣지 않는다
        self.assertNotIn('62/100', text)              # 제작 과정 점수도 싣지 않는다
        copy = N.default_copy(facts)
        self.assertEqual(N._problems(copy, facts), [])
        nl = N.context(facts, copy, 1, self.run)
        self.assertEqual(nl['card_ids'], ['cover', 'meeting', 'pick-1', 'next', 'og'])
        self.assertEqual(nl['picks'][0]['page'], 3)
        self.assertEqual(len(nl['alts']), 4)

    def test_without_meeting_default_copy_still_passes(self):
        facts = N.collect(self.run)
        copy = N.default_copy(facts)
        self.assertEqual(copy['chat'], [])
        self.assertEqual(N._problems(copy, facts), [])
        self.assertEqual(N.context(facts, copy, 1, self.run)['card_ids'], ['cover', 'pick-1', 'next', 'og'])


PICK = {'id': 7, 'title': '코칭 문화', 'cat': 'HRD', 'author_key': 'hrd', 'date': '10.13', 'url': '/7/',
        'summary': '실무자는 122,974명입니다. 효과는 조직에서 재야 합니다.', 'keywords': ['코칭'], 'headings': ['효과를 재는 법'],
        'origin': {'decision_id': 1, 'from': '10.04 편집회의 · 한빈 제안', 'proposer': 'hrd', 'pitch': '코칭 문화',
                   'why': '코칭 검색은 많은데 우리 글이 없었습니다.'}}
FACTS = {'start': '2026-10-09', 'end': '2026-10-15',
         'published': [{'id': 7, 'title': '코칭 문화', 'cat': 'HRD', 'remake': False, 'score': 84, 'author_key': 'hrd',
                        'date': '10.13', 'summary': PICK['summary'], 'url': '/7/'}],
         'picks': [PICK],
         'meeting': {'date': '10.04', 'lines': [{'agent': 'lead', 'text': '검색 클릭은 10회였습니다.'},
                                                {'agent': 'hrd', 'text': '코칭 검색은 많은데 우리 글이 없었습니다.'},
                                                {'agent': 'critic', 'text': '사례 하나로 열면 좋겠습니다.'}]},
         'next': [{'day': '토', 'what': '프로그래밍 칼럼', 'note': '10.17(토)', 'agent': 'coding', 'date': '2026-10-17'}]}


def good(**kw):
    c = {'theme': '코칭, *유행*일까 효과일까', 'intro': '이번 주 추천은 코칭 칼럼이에요. 왜 골랐는지도 같이 적었어요.',
         'chat': [{'agent': 'lead', 'line': '검색 클릭이 10회뿐이었어요.'},
                  {'agent': 'hrd', 'line': '코칭은 찾는데 우리 글이 없더라고요.'},
                  {'agent': 'critic', 'line': '사례 하나로 열면 좋겠어요.'}],
         'picks': {'7': {'hook': '코칭, 돈 쓴 만큼 효과 있을까?', 'why_now': '코칭을 찾는 사람은 많은데 답해 줄 글이 없었어요.',
                         'points': ['시장 규모는 효과의 증거가 아니에요', '비교 집단을 두는 법', '조직에서 재는 순서'],
                         'for_whom': 'HRD·교육 담당자'}}}
    c.update(kw)
    return c


def quiet():
    """추천 글·회의가 없는 주의 문구(숫자 없음)."""
    return {'theme': '조용한 *한 주*', 'intro': '원고를 다듬었어요. 다음 주를 준비했어요.', 'chat': [], 'picks': {}}


class CurateTests(TestCase):
    def test_invented_number_is_sent_back_once(self):
        calls = []

        def ask(key, prompt, **kw):
            calls.append(prompt)
            return good(intro='이번 주 추천은 코칭이에요. 조회는 5,321회였어요.') if len(calls) == 1 else good()
        copy = N.curate(FACTS, ask_json=ask)
        self.assertEqual(copy['source'], 'curator')
        self.assertEqual(len(calls), 2)
        self.assertIn('5,321', calls[1])
        self.assertIn('수정 횟수·심사 점수·실패담은 쓰지 않습니다', calls[0])

    def test_falls_back_when_still_wrong_or_failing(self):
        self.assertEqual(N.curate(FACTS, ask_json=lambda *a, **k: good(theme='가' * 40))['source'], 'default')

        def boom(*a, **k):
            raise RuntimeError('CLI 없음')
        self.assertEqual(N.curate(FACTS, ask_json=boom)['source'], 'default')

    def test_picks_and_chat_are_checked(self):
        self.assertEqual(N._problems(good(), FACTS), [])
        bad_pick = good(picks={'7': {**good()['picks']['7'], 'points': ['하나뿐']}})
        self.assertTrue(N._problems(bad_pick, FACTS))
        self.assertTrue(N._problems(good(chat=[{'agent': 'nobody', 'line': '안녕'}] * 3), FACTS))
        self.assertTrue(N._problems(good(chat=[]), FACTS))                     # 회의가 있으면 대화가 있어야
        self.assertEqual(N._problems(N.default_copy(FACTS), FACTS), [])


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
        a = N.make(self.run, ask_json=lambda *a, **k: quiet(), renderer=r, out=lambda *_: None)
        b = N.make(self.run, renderer=r, use_model=False, out=lambda *_: None)
        self.assertEqual((a.issue_no, a.slug, b.pk), (1, '2026-w42', a.pk))
        self.assertEqual(Newsletter.objects.count(), 1)
        b.refresh_from_db()
        self.assertEqual(b.status, Newsletter.STATUS_PUBLISHED)
        self.assertEqual([u.split('?')[0].rsplit('/', 1)[1] for u in b.cards], ['cover.png', 'next.png'])  # 추천·회의 없는 주
        self.assertIn('/newsletter/2026-w42/og.png', b.og_image)
        self.assertEqual(len(b.data['alts']), 2)
        self.assertTrue(state['dirs'][0].endswith('2026-w42'))

    def test_overflow_asks_curator_to_shorten(self):
        r, _ = self.fake_renderer(overflow_first=['theme'])
        prompts = []

        def ask(key, prompt, **kw):
            prompts.append(prompt)
            return quiet()
        N.make(self.run, ask_json=ask, renderer=r, out=lambda *_: None)
        self.assertEqual(len(prompts), 2)
        self.assertIn('넘쳤습니다', prompts[1])

    def test_dry_run_saves_nothing(self):
        r, state = self.fake_renderer()
        res = N.make(self.run, dry=True, renderer=r, use_model=False, out=lambda *_: None)
        self.assertEqual(Newsletter.objects.count(), 0)
        self.assertTrue(state['dirs'][0].endswith('_dry'))
        self.assertEqual(len(res['cards']), 3)


class PageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.issue = Newsletter.objects.create(
            issue_no=1, slug='2026-w42', week_start=date(2026, 10, 9), week_end=date(2026, 10, 15),
            title='코칭, 유행일까 효과일까', intro='이번 주 추천은 코칭 칼럼이에요.',
            data={'facts': FACTS, 'copy': good(), 'alts': ['표지', '회의실에서', '추천 칼럼 1 — 코칭 문화', '다음 관측']},
            cards=[f'/media/newsletter/2026-w42/{c}.png' for c in ('cover', 'meeting', 'pick-1', 'next')],
            og_image='/media/newsletter/2026-w42/og.png', status=Newsletter.STATUS_PUBLISHED, published_at=timezone.now())
        Newsletter.objects.create(issue_no=2, slug='2026-w43', week_start=date(2026, 10, 16), week_end=date(2026, 10, 22),
                                  title='보류된 호', status=Newsletter.STATUS_HOLD)

    def test_list_and_detail_show_published_only(self):
        r = self.client.get('/newsletter/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(r, '코칭, 유행일까 효과일까')
        self.assertNotContains(r, '보류된 호')
        r = self.client.get('/newsletter/2026-w42/', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(r, 'pick-1.png')
        self.assertContains(r, '추천 칼럼 1 — 코칭 문화')
        self.assertContains(r, '코칭은 찾는데 우리 글이 없더라고요.')          # 회의실 대화
        self.assertContains(r, '코칭, 돈 쓴 만큼 효과 있을까?')               # 추천 훅
        self.assertContains(r, '비교 집단을 두는 법')
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
