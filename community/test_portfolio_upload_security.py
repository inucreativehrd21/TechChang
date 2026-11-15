"""대용량 원본 수용과 자원·권한·응답 격리의 경계를 검증해요."""
from datetime import timedelta
from pathlib import Path
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from community.models import PortfolioCollection, PortfolioUploadBudget
from community.portfolio_security import MAX_HTML_BYTES, MAX_REQUEST_BYTES, with_html_summary

UA = 'Mozilla/5.0 Windows Chrome/130'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PortfolioUploadSecurityTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(PORTFOLIO_HTML_BACKUP_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = User.objects.create_user('html-member')
        self.user.profile.is_email_verified = True
        self.user.profile.save(update_fields=['is_email_verified'])
        self.collection = PortfolioCollection.objects.create(
            user=self.user, portfolio_name='Portfolio', slug='html-test', display_name='회원',
            content_mode='html', html_content='<html>BEFORE</html>', is_published=True, approval_status='approved',
        )
        self.url = reverse('community:portfolio_collection_edit', args=[self.collection.slug])
        self.client.force_login(self.user)

    def upload(self, content, filename='portfolio.html', **extra):
        return self.client.post(self.url, {'content_mode':'html', 'html_file':SimpleUploadedFile(filename, content)},
                                HTTP_USER_AGENT=UA, **extra)

    def test_twenty_mib_boundary_preserves_content_and_requires_approval(self):
        content = b'<!doctype html>' + b' ' * (MAX_HTML_BYTES - 15)
        self.assertEqual(len(content), MAX_HTML_BYTES)
        response = self.upload(content)
        self.assertEqual(response.status_code, 302)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.html_content.encode(), content)
        self.assertEqual((self.collection.approval_status, self.collection.is_published), ('draft', False))
        self.assertEqual((Path(self.directory.name) / f'{self.collection.pk}.html').read_text(), '<html>BEFORE</html>')

    def test_one_byte_over_boundary_is_rejected_before_storage(self):
        self.assertEqual(self.upload(b'x' * (MAX_HTML_BYTES + 1)).status_code, 413)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.html_content, '<html>BEFORE</html>')
        self.assertTrue(self.collection.is_published)

    def test_request_limit_is_checked_before_parsing_files(self):
        response = self.client.generic('POST', self.url, b'', content_type='application/octet-stream',
                                       CONTENT_LENGTH=str(MAX_REQUEST_BYTES + 1), HTTP_USER_AGENT=UA)
        self.assertEqual(response.status_code, 413)
        self.assertFalse(PortfolioUploadBudget.objects.exists())

    def test_invalid_utf8_and_wrong_extension_keep_original(self):
        for content, name in ((b'\xff\xfe', 'invalid.html'), (b'<html>NEW</html>', 'attack.exe')):
            self.assertEqual(self.upload(content, name).status_code, 302)
            self.collection.refresh_from_db()
            self.assertEqual(self.collection.html_content, '<html>BEFORE</html>')

    def test_account_quota_counts_utf8_bytes(self):
        for n in range(2):
            PortfolioCollection.objects.create(user=self.user, portfolio_name=f'other-{n}', slug=f'quota-{n}',
                                               html_content='가' * (6 * 1024 * 1024))
        self.assertEqual(self.upload(b'x' * (15 * 1024 * 1024)).status_code, 302)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.html_content, '<html>BEFORE</html>')

    def test_rate_budget_is_shared_in_database_and_expires(self):
        PortfolioUploadBudget.objects.create(user=self.user, window_start=timezone.now(), requests=10)
        self.assertEqual(self.upload(b'<html>new</html>').status_code, 429)
        PortfolioUploadBudget.objects.filter(user=self.user).update(window_start=timezone.now()-timedelta(minutes=11))
        self.assertEqual(self.upload(b'<html>new</html>').status_code, 302)

    def test_other_member_and_anonymous_cannot_upload(self):
        other = User.objects.create_user('other')
        other.profile.is_email_verified = True
        other.profile.save(update_fields=['is_email_verified'])
        self.client.force_login(other)
        self.assertEqual(self.upload(b'<html>attack</html>').status_code, 404)
        self.client.logout()
        self.assertEqual(self.upload(b'<html>attack</html>').status_code, 302)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.html_content, '<html>BEFORE</html>')

    def test_csrf_still_required_for_large_uploads(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(self.url, {'content_mode':'html', 'html_file':SimpleUploadedFile('test.html', b'new')}, HTTP_USER_AGENT=UA)
        self.assertEqual(response.status_code, 403)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.html_content, '<html>BEFORE</html>')

    def test_direct_raw_has_enforced_sandbox_and_narrow_resource_policy(self):
        raw = self.client.get(reverse('community:portfolio_collection_raw', args=[self.collection.slug]), HTTP_USER_AGENT=UA)
        self.assertEqual(raw.status_code, 200)
        directives = dict(part.strip().split(' ', 1) for part in raw['Content-Security-Policy'].split(';') if part.strip())
        self.assertEqual(directives['sandbox'], 'allow-scripts')
        self.assertNotIn('allow-same-origin', raw['Content-Security-Policy'])
        self.assertNotIn('https:', directives['img-src'])
        self.assertEqual(directives['connect-src'], "'none'")
        self.assertEqual(directives['worker-src'], "'none'")
        self.assertNotIn('Content-Security-Policy-Report-Only', raw)
        self.assertEqual(raw['Cache-Control'], 'private, no-store')

    def test_source_is_text_attachment_only_for_owner_or_staff(self):
        url = reverse('community:portfolio_collection_source', args=[self.collection.slug])
        r = self.client.get(url, HTTP_USER_AGENT=UA)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('text/plain'))
        self.assertIn('.txt', r['Content-Disposition'])
        self.assertIn('attachment', r['Content-Disposition'])
        other = User.objects.create_user('outsider')
        other.profile.is_email_verified = True
        other.profile.save(update_fields=['is_email_verified'])
        self.client.force_login(other)
        self.assertEqual(self.client.get(url, HTTP_USER_AGENT=UA).status_code, 403)

    def test_large_source_not_embedded_in_editor_or_member_listing(self):
        marker = 'LARGE_SOURCE_MARKER'
        PortfolioCollection.objects.filter(pk=self.collection.pk).update(html_content=marker + 'x'*1024*1024)
        summary = with_html_summary(PortfolioCollection.objects.all(), editor=True).get(pk=self.collection.pk)
        self.assertIn('html_content', summary.get_deferred_fields())
        self.assertEqual(summary.html_editor, '')
        for url in (self.url, '/members/', '/portfolios/'):
            response = self.client.get(url, HTTP_USER_AGENT=UA)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, marker)
            self.assertLess(len(response.content), 250000)

    def test_empty_editor_keeps_large_source(self):
        content = '<html>' + 'x'*1024*1024 + '</html>'
        PortfolioCollection.objects.filter(pk=self.collection.pk).update(html_content=content)
        self.client.post(self.url, {'content_mode':'html', 'html_content':''}, HTTP_USER_AGENT=UA)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.html_content, content)

    def test_backup_replaces_one_previous_version_instead_of_growing(self):
        self.upload(b'<html>SECOND</html>')
        self.upload(b'<html>THIRD</html>')
        files = list(Path(self.directory.name).glob('*.html'))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_text(), '<html>SECOND</html>')

    def test_admin_review_contains_only_escaped_bounded_preview(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        source = '<script>window.UNTRUSTED_MARKER=1</script>' + 'x'*1024*1024
        PortfolioCollection.objects.filter(pk=self.collection.pk).update(html_content=source, approval_status='pending')
        response = self.client.get(reverse('common:admin_portfolio_approval'), HTTP_USER_AGENT=UA)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '&lt;script&gt;window.UNTRUSTED_MARKER')
        self.assertNotContains(response, '<script>window.UNTRUSTED_MARKER')
        self.assertContains(response, '/portfolios/html-test/source/')
        self.assertLess(len(response.content), 200000)
