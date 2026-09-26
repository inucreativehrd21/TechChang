from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Question, PortfolioCollection


class StaticViewSitemap(Sitemap):
    """정적/주요 공개 페이지 (홈, 커뮤니티, 게임, 구성원, 랭킹)

    로그인이 필요한 페이지는 넣지 않는다 — 크롤러에게는 robots.txt 가 막아 둔
    로그인 페이지로 리다이렉트되는 막다른 길이라, 색인은 안 되고 크롤링 예산만 쓴다.
    (방명록 guestbook_list 는 @login_required 라 2026-09-26 에 제외)
    """
    protocol = 'https'

    # (URL name, priority, changefreq) — 홈을 최상위 우선순위로
    PAGES = [
        ('community:index',          1.0, 'daily'),
        ('community:board_main',     0.9, 'daily'),
        ('community:games_index',    0.7, 'weekly'),
        ('community:members_list',   0.7, 'weekly'),
        ('common:point_ranking',     0.6, 'weekly'),
        ('sitemap_page',             0.4, 'daily'),   # 사람이 보는 사이트맵 = 내부링크 허브
    ]

    def items(self):
        return self.PAGES

    def location(self, item):
        return reverse(item[0])

    def priority(self, item):
        return item[1]

    def changefreq(self, item):
        return item[2]


class QuestionSitemap(Sitemap):
    """질문/답변 게시글 — 비로그인 방문자가 실제로 읽을 수 있는 글만"""
    protocol = 'https'
    changefreq = 'daily'
    priority = 0.7

    # community.views.base_views.detail 이 비로그인 사용자를 돌려보내는 조건과 짝을 이룬다.
    # 여기 조건을 바꾸면 detail 쪽도 함께 봐야 한다.
    RESTRICTED_CATEGORIES = ('문의',)

    def items(self):
        return Question.objects.filter(
            is_deleted=False,
            is_locked=False,                       # 회원 전용 글 → 로그인 페이지로 302
        ).exclude(
            category__name__in=self.RESTRICTED_CATEGORIES,   # 문의글 → 홈으로 302
        ).order_by('-create_date').select_related('author', 'category')[:500]

    def lastmod(self, obj):
        return obj.modify_date or obj.create_date

    def location(self, obj):
        return reverse('community:detail', kwargs={'question_id': obj.id})


class PortfolioCollectionSitemap(Sitemap):
    """공개 포트폴리오 (slug 기반)"""
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return PortfolioCollection.objects.filter(
            is_published=True, approval_status='approved'
        ).select_related('user').order_by('-modify_date')

    def lastmod(self, obj):
        return obj.modify_date

    def location(self, obj):
        return reverse('community:portfolio_collection_detail', kwargs={'slug': obj.slug})
