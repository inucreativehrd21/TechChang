"""Recent activity must not reveal answers or comments from protected posts."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import Answer, Category, Comment, Question


class RecentActivityPrivacyTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user('private-author', password='test-password')
        self.other = User.objects.create_user('other-reader', password='test-password')
        self.other.profile.is_email_verified = True
        self.other.profile.save(update_fields=['is_email_verified'])
        self.inquiry, _ = Category.objects.get_or_create(name='문의')
        self.public, _ = Category.objects.get_or_create(name='자유게시판')

        def post(category, subject, *, locked=False, deleted=False):
            return Question.objects.create(
                author=self.author, category=category, subject=subject,
                content='body', create_date=timezone.now(),
                is_locked=locked, is_deleted=deleted,
            )

        self.secret = post(self.inquiry, 'private inquiry')
        self.locked = post(self.public, 'member only', locked=True)
        self.deleted = post(self.public, 'deleted', deleted=True)
        self.open = post(self.public, 'open')
        for question, marker in (
            (self.secret, 'INQUIRY_SECRET_701'),
            (self.locked, 'LOCKED_SECRET_702'),
            (self.deleted, 'DELETED_SECRET_703'),
            (self.open, 'PUBLIC_MARKER_704'),
        ):
            Answer.objects.create(author=self.author, question=question,
                                  content=marker, create_date=timezone.now())
            Comment.objects.create(author=self.author, question=question,
                                   content=marker, create_date=timezone.now())
        secret_answer = Answer.objects.get(question=self.secret)
        Comment.objects.create(author=self.author, answer=secret_answer,
                               content='INQUIRY_REPLY_SECRET_705', create_date=timezone.now())
        removed_answer = Answer.objects.create(
            author=self.author, question=self.open, content='REMOVED_ANSWER_706',
            create_date=timezone.now(), is_deleted=True,
        )
        Comment.objects.create(author=self.author, answer=removed_answer,
                               content='REMOVED_REPLY_707', create_date=timezone.now())

    def _assert_list(self, route, visible, hidden):
        response = self.client.get(reverse(route))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for marker in visible:
            self.assertIn(marker, body)
        for marker in hidden:
            self.assertFalse(marker in body, f'{marker} leaked through {route}')

    def test_anonymous_recent_lists_hide_protected_content(self):
        for route in ('community:recent_answers', 'community:recent_comments'):
            with self.subTest(route=route):
                self._assert_list(route, ['PUBLIC_MARKER_704'],
                                  ['INQUIRY_SECRET_701', 'LOCKED_SECRET_702', 'DELETED_SECRET_703'])

    def test_other_member_cannot_read_inquiry_snippets(self):
        self.client.force_login(self.other)
        for route in ('community:recent_answers', 'community:recent_comments'):
            with self.subTest(route=route):
                self._assert_list(route, ['LOCKED_SECRET_702', 'PUBLIC_MARKER_704'],
                                  ['INQUIRY_SECRET_701', 'DELETED_SECRET_703'])

    def test_answer_attached_comments_follow_parent_visibility(self):
        self._assert_list('community:recent_comments', ['PUBLIC_MARKER_704'],
                          ['INQUIRY_REPLY_SECRET_705', 'REMOVED_REPLY_707'])

    def test_inquiry_author_can_see_their_own_recent_answer(self):
        self.author.profile.is_email_verified = True
        self.author.profile.save(update_fields=['is_email_verified'])
        self.client.force_login(self.author)
        self._assert_list('community:recent_answers', ['INQUIRY_SECRET_701'],
                          ['DELETED_SECRET_703', 'REMOVED_ANSWER_706'])
