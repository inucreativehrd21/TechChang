from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User

from .models import Question, Category


class InquiryDetailAccessTests(TestCase):
    """'문의' 글 열람 권한 처리 회귀 테스트.

    과거 detail 뷰가 is_locked 분기 안에서 redirect 를 지역 재import 하여,
    잠기지 않은 '문의' 글을 비권한 사용자가 열면 UnboundLocalError(500) 가
    발생했다. 비권한 접근은 500 이 아니라 리다이렉트(302)여야 한다.
    """

    def setUp(self):
        self.inquiry = Category.objects.create(name='문의')
        self.author = User.objects.create_user('writer', password='pw-12345')
        self.question = Question.objects.create(
            author=self.author,
            subject='문의 테스트',
            content='본문',
            create_date=timezone.now(),
            category=self.inquiry,
            is_locked=False,
        )

    def test_anonymous_user_is_redirected_not_500(self):
        response = self.client.get(f'/{self.question.pk}/')
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('community:index'))
