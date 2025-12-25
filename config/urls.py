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
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from community.views import base_views

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
    path('accounts/', include('allauth.urls')),  # django-allauth URLs
]

# 개발 환경에서 미디어 파일 서빙
if settings.DEBUG:
    # 개발 환경에서만 미디어 파일을 Django로 서빙
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

