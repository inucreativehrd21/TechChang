"""운영자 픽 — 관리자(superuser)만 지정·해제하고, 지정된 글은 카드가 짙은 인디고로 돋보인다."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import Category, Question

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'


def verified(user):
    profile = getattr(user, 'profile', None)
    if profile is not None:
        profile.is_email_verified = True
        profile.save()
    return user


class OperatorPickTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = verified(User.objects.create_superuser('admin', 'a@example.com', 'x'))
        self.member = verified(User.objects.create_user('member', password='x'))
        cat, _ = Category.objects.get_or_create(name='자유')
        self.q = Question.objects.create(author=self.member, category=cat, subject='운영자가 고를 글',
                                         content='본문입니다. ' * 30, create_date=timezone.now())
        self.url = reverse('community:question_operator_pick', args=[self.q.id])

    def test_only_superuser_can_toggle_and_only_by_post(self):
        self.client.force_login(self.member)
        self.client.post(self.url, HTTP_USER_AGENT=PC)
        self.q.refresh_from_db()
        self.assertFalse(self.q.operator_pick)

        self.client.force_login(self.admin)
        self.client.get(self.url, HTTP_USER_AGENT=PC)              # GET 으로는 바뀌지 않는다
        self.q.refresh_from_db()
        self.assertFalse(self.q.operator_pick)

        self.client.post(self.url, HTTP_USER_AGENT=PC)
        self.q.refresh_from_db()
        self.assertTrue(self.q.operator_pick)
        self.assertIsNotNone(self.q.operator_pick_at)
        self.client.post(self.url, HTTP_USER_AGENT=PC)
        self.q.refresh_from_db()
        self.assertFalse(self.q.operator_pick)
        self.assertIsNone(self.q.operator_pick_at)

    def test_cards_stand_out_on_home_and_board(self):
        self.q.operator_pick = True
        self.q.save()
        home = self.client.get('/', HTTP_USER_AGENT=PC).content.decode()
        self.assertIn('is-op-pick', home)
        self.assertIn('class="tc-op-pick"', home)
        board = self.client.get(reverse('community:board_main'), HTTP_USER_AGENT=PC).content.decode()
        self.assertIn('is-op-pick', board)
        mobile = self.client.get('/', HTTP_USER_AGENT=MOBILE).content.decode()
        self.assertIn('is-op-pick', mobile)
        self.assertIn('class="tc-m-op-pick"', mobile)

    def test_detail_badge_for_all_and_button_for_admin_only(self):
        self.q.operator_pick = True
        self.q.save()
        detail = f'/{self.q.id}/'
        for ua in (PC, MOBILE):
            anon = self.client.get(detail, HTTP_USER_AGENT=ua).content.decode()
            self.assertIn('class="tc-op-badge"', anon)
            self.assertNotIn(self.url, anon)
        self.client.force_login(self.member)
        self.assertNotIn(self.url, self.client.get(detail, HTTP_USER_AGENT=PC).content.decode())
        self.client.force_login(self.admin)
        for ua in (PC, MOBILE):
            page = self.client.get(detail, HTTP_USER_AGENT=ua).content.decode()
            self.assertIn(self.url, page)
            self.assertIn('운영자 픽 해제', page)
