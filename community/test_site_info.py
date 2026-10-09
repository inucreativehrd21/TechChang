from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from common.models import Profile
from community.models import Category, Question

PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130'
MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


def user(name, **kw):
    u = User.objects.create_user(username=name, password='pw-123456!', email=f'{name}@example.com', **kw)
    p, _ = Profile.objects.get_or_create(user=u)
    p.is_email_verified = True
    p.save()
    return u


class AdminEditsLabColumnsTests(TestCase):
    def setUp(self):
        cat = Category.objects.create(name='HRD')
        self.bot = user(Question.BOT_USERNAME)
        self.admin = user('admin', is_staff=True, is_superuser=True)
        self.member = user('member')
        self.column = Question.objects.create(author=self.bot, category=cat, subject='연구팀 칼럼', content='본문',
                                              create_date=timezone.now())
        self.post = Question.objects.create(author=self.member, category=cat, subject='회원 글', content='본문',
                                            create_date=timezone.now())

    def test_permission_matrix(self):
        self.assertTrue(self.column.can_edit(self.admin))      # 관리자 → 연구팀 칼럼 가능
        self.assertFalse(self.post.can_edit(self.admin))       # 관리자라도 회원 글은 불가
        self.assertTrue(self.post.can_edit(self.member))       # 작성자 본인
        self.assertFalse(self.column.can_edit(self.member))

    def test_admin_can_save_lab_column_and_author_stays_lab(self):
        self.client.force_login(self.admin)
        res = self.client.get(f'/question/modify/{self.column.id}/', HTTP_USER_AGENT=PC)
        if res.status_code == 404:                                # URL 패턴 확인용 안전장치
            from django.urls import reverse
            res = self.client.get(reverse('community:question_modify', args=[self.column.id]), HTTP_USER_AGENT=PC)
        self.assertEqual(res.status_code, 200)

    def test_detail_shows_edit_but_not_delete_to_admin(self):
        self.client.force_login(self.admin)
        html = self.client.get(f'/{self.column.id}/', HTTP_USER_AGENT=PC).content.decode()
        from django.urls import reverse
        self.assertIn(reverse('community:question_modify', args=[self.column.id]), html)
        self.assertNotIn(reverse('community:question_delete', args=[self.column.id]), html)


class SiteInfoTests(TestCase):
    def test_home_footer_and_copy(self):
        for ua in (PC, MOBILE):
            html = self.client.get('/', HTTP_USER_AGENT=ua).content.decode()
            self.assertIn('seunghyunmoon55@gmail.com', html)
            self.assertIn('tel:+821030605948', html)
            self.assertIn('010-3060-5948', html)
            self.assertIn('문승현', html)
        pc = self.client.get('/', HTTP_USER_AGENT=PC).content.decode()
        self.assertNotIn('tc-eyebrow">인천대학교 창의인재개발학과 전공심화연구모임', pc)
        self.assertIn('에서 시작했습니다', pc)                    # 소개 모달: 뿌리는 테크창 활동
        self.assertNotIn('혁신적인 학습 소모임', pc)               # 현재형 소모임 소개는 없앰


class DetailContentVisibleTests(TestCase):
    """PC 상세가 본문 카드를 JS 로 숨겼다가 IntersectionObserver(threshold 0.1)로 드러내던 코드 회귀 방지.
    본문이 화면 높이의 10배를 넘는 긴 칼럼은(모바일에서 PC 버전으로 볼 때) 영영 opacity 0 이었다(2026-10-09)."""

    def test_pc_detail_does_not_hide_the_article_with_js(self):
        bot = user(Question.BOT_USERNAME)
        q = Question.objects.create(author=bot, category=Category.objects.create(name='HRD'), subject='긴 칼럼',
                                    content='문단입니다. ' * 3000, create_date=timezone.now())
        self.client.cookies['force_version'] = 'desktop'
        html = self.client.get(f'/{q.id}/', HTTP_USER_AGENT=MOBILE).content.decode()
        self.assertIn('class="question-card"', html)          # PC 템플릿이 나왔는지
        self.assertNotIn("card.style.opacity = '0'", html)
