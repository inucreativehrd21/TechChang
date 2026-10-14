"""커피챗 제안 — HTML 포트폴리오(샌드박스 iframe)의 버튼 → 부모 페이지 폼 → 포트폴리오 주인 이메일로 전달."""
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from community.models import PortfolioCollection

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
HTML = ('<!DOCTYPE html><html><body><h1>포트폴리오</h1>'
        '<a class="cta" href="#coffee-chat" data-tc-coffee-chat>☕ 커피챗 제안하기</a></body></html>')
GOOD = {'name': '김채용', 'org': '테스트컴퍼니', 'email': 'recruiter@example.com',
        'message': '안녕하세요, 포트폴리오 잘 봤습니다. 다음 주에 30분 정도 이야기 나눌 수 있을까요?'}


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   DEFAULT_FROM_EMAIL='noreply@techchang.com')
class CoffeeChatTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('owner', email='owner@placeholder.com', password='x')
        self.pf = PortfolioCollection.objects.create(
            user=self.owner, portfolio_name='main', slug='owner-main', display_name='문승현',
            content_mode='html', html_content=HTML, email='owner.real@example.com',
            is_published=True, approval_status='approved')
        self.url = reverse('community:portfolio_coffee_chat', args=[self.pf.slug])

    def post(self, data=None, **extra):
        return self.client.post(self.url, data or GOOD, HTTP_USER_AGENT=PC, **extra)

    def test_message_goes_to_portfolio_email_with_reply_to_sender(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ['owner.real@example.com'])          # 계정 자리표시자 주소가 아니라 포트폴리오 연락 이메일
        self.assertEqual(m.reply_to, ['recruiter@example.com'])
        self.assertIn('김채용', m.subject)
        self.assertIn('30분 정도 이야기', m.body)
        self.assertIn('테스트컴퍼니', m.body)

    def test_falls_back_to_account_email(self):
        PortfolioCollection.objects.filter(pk=self.pf.pk).update(email='')
        self.post()
        self.assertEqual(mail.outbox[0].to, ['owner@placeholder.com'])

    def test_validation_errors(self):
        r = self.post({'name': '', 'email': 'not-an-email', 'message': '짧음'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.json()['errors']), {'name', 'email', 'message'})
        self.assertEqual(len(mail.outbox), 0)

    def test_honeypot_is_silently_dropped(self):
        r = self.post({**GOOD, 'website': 'http://spam.example'})
        self.assertTrue(r.json()['ok'])
        self.assertEqual(len(mail.outbox), 0)

    def test_rate_limited_per_ip(self):
        for _ in range(3):
            self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 429)
        self.assertEqual(len(mail.outbox), 3)

    def test_private_portfolio_and_get_are_refused(self):
        self.assertEqual(self.client.get(self.url, HTTP_USER_AGENT=PC).status_code, 405)
        PortfolioCollection.objects.filter(pk=self.pf.pk).update(is_published=False)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_raw_html_gets_bridge_and_page_gets_form(self):
        raw = self.client.get(reverse('community:portfolio_collection_raw', args=[self.pf.slug]), HTTP_USER_AGENT=PC)
        body = raw.content.decode()
        self.assertIn('tc:coffee-chat', body)
        self.assertLess(body.index('tc:coffee-chat'), body.index('</body>'))
        page = self.client.get(reverse('community:portfolio_collection_detail', args=[self.pf.slug]),
                               HTTP_USER_AGENT=PC).content.decode()
        self.assertIn('id="tc-cc"', page)
        self.assertIn(self.url, page)
        self.assertIn('테크창에는 저장되지 않아요', page)
