"""칼럼 끝 한 줄 반응 카드 — 연구팀 칼럼에만, 로그인하면 한 줄(댓글)·추천, 아니면 로그인 안내."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import Answer, Category, Question

UA_PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'
UA_MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'
BODY = '칼럼 본문입니다. ' * 80


class TakeawayCardTests(TestCase):
    def setUp(self):
        bot = User.objects.create_user(Question.BOT_USERNAME, password='x')
        self.member = User.objects.create_user('reader', password='x')
        self.member.profile.is_email_verified = True          # 이메일 인증을 마친 일반 회원
        self.member.profile.save()
        cat = Category.objects.create(name='HRD')
        with mock.patch('office.signals.transaction.on_commit'):
            self.col = Question.objects.create(author=bot, category=cat, subject='칼럼', content=BODY,
                                               create_date=timezone.now())
        self.post = Question.objects.create(author=self.member, category=cat, subject='질문', content=BODY,
                                            create_date=timezone.now())

    def get(self, q, ua=UA_PC):
        r = self.client.get(reverse("community:detail", args=[q.id]), HTTP_USER_AGENT=ua)
        assert r.status_code == 200, (r.status_code, r.get("Location"))
        return r.content.decode()

    def test_only_lab_columns_get_the_card(self):
        self.assertIn('오늘 글에서 하나 가져간다면?', self.get(self.col))
        self.assertNotIn('오늘 글에서 하나 가져간다면?', self.get(self.post))

    def test_anonymous_reader_is_sent_to_login_and_back(self):
        html = self.get(self.col)
        self.assertIn('로그인하고 한 줄 남기기', html)
        self.assertNotIn('id="tc-tk-input"', html)

    def test_logged_in_reader_leaves_a_line_as_a_comment(self):
        self.client.login(username='reader', password='x')
        for ua in (UA_PC, UA_MOBILE):
            html = self.get(self.col, ua)
            self.assertIn('id="tc-tk-input"', html)
            self.assertIn(reverse('community:answer_create', args=[self.col.id]), html)
            self.assertIn(reverse('community:question_vote', args=[self.col.id]), html)
        self.client.post(reverse('community:answer_create', args=[self.col.id]),
                         {'content': '비교 집단 없이 전후만 재면 효과가 부풀려 보인다'}, HTTP_USER_AGENT=UA_PC)
        self.assertTrue(Answer.objects.filter(question=self.col, author=self.member).exists())
