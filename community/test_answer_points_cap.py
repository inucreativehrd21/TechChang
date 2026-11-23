"""답변 포인트 하루 상한(100P) — 상한까지만 지급하고, 지울 때는 받은 만큼만 회수해요."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from common.models import PointHistory, Profile
from community.models import Answer, Category, Question
from community.utils import ANSWER_DAILY_CAP, ANSWER_POINTS

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'


class AnswerPointCapTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('writer', password='pw-12345678')
        Profile.objects.update_or_create(user=self.user, defaults={'is_email_verified': True, 'points': 0})
        self.question = Question.objects.create(author=self.user, subject='질문', content='내용',
                                                category=Category.objects.create(name='문의'),
                                                create_date=timezone.now())
        self.client.force_login(self.user)

    def points(self):
        return Profile.objects.get(user=self.user).points

    def answer(self, text):
        return self.client.post(reverse('community:answer_create', args=[self.question.id]),
                                {'content': text}, HTTP_USER_AGENT=UA, follow=True)

    def test_daily_cap_then_no_more_points(self):
        for i in range(ANSWER_DAILY_CAP // ANSWER_POINTS):
            self.answer(f'답변 {i}')
        self.assertEqual(self.points(), ANSWER_DAILY_CAP)
        response = self.answer('여섯 번째 답변')
        self.assertEqual(self.points(), ANSWER_DAILY_CAP)
        self.assertContains(response, '모두 받았어요')
        self.assertEqual(Answer.objects.filter(author=self.user).count(), 6)

    def test_deleting_an_unpaid_answer_does_not_deduct(self):
        for i in range(6):
            self.answer(f'답변 {i}')
        last = Answer.objects.filter(author=self.user).order_by('-id').first()
        self.client.get(reverse('community:answer_delete', args=[last.id]), HTTP_USER_AGENT=UA)
        self.assertEqual(self.points(), ANSWER_DAILY_CAP)
        first = Answer.objects.filter(author=self.user).order_by('id').first()
        self.client.get(reverse('community:answer_delete', args=[first.id]), HTTP_USER_AGENT=UA)
        self.assertEqual(self.points(), ANSWER_DAILY_CAP - ANSWER_POINTS)

    def test_delete_and_repost_does_not_reopen_the_quota(self):
        for i in range(5):
            self.answer(f'답변 {i}')
        first = Answer.objects.filter(author=self.user).order_by('id').first()
        self.client.get(reverse('community:answer_delete', args=[first.id]), HTTP_USER_AGENT=UA)
        self.answer('다시 쓴 답변')
        self.assertEqual(self.points(), ANSWER_DAILY_CAP - ANSWER_POINTS)

    def test_yesterday_awards_do_not_count_and_legacy_answers_refund_twenty(self):
        old = Answer.objects.create(author=self.user, question=self.question, content='예전 답변',
                                    create_date=timezone.now() - timedelta(days=30))
        PointHistory.objects.create(user=self.user, amount=100, reason=PointHistory.REASON_ADMIN,
                                    description='댓글 작성: 어제 몰아 쓴 답변')
        PointHistory.objects.filter(user=self.user).update(created_at=timezone.now() - timedelta(days=1))
        Profile.objects.filter(user=self.user).update(points=100)
        self.answer('오늘 첫 답변')
        self.assertEqual(self.points(), 120)
        self.client.get(reverse('community:answer_delete', args=[old.id]), HTTP_USER_AGENT=UA)
        self.assertEqual(self.points(), 100)
