from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Question, PortfolioCollection


class StaticViewSitemap(Sitemap):
    """정적/주요 공개 페이지 (홈, 커뮤니티, 게임, 구성원, 랭킹, 방명록)"""
    protocol = 'https'

    # (URL name, priority, changefreq) — 홈을 최상위 우선순위로
    PAGES = [
        ('community:index',          1.0, 'daily'),
        ('community:board_main',     0.9, 'daily'),
        ('community:games_index',    0.7, 'weekly'),
        ('community:members_list',   0.7, 'weekly'),
        ('common:point_ranking',     0.6, 'weekly'),
        ('community:guestbook_list', 0.5, 'weekly'),
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
    """질문/답변 게시글"""
    protocol = 'https'
    changefreq = 'daily'
    priority = 0.7

    def items(self):
        return Question.objects.filter(
            is_deleted=False
        ).order_by('-create_date').select_related('author')[:500]

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
