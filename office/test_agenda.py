"""공개 안건 — '기존 칼럼 /123/ 보강: …', ''연재' 3회 발행' 같은 내부 기획 문장을 독자용으로 바꾼다(office.agenda)."""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import Category, ColumnSeries, Question
from office import agenda as A
from office.models import Decision, Meeting


class PublicItemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(name='데이터분석')
        bot = User.objects.create_user('writer', password='x')
        cls.q = Question.objects.create(author=bot, category=cat, subject='ADsP·SQLD 공부 순서, 출발점이 정합니다',
                                        content='본문', create_date=timezone.now())
        cls.series = ColumnSeries.objects.create(slug='build-your-own-ai-agent', title='AI 에이전트, 직접 만들어 봅니다',
                                                 category=cat, total_episodes=10)
        ColumnSeries.objects.create(slug='django-for-vibe-coders', title='AI가 짜준 Django, 이제 알고 씁니다',
                                    category=cat, total_episodes=10)
        cls.meeting = Meeting.objects.create(week_start=date(2026, 11, 2))

    def decision(self, title, kind=Decision.KIND_COLUMN, note='공개 소개'):
        return Decision.objects.create(meeting=self.meeting, kind=kind, topic='data', question='q',
                                       options=[{'key': 'a', 'title': title}], chosen_key='a', public_note=note)

    def test_refresh_shows_the_real_article_title_and_link(self):
        item = A.public_item(self.decision(f'기존 칼럼 /{self.q.pk}/ 보강: 제목·도입부에 ADsP 점수 확인 앞세우기'))
        self.assertEqual((item['kind'], item['kind_label']), ('refresh', '다듬는 글'))
        self.assertEqual(item['title'], self.q.subject)
        self.assertEqual(item['url'], reverse('community:detail', args=[self.q.pk]))
        self.assertNotIn('/', item['title'])
        self.assertEqual(item['note'], '공개 소개')

    def test_refresh_of_missing_article_drops_the_number_and_instruction_prefix(self):
        item = A.public_item(self.decision('기존 칼럼 /99999/ 보강: 제목에 ONA 뜻 앞세우기'))
        self.assertEqual((item['kind'], item['title'], item['url']), ('refresh', '제목에 ONA 뜻 앞세우기', ''))

    def test_series_names_the_series_and_episode(self):
        item = A.public_item(self.decision("'AI 에이전트, 직접 만들어 봅니다' 3회 발행", kind=Decision.KIND_SERIES))
        self.assertEqual((item['title'], item['kind_label']), (self.series.title, '연재 3회'))
        self.assertEqual(item['url'], reverse('community:series_detail', args=[self.series.slug]))
        short = A.public_item(self.decision('Django 시리즈 8편을 이어서 발행', kind=Decision.KIND_SERIES))
        self.assertEqual((short['title'], short['kind_label']), ('AI가 짜준 Django, 이제 알고 씁니다', '연재 8회'))

    def test_new_article_is_unchanged(self):
        item = A.public_item(self.decision('SQLD 직전 2주, 과락은 이 과목에서 갈립니다'))
        self.assertEqual((item['kind_label'], item['title']), ('새 글', 'SQLD 직전 2주, 과락은 이 과목에서 갈립니다'))
        self.assertEqual(A.reader_title(self.decision('SQLD 직전 2주')), 'SQLD 직전 2주')

    def test_reader_title_for_one_line_places(self):
        d = self.decision(f'기존 칼럼 /{self.q.pk}/ 보강: 도입부 다듬기')
        self.assertEqual(A.reader_title(d), f'다듬는 글 · {self.q.subject}')

    def test_lab_home_shows_reader_facing_agenda(self):
        self.decision(f'기존 칼럼 /{self.q.pk}/ 보강: 제목·도입부에 ADsP 점수 확인 앞세우기')
        self.decision("'AI 에이전트, 직접 만들어 봅니다' 3회 발행", kind=Decision.KIND_SERIES)
        r = self.client.get(reverse('office:home'))
        html = r.content.decode()
        self.assertIn(self.q.subject, html)
        self.assertIn('다듬는 글', html)
        self.assertIn('<span class="tc-lb-tag">연재</span><span class="tc-lb-kind">3회</span>', html)
        self.assertNotIn(f'/{self.q.pk}/ 보강', html)
        self.assertNotIn('3회 발행', html)
