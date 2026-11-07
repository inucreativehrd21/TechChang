from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (Answer, Category, CollectionProject, Comment, Portfolio,
                     PortfolioAsset, PortfolioCollection, Project, Question)


class MediaAuthorizationTests(TestCase):
    def setUp(self):
        self.client.defaults['HTTP_USER_AGENT'] = 'Mozilla/5.0'
        self.owner = User.objects.create_user('media_owner', password='test-password')
        self.other = User.objects.create_user('media_other', password='test-password')
        for user in (self.owner, self.other):
            user.profile.is_email_verified = True
            user.profile.save(update_fields=['is_email_verified'])
        self.category = Category.objects.create(name='문의')
        self.question = Question.objects.create(
            author=self.owner, category=self.category, subject='비공개 문의',
            content='본문', create_date=timezone.now(),
            file='question_files/private.pdf', image='questions/private.png',
        )
        self.collection = PortfolioCollection.objects.create(
            user=self.owner, portfolio_name='비공개 포트폴리오', slug='private-media',
            approval_status='draft', is_published=False,
        )
        self.asset = PortfolioAsset.objects.create(
            collection=self.collection, image='portfolio/html_assets/private.png',
            original_name='private.png',
        )

    def auth(self, path):
        return self.client.get('/media/_authorize/', HTTP_X_ORIGINAL_URI=path)

    def test_private_question_and_portfolio_media_require_owner(self):
        for path in ('/media/question_files/private.pdf',
                     '/media/questions/private.png',
                     '/media/portfolio/html_assets/private.png'):
            with self.subTest(path=path):
                self.assertEqual(self.auth(path).status_code, 403)
                self.client.force_login(self.owner)
                self.assertEqual(self.auth(path).status_code, 204)
                self.client.force_login(self.other)
                self.assertEqual(self.auth(path).status_code, 403)
                self.client.logout()

    def test_public_media_and_unknown_files(self):
        self.question.category.name = '자유'
        self.question.category.save(update_fields=['name'])
        self.collection.approval_status = 'approved'
        self.collection.is_published = True
        self.collection.save(update_fields=['approval_status', 'is_published'])
        self.assertEqual(self.auth('/media/question_files/private.pdf').status_code, 204)
        self.assertEqual(self.auth('/media/portfolio/html_assets/private.png').status_code, 204)
        self.assertEqual(self.auth('/media/portfolio/html_assets/untracked.png').status_code, 403)
        self.assertEqual(self.auth('/media/portfolio/html_assets/private.html').status_code, 403)
        self.assertEqual(self.auth('/media/portfolio/../html_assets/private.png').status_code, 403)

    def test_related_images_follow_parent_visibility(self):
        Answer.objects.create(
            author=self.owner, question=self.question, content='답변',
            create_date=timezone.now(), image='answers/private.png',
        )
        Comment.objects.create(
            author=self.owner, question=self.question, content='댓글',
            create_date=timezone.now(), image='comments/private.png',
        )
        legacy = Portfolio.objects.create(
            user=self.owner, approval_status='draft', is_public=False,
            profile_image='portfolio/profiles/private.png',
        )
        Project.objects.create(
            portfolio=legacy, title='프로젝트', description='설명',
            image='portfolio/projects/private.png',
        )
        CollectionProject.objects.create(
            portfolio_collection=self.collection, title='컬렉션 프로젝트',
            description='설명', image='portfolio/projects/collection-private.png',
        )
        paths = ('/media/answers/private.png', '/media/comments/private.png',
                 '/media/portfolio/profiles/private.png',
                 '/media/portfolio/projects/private.png',
                 '/media/portfolio/projects/collection-private.png')
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.auth(path).status_code, 403)
                self.client.force_login(self.owner)
                self.assertEqual(self.auth(path).status_code, 204)
                self.client.logout()

    def test_invalid_portfolio_upload_is_rejected_before_save(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('community:portfolio_collection_edit', args=[self.collection.slug]),
            {'profile_image': SimpleUploadedFile('attack.html', b'<script>alert(1)</script>',
                                                  content_type='text/html')},
        )
        self.assertEqual(response.status_code, 400)
        self.collection.refresh_from_db()
        self.assertFalse(self.collection.profile_image)

    def test_vote_get_cannot_change_state(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('community:question_vote', args=[self.question.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(self.question.voter.filter(pk=self.other.pk).exists())
