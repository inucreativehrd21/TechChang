"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import re_path, include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.contrib.sitemaps.views import index as sitemap_index, sitemap
from community.views import base_views
from community.feeds import ColumnFeed
from community.sitemaps import (StaticViewSitemap, ColumnSitemap, PostSitemap, SeriesSitemap,
                                MakingSitemap, PortfolioCollectionSitemap)

sitemaps = {
    'static': StaticViewSitemap,
    'columns': ColumnSitemap,
    'series': SeriesSitemap,
    'posts': PostSitemap,
    'making': MakingSitemap,
    'portfolios': PortfolioCollectionSitemap,
}

urlpatterns = [
    # 보안: Admin URL을 추측하기 어려운 경로로 변경
    # 환경변수 DJANGO_ADMIN_URL로 커스터마이징 가능 (기본: secret-control-panel/)
    path(
        settings.ADMIN_URL if hasattr(settings, 'ADMIN_URL') else 'secret-control-panel/',
        admin.site.urls
    ),

    # 기존 pybo URL 리다이렉트 (하위 호환성)
    path('pybo/', RedirectView.as_view(url='/', permanent=True)),
    path('pybo/<path:remaining_path>/', RedirectView.as_view(url='/%(remaining_path)s/', permanent=True)),

    path('', include('community.urls')),  # 커뮤니티 메인 (루트 경로)
    path('common/', include('common.urls')),
    path('lab/', include('office.urls')),  # 연구팀 가상 연구실 (office 앱)
    path('accounts/', include('allauth.urls')),  # django-allauth URLs
    # sitemap.xml = 묶음 색인(index). GSC 에서 칼럼·시리즈·회원 글 등 묶음별 색인 비율을 따로 본다.
    path('sitemap.xml', sitemap_index, {'sitemaps': sitemaps, 'sitemap_url_name': 'sitemap_section'},
         name='sitemap_index'),
    path('sitemap-<section>.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap_section'),
    # 사람이 보는 사이트맵. sitemap.xml 에 XSL 을 붙이는 방법도 있지만 Chrome 이 XSLT 를
    # 제거 중이라 경고 배너가 뜨고 곧 깨진다. 별도 HTML 페이지가 내부링크에도 이득이다.
    path('sitemap/', base_views.sitemap_page, name='sitemap_page'),
    path('robots.txt', base_views.robots_txt, name='robots_txt'),
    path('rss.xml', ColumnFeed(), name='rss'),   # 연구팀 칼럼 RSS (네이버 서치어드바이저 제출용)
    re_path(r'^(?P<key>[0-9a-f]{32})\.txt$', base_views.indexnow_key, name='indexnow_key'),
]

# 개발 환경에서 미디어 파일 서빙
if settings.DEBUG:
    # 개발 환경에서만 미디어 파일을 Django로 서빙
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

