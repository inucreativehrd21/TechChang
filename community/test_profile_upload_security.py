"""A crafted profile upload must never become executable same-origin HTML."""

import tempfile
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image


class ProfileUploadSecurityTests(TestCase):
    def test_legacy_profile_endpoint_rejects_html_disguised_as_image(self):
        user = User.objects.create_user('upload-target', password='test-password')
        user.profile.is_email_verified = True
        user.profile.save(update_fields=['is_email_verified'])
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse('community:profile_update'), {
                'nickname': 'reader',
                'profile_image': SimpleUploadedFile(
                    'attack.html', b'<script>window.attack=1</script>', content_type='image/png'
                ),
            })
            user.profile.refresh_from_db()
            self.assertEqual(response.status_code, 400)
            self.assertFalse(user.profile.profile_image)

    def test_valid_profile_image_still_uploads(self):
        user = User.objects.create_user('valid-uploader', password='test-password')
        user.profile.is_email_verified = True
        user.profile.save(update_fields=['is_email_verified'])
        self.client.force_login(user)
        image = BytesIO()
        Image.new('RGB', (2, 2), 'white').save(image, format='PNG')

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse('community:profile_update'), {
                'nickname': 'reader',
                'profile_image': SimpleUploadedFile('avatar.png', image.getvalue(), content_type='image/png'),
            })
            user.profile.refresh_from_db()
            self.assertEqual(response.status_code, 302)
            self.assertEqual(user.profile.nickname, 'reader')
            self.assertTrue(user.profile.profile_image.name.endswith('.png'))
