"""공개 칼럼 지도(/map/) — 누구나 둘러보고 검색, PDF 는 회원만, 요약 갱신·연구실 관리는 관리자만."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import Category, ColumnSeries, Question
from office import digest as D

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
UA_MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'


class PublicColumnMapTests(TestCase):
    def setUp(self):
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        hrd, code = Category.objects.create(name='HRD'), Category.objects.create(name='프로그래밍')
        with mock.patch('office.signals.transaction.on_commit'):
            self.coach = Question.objects.create(author=bot, category=hrd, subject='코칭 문화 투자', content='코칭 본문',
                                                 create_date=timezone.now(), view_count=77)
            self.ai = Question.objects.create(author=bot, category=code, subject='AI 코드 검증', content='AI 본문',
                                              create_date=timezone.now(), view_count=74)
            self.raw = Question.objects.create(author=bot, category=hrd, subject='요약 없는 칼럼',
                                               content='첫 문단 요약입니다.', create_date=timezone.now())
        D.save(self.coach, {'subtopic': '리더십·피드백 문화', 'keywords': ['ICF Global Coaching Study', '메타분석'],
                            'summary': '코칭 시장 성장은 효과의 증거가 아니라고 지적합니다.'})
        D.save(self.ai, {'subtopic': 'AI 코딩 도구', 'keywords': ['Sonar', 'Veracode'],
                         'summary': '개발자가 AI 코드를 불신하면서도 검증하지 않는 이유를 묻습니다.'})
        self.url = reverse('community:column_map')

    def get(self, params='', ua=UA):
        r = self.client.get(self.url + params, HTTP_USER_AGENT=ua)
        self.assertEqual(r.status_code, 200)
        return r

    def test_anyone_can_browse_the_map(self):
        for ua in (UA, UA_MOBILE):
            html = self.get(ua=ua).content.decode()
            self.assertIn('칼럼 지도', html)
            self.assertIn('리더십·피드백 문화', html)
            self.assertIn('ICF Global Coaching Study', html)
            self.assertIn('첫 문단 요약입니다.', html)            # 요약이 아직 없으면 글머리 요약으로
            self.assertIn('<meta name="robots" content="index, follow">', html)

    def test_search_matches_all_words_highlights_and_is_noindex(self):
        r = self.get('?q=코칭+메타분석')
        self.assertEqual([e['q'].id for e in r.context['results']], [self.coach.id])
        html = r.content.decode()
        self.assertIn('<mark>코칭</mark>', html)
        self.assertIn('noindex, follow', html)
        self.assertEqual(self.get('?q=코칭+Sonar').context['results'], [])

    def test_category_and_subtopic_filters(self):
        r = self.get('?cat=coding')
        self.assertEqual([g['key'] for g in r.context['groups']], ['coding'])
        r = self.get('?sub=' + 'AI 코딩 도구')
        self.assertEqual([e['q'].id for e in r.context['results']], [self.ai.id])

    def test_search_input_is_escaped(self):
        html = self.get('?q=<script>alert(1)</script>').content.decode()
        self.assertNotIn('<script>alert(1)</script>', html)

    def test_pdf_is_members_only_and_admin_tools_are_admin_only(self):
        html = self.get().content.decode()
        self.assertIn('PDF 저장 · 회원 전용', html)
        self.assertNotIn('id="cm-pdf"', html)
        self.assertIn('class="cm guest"', html)                 # 비회원이 인쇄하면 본문 대신 안내
        self.assertNotIn('요약 갱신', html)

        member = User.objects.create_user('reader', password='x')
        member.profile.is_email_verified = True
        member.profile.save()
        self.client.login(username='reader', password='x')
        html = self.get().content.decode()
        self.assertIn('id="cm-pdf"', html)
        self.assertNotIn('요약 갱신', html)
        self.assertNotIn(reverse('office:admin'), html.split('class="cm')[1])

        User.objects.create_superuser('boss', 'b@x.com', 'x')
        self.client.login(username='boss', password='x')
        html = self.get().content.decode()
        self.assertIn('요약 갱신', html)
        self.assertIn('갱신 대기', html)                         # 요약 없는 칼럼 표시는 관리자에게만

    def test_series_episodes_sit_under_series_title_in_order(self):
        cat = Category.objects.get(name='프로그래밍')
        s = ColumnSeries.objects.create(slug='django', title='AI가 짜준 Django', category=cat, total_episodes=10)
        bot = User.objects.get(username=Question.BOT_USERNAME)
        with mock.patch('office.signals.transaction.on_commit'):
            for no in (2, 0, 1):
                Question.objects.create(author=bot, category=cat, subject=f'{no}편', content='본문',
                                        create_date=timezone.now(), series=s, episode_number=no)
        series = next(g for g in self.get('?cat=series').context['groups'] if g['key'] == 'series')
        self.assertEqual([e['q'].episode_number for e in series['subs'][0]['items']], [0, 1, 2])

    def test_map_is_linked_from_nav_and_sitemap(self):
        self.assertIn(self.url, self.client.get('/', HTTP_USER_AGENT=UA).content.decode())
        self.assertIn('https://techchang.com/map/', self.client.get('/sitemap-static.xml').content.decode())
