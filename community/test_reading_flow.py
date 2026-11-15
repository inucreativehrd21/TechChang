"""검색·가입 복귀·목록 복귀의 사용자 흐름과 권한 경계를 검증해요."""
from urllib.parse import quote

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from common.models import EmailVerification
from community.models import Answer, Category, ColumnSeries, Question

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Mobile/15E148'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ReadingFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.bot = User.objects.create_user(Question.BOT_USERNAME)
        self.author = User.objects.create_user('flow-reader', password='Strong-pass!2026')
        self.author.profile.is_email_verified = True
        self.author.profile.save(update_fields=['is_email_verified'])
        self.cat, _ = Category.objects.get_or_create(name='프로그래밍')
        self.inquiry, _ = Category.objects.get_or_create(name='문의')
        self.series = ColumnSeries.objects.create(slug='flow-agent', title='에이전트 배우기', category=self.cat)
        self.column = self.post('공개 칼럼', author=self.bot, operator_pick=True)
        self.episode = self.post('도구 쥐여 주기: 함수 호출', author=self.bot, series=self.series, episode_number=0)
        self.locked = self.post('잠금 글', is_locked=True, content='LOCKED_MARKER')
        self.secret = self.post('문의 글', category=self.inquiry, content='INQUIRY_MARKER')
        self.deleted = self.post('삭제 글', is_deleted=True, content='DELETED_MARKER')
        Answer.objects.create(question=self.column, author=self.author, content='REMOVED_ANSWER_MARKER',
                              is_deleted=True, create_date=timezone.now())

    def post(self, title, **values):
        args = dict(author=self.author, category=self.cat, subject=title,
                    content='여러 독자가 읽을 수 있는 공개 본문입니다. ' * 30, create_date=timezone.now())
        args.update(values)
        return Question.objects.create(**args)

    def get(self, url, **values):
        return self.client.get(url, HTTP_USER_AGENT=PC, **values)

    def test_home_search_and_explore_find_published_episode(self):
        response = self.get('/', data={'kw': '도구 쥐여 주기'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'community/explore.html')
        self.assertContains(response, self.episode.subject)
        self.assertEqual(list(response.context['results']), [self.episode])

    def test_search_filters_types_and_category(self):
        response = self.get('/explore/', data={'q': '함수 호출', 'kind': 'series', 'category': self.cat.name})
        self.assertEqual(list(response.context['results']), [self.episode])
        self.assertEqual(self.get('/explore/', data={'kind': 'post'}).context['results'].paginator.count, 0)
        response = self.get('/explore/', data={'kind': 'column'})
        self.assertEqual(list(response.context['results']), [self.column])

    def test_search_does_not_reveal_protected_or_removed_content(self):
        for query in ('LOCKED_MARKER', 'INQUIRY_MARKER', 'DELETED_MARKER', 'REMOVED_ANSWER_MARKER'):
            response = self.get('/explore/', data={'q': query})
            self.assertEqual(response.context['results'].paginator.count, 0, query)

    def test_other_member_cannot_search_private_inquiry(self):
        other = User.objects.create_user('flow-other')
        other.profile.is_email_verified = True
        other.profile.save(update_fields=['is_email_verified'])
        self.client.force_login(other)
        result = self.get('/explore/', data={'q': 'INQUIRY_MARKER'})
        self.assertEqual(result.context['results'].paginator.count, 0)

    def test_pagination_preserves_filters(self):
        for n in range(13):
            self.post(f'검색용 글 {n}')
        response = self.get('/explore/', data={'q': '검색용', 'kind': 'post', 'page': '2'})
        self.assertEqual(len(response.context['results']), 1)
        self.assertContains(response, 'kind=post')
        self.assertContains(response, 'page=1')

    def test_home_promotes_public_columns_and_keeps_game_entry(self):
        for ua in (PC, MOBILE):
            result = self.client.get('/', HTTP_USER_AGENT=ua)
            html = result.content.decode()
            self.assertLess(html.index('id="fl-start"'), html.index('id="tc-ball-title"'))
            self.assertContains(result, '칼럼 둘러보기')
            self.assertEqual(result.context['start_posts'][0], self.column)
            self.assertNotIn(self.locked, result.context['start_posts'])
            self.assertContains(result, 'data-tc-mode-open', count=1)

    def test_mobile_exposes_explore_activity_and_write_in_community(self):
        result = self.client.get('/', HTTP_USER_AGENT=MOBILE)
        self.assertContains(result, '<span>탐색</span>')
        self.assertContains(result, '<span>내 활동</span>')
        self.assertContains(self.client.get('/board/', HTTP_USER_AGENT=MOBILE), reverse('community:question_create'))

    def test_list_return_keeps_query_page_and_anchor(self):
        source = '/explore/?q=함수&page=2#fl-results'
        result = self.get(reverse('community:detail', args=[self.episode.pk]), data={'from': source})
        self.assertEqual(result.context['back_url'], source)
        self.assertEqual(result.context['back_label'], '탐색 결과')

    def test_direct_episode_returns_to_its_series(self):
        result = self.get(reverse('community:detail', args=[self.episode.pk]))
        self.assertEqual(result.context['back_url'], reverse('community:series_detail', args=[self.series.slug]))

    def test_external_and_non_list_return_addresses_are_ignored(self):
        for value in ('https://evil.example/', '//evil.example/', '/common/logout/'):
            result = self.get(reverse('community:detail', args=[self.column.pk]), data={'from': value})
            self.assertEqual(result.context['back_url'], '/explore/')

    def test_only_public_columns_get_browser_reading_tools(self):
        for ua in (PC, MOBILE):
            result = self.client.get(reverse('community:detail', args=[self.column.pk]), HTTP_USER_AGENT=ua)
            self.assertContains(result, 'data-reading-article')
            self.assertContains(result, 'data-reading-body')
        self.client.force_login(self.author)
        self.assertNotContains(self.get(reverse('community:detail', args=[self.locked.pk])), 'data-reading-article')

    def test_personal_and_search_pages_are_noindex(self):
        for route in ('/explore/', '/my/'):
            for ua in (PC, MOBILE):
                result = self.client.get(route, HTTP_USER_AGENT=ua)
                self.assertEqual(result.status_code, 200)
                self.assertContains(result, 'noindex, follow')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SignupReturnTests(TestCase):
    def test_signup_accepts_the_full_server_verification_code(self):
        for ua in (PC, MOBILE):
            response = self.client.get('/common/signup/', HTTP_USER_AGENT=ua)
            self.assertContains(response, f'maxlength="{EmailVerification.CODE_LENGTH}"')
            self.assertContains(response, 'autocomplete="one-time-code"')

    def test_login_signup_link_keeps_fragment_and_query(self):
        target = '/123/?from=%2Fexplore%2F%3Fq%3Dagent#tc-takeaway-q'
        for ua in (PC, MOBILE):
            response = self.client.get('/common/login/', {'next': target}, HTTP_USER_AGENT=ua)
            self.assertContains(response, '/common/signup/?next=' + quote(target, safe='/'))

    def test_signup_errors_keep_safe_destination_and_mobile_layout(self):
        for ua in (PC, MOBILE):
            response = self.client.post('/common/signup/', {'next': '/rookie/lite/'}, HTTP_USER_AGENT=ua)
            self.assertEqual(response.context['next'], '/rookie/lite/')
            self.assertContains(response, 'name="next" value="/rookie/lite/"')
            if ua == MOBILE:
                self.assertTemplateUsed(response, 'base_mobile.html')

    def test_signup_completion_returns_to_original_action(self):
        target = '/rookie/lite/?from=home#career'
        EmailVerification.objects.create(email='return@example.com', code='12345678',
                                         is_verified=True, verified_at=timezone.now())
        response = self.client.post('/common/signup/', {
            'username': 'return-new', 'email': 'return@example.com',
            'password1': 'Strong-pass!2026', 'password2': 'Strong-pass!2026',
            'agree_age': '1', 'agree_terms': '1', 'agree_privacy': '1', 'next': target,
        }, HTTP_USER_AGENT=PC)
        self.assertRedirects(response, target, fetch_redirect_response=False)
        self.assertIn('_auth_user_id', self.client.session)

    def test_signup_rejects_external_downgrade_and_auth_loop_destinations(self):
        for value in ('https://evil.example/', '//evil.example/', 'javascript:alert(1)', '/common/signup/',
                      'http://testserver/rookie/'):
            response = self.client.get('/common/signup/', {'next': value}, secure=True, HTTP_USER_AGENT=PC)
            self.assertEqual(response.context['next'], '/', value)
