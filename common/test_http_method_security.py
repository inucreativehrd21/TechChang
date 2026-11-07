"""State-changing account actions must reject cross-site GET probes."""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from common.models import DailyCheckIn, Emoticon, Profile, UserEmoticon


class AccountMethodSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('method-target', password='test-password')
        self.client.force_login(self.user)
        self.profile = Profile.objects.get(user=self.user)
        self.profile.points = 30
        self.profile.is_email_verified = True
        self.profile.save(update_fields=['points', 'is_email_verified'])
        self.emoticon = Emoticon.objects.create(name='test', image='emoticons/test.png', price=10)

    def test_get_cannot_award_checkin_points(self):
        response = self.client.get(reverse('common:daily_checkin'))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(DailyCheckIn.objects.filter(user=self.user).exists())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.points, 30)

    def test_get_cannot_spend_points(self):
        response = self.client.get(reverse('common:purchase_emoticon', args=[self.emoticon.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(UserEmoticon.objects.filter(user=self.user, emoticon=self.emoticon).exists())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.points, 30)

    def test_get_cannot_change_selected_emoticon(self):
        UserEmoticon.objects.create(user=self.user, emoticon=self.emoticon)
        response = self.client.get(reverse('common:select_emoticon', args=[self.emoticon.pk]))
        self.assertEqual(response.status_code, 405)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.selected_emoticon)

    def test_get_cannot_end_session(self):
        response = self.client.get(reverse('common:logout'))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.user.pk))

    def test_post_still_allows_checkin(self):
        response = self.client.post(reverse('common:daily_checkin'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DailyCheckIn.objects.filter(user=self.user).exists())

    def test_post_still_allows_purchase(self):
        response = self.client.post(reverse('common:purchase_emoticon', args=[self.emoticon.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(UserEmoticon.objects.filter(user=self.user, emoticon=self.emoticon).exists())

    def test_post_without_csrf_cannot_change_account(self):
        attacker = Client(enforce_csrf_checks=True)
        attacker.force_login(self.user)
        for route in (
            reverse('common:daily_checkin'),
            reverse('common:purchase_emoticon', args=[self.emoticon.pk]),
            reverse('common:logout'),
        ):
            with self.subTest(route=route):
                self.assertEqual(attacker.post(route).status_code, 403)
        self.assertFalse(DailyCheckIn.objects.filter(user=self.user).exists())
        self.assertFalse(UserEmoticon.objects.filter(user=self.user).exists())
        self.assertEqual(attacker.session.get('_auth_user_id'), str(self.user.pk))
