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
            {'agent': 'data', 'round': 2, 'text': '피어러닝이 성과로 이어지는 조건을 보려면 적용 사례를 함께 모아야 합니다.'},
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
        # 팀장의 지표 브리핑은 싣지 않고(방문·클릭 수), 제안·반응만. 제안 발언에서도 지표 문장은 빠진다
        self.assertEqual([ln['agent'] for ln in lines], ['hrd', 'critic', 'data'])
        self.assertNotIn('클릭', lines[0]['text'])
        self.assertIn('검색하는 사람은 있는데 답이 없습니다', lines[0]['text'])
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
         'meeting': {'date': '10.04', 'lines': [{'agent': 'hrd', 'text': '코칭에 예산을 쓰는 조직이 늘었는데 효과를 묻는 질문은 드뭅니다.'},
                                                {'agent': 'data', 'text': '효과는 조직 안에서 직접 재야 한다는 점을 짚겠습니다.'},
                                                {'agent': 'critic', 'text': '사례 하나로 열면 좋겠습니다.'}]},
         'next': [{'day': '토', 'what': '프로그래밍 칼럼', 'note': '10.17(토)', 'agent': 'coding', 'date': '2026-10-17'}]}


def good(**kw):
    c = {'theme': '코칭, *유행*일까 효과일까', 'intro': '이번 주 추천은 코칭 칼럼이에요. 왜 골랐는지도 같이 적었어요.',
         'chat': [{'agent': 'hrd', 'line': '코칭 예산은 늘었는데 효과를 묻는 사람은 드물어요.'},
                  {'agent': 'data', 'line': '효과는 조직 안에서 직접 재야 해요.'},
                  {'agent': 'critic', 'line': '사례 하나로 열면 좋겠어요.'}],
         'picks': {'7': {'hook': '코칭, 돈 쓴 만큼 효과 있을까?', 'why_now': '코칭 예산을 정하는 시기라 효과를 따져 볼 근거가 필요해요.',
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
            calls.append((key, prompt))
            if key == 'critic':
                return {'must_fix': []}
            sent = [p for k, p in calls if k == N.CURATOR]
            return good(intro='이번 주 추천은 코칭이에요. 조회는 5,321회였어요.') if len(sent) == 1 else good()
        copy = N.curate(FACTS, ask_json=ask)
        self.assertEqual(copy['source'], 'curator')
        self.assertEqual([k for k, _ in calls], [N.CURATOR, N.CURATOR, 'critic'])   # 숫자 날조로 1회 재시도 뒤 평론
        self.assertIn('5,321', calls[1][1])
        self.assertIn('수정 횟수·심사 점수·실패담은 쓰지 않습니다', calls[0][1])

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


class CriticReviewTests(TestCase):
    """2026-10-24 — 은혜(큐레이터)가 고른 안건을 은혜가 쓴 문구 그대로 내보내던 것을, 예원(평론가)이
    한 번 더 보게 한다. '뻔한 이유'·'끊겨 보이는 문장'처럼 기계적으로는 못 거르는 것만 본다."""

    def test_critic_flags_copy_and_curator_rewrites_once(self):
        calls = []

        def ask(key, prompt, **kw):
            calls.append(key)
            if key == 'critic':
                return {'must_fix': [{'where': '효과 있을까?', 'problem': '뻔한 이유', 'fix': '구체적으로'}]}
            return good()
        copy = N.curate(FACTS, ask_json=ask)
        self.assertEqual(copy['source'], 'curator')
        self.assertEqual(calls, [N.CURATOR, 'critic', N.CURATOR])

    def test_falls_back_when_review_rewrite_call_fails(self):
        def ask(key, prompt, **kw):
            if key == 'critic':
                return {'must_fix': [{'where': 'x', 'problem': 'y', 'fix': 'z'}]}
            if '평론가(예원)의 지적' in prompt:
                raise RuntimeError('재작성 실패')
            return good()
        self.assertEqual(N.curate(FACTS, ask_json=ask)['source'], 'default')

    def test_falls_back_when_rewrite_still_breaks_mechanical_rules(self):
        def ask(key, prompt, **kw):
            if key == 'critic':
                return {'must_fix': [{'where': 'x', 'problem': 'y', 'fix': 'z'}]}
            if '평론가(예원)의 지적' in prompt:
                return good(theme='가' * 40)       # 다시 써도 길이 규칙을 또 어김
            return good()
        self.assertEqual(N.curate(FACTS, ask_json=ask)['source'], 'default')

    def test_critic_call_failure_does_not_block_publishing(self):
        def ask(key, prompt, **kw):
            if key == 'critic':
                raise RuntimeError('평론가 호출 실패')
            return good()
        self.assertEqual(N.curate(FACTS, ask_json=ask)['source'], 'curator')


class DefaultCopyTruncationTests(TestCase):
    """2026-10-24 — 위클리 카드에 "...도입 판단에 무엇..." 처럼 문장 중간에서 뚝 끊긴 문구가 나간 사고.
    default_copy() 의 폴백 문구가 글자 수로만 자르던 것을 단어 경계·완결 문장 기준으로 고쳤다."""

    def test_shortest_fit_prefers_a_candidate_that_already_fits(self):
        long_one = '아주 길어서 글자수 제한을 넘기는 두 번째 문장입니다 그래서 이건 선택되면 안 됩니다'
        self.assertEqual(N._shortest_fit(['짧은 문장입니다', long_one], 10, '짧은 문장입니다'), '짧은 문장입니다')

    def test_shortest_fit_cuts_at_a_word_boundary_not_mid_word(self):
        long = ('스테이징이 없는 jj가 매일 쓰는 Git 작업 여섯 가지를 어떻게 옮기는지, '
                '1대1 번역이 안 되는 지점이 도입 판단에 무엇을 뜻하는지를 정리했습니다')
        out = N._shortest_fit([long], 40, long)
        self.assertLessEqual(len(out), 40)
        self.assertTrue(out.endswith('…'))
        body = out[:-1]
        self.assertTrue(long.startswith(body))
        self.assertIn(long[len(body):len(body) + 1], ('', ' '))   # 잘린 바로 다음 글자가 공백 — 단어 중간이 아님

    def test_default_copy_why_now_is_a_whole_sentence_when_it_fits(self):
        facts = {**FACTS, 'picks': [{**PICK, 'summary': '짧은 요약입니다. 두 번째 문장도 짧습니다.'}]}
        copy = N.default_copy(facts)
        self.assertEqual(copy['picks']['7']['why_now'], '짧은 요약입니다.')


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
        calls = []

        def ask(key, prompt, **kw):
            calls.append((key, prompt))
            return {'must_fix': []} if key == 'critic' else quiet()
        N.make(self.run, ask_json=ask, renderer=r, out=lambda *_: None)
        curator_prompts = [p for k, p in calls if k == N.CURATOR]
        self.assertEqual(len(curator_prompts), 2)             # 넘침 전 1회 + 넘침 뒤 다시 쓰기 1회
        self.assertIn('넘쳤습니다', curator_prompts[1])
        self.assertEqual([k for k, _ in calls].count('critic'), 2)   # 두 큐레이션 결과 각각 평론가가 봄

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
        self.assertContains(r, '코칭 예산은 늘었는데 효과를 묻는 사람은 드물어요.')   # 회의실 대화
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



class PublicGuardTests(TestCase):
    """2026-10-16 No.2 — 회의실 카드에 '방문자 3301명, 클릭 10회, 추천 0'이 나가고 말풍선이 아래 상자에 닿았다."""

    def test_site_metrics_and_catalog_gaps_are_rejected(self):
        bad = good(chat=[{'agent': 'lead', 'line': '방문자 3301명, 검색 클릭은 10회뿐. 추천은 전부 0이에요.'},
                         {'agent': 'hrd', 'line': '학습 전이는 최근 HRD 칼럼에 같은 주제가 없었어요.'},
                         {'agent': 'critic', 'line': '사례 하나로 열면 좋겠어요.'}],
                   picks={'7': {**good()['picks']['7'], 'why_now': '회의에서 검색어에 코칭이 보였어요.'}})
        probs = N.public_problems(bad, FACTS)
        self.assertTrue(any('chat[0]' in p and '지표' in p for p in probs))
        self.assertTrue(any('chat[1]' in p and '운영 사정' in p for p in probs))
        self.assertTrue(any('why_now' in p and '회의에서' in p for p in probs))
        self.assertEqual(N.public_problems(good(), FACTS), [])

    def test_meeting_scrub_drops_metric_sentences(self):
        text = '방문자는 3301명으로 늘었습니다. 현장에서는 교육 뒤 적용이 안 된다는 고민이 많습니다. 최근 HRD 칼럼 중 같은 주제는 없었습니다.'
        self.assertEqual(N._scrub(text), '현장에서는 교육 뒤 적용이 안 된다는 고민이 많습니다.')

    def test_meeting_card_trims_bubbles_until_it_fits(self):
        copy = good(chat=good()['chat'] + [{'agent': 'lead', 'line': '정리해 볼게요.'}])
        self.assertTrue(N._fix_layout(['layout:meeting'], copy))
        self.assertEqual(len(copy['chat']), 3)
        self.assertFalse(N._fix_layout(['layout:meeting'], copy))          # 3개 밑으로는 줄이지 않는다
        self.assertFalse(N._fix_layout(['layout:pick-1'], copy))

    def test_broken_layout_is_held_not_published(self):
        run = date(2026, 10, 16)
        with mock.patch('office.jobmail.send') as send:
            obj = N.make(run, renderer=lambda nl, d: ['layout:next'], use_model=False, out=lambda *_: None)
        self.assertEqual(obj.status, Newsletter.STATUS_HOLD)
        self.assertIsNone(obj.published_at)
        send.assert_called_once()
        self.assertIn('공개 보류', send.call_args.args[0])
        self.assertEqual(self.client.get('/newsletter/', HTTP_USER_AGENT='Mozilla/5.0').status_code, 200)
        self.assertEqual(self.client.get(f'/newsletter/{obj.slug}/', HTTP_USER_AGENT='Mozilla/5.0').status_code, 404)

    def test_rerun_with_problems_keeps_the_published_issue(self):
        run = date(2026, 10, 16)
        ok = N.make(run, renderer=lambda nl, d: [], use_model=False, out=lambda *_: None)
        with mock.patch('office.jobmail.send'):
            again = N.make(run, renderer=lambda nl, d: ['layout:cover'], use_model=False, out=lambda *_: None)
        self.assertEqual(again.pk, ok.pk)
        ok.refresh_from_db()
        self.assertEqual(ok.status, Newsletter.STATUS_PUBLISHED)
