from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseForbidden
from django.utils import timezone
from django.db import models
from django.db.models import F, Max
import json

from ..models import Portfolio, Project


def members_list(request):
    """
    구성원 목록 - 포트폴리오를 공개한 사용자들
    """
    # is_public=True인 포트폴리오만 가져오기
    public_portfolios = Portfolio.objects.filter(
        is_public=True
    ).select_related('user').order_by('-modify_date')

    context = {
        'portfolios': public_portfolios,
    }

    return render(request, 'community/members_list.html', context)


def portfolio_view(request, user_id):
    """
    포트폴리오 보기

    Args:
        user_id: 사용자 ID
    """
    user = get_object_or_404(User, pk=user_id)

    # 포트폴리오 가져오기 (없으면 생성)
    portfolio, created = Portfolio.objects.get_or_create(user=user)

    # 비공개 포트폴리오는 본인만 볼 수 있음
    if not portfolio.is_public and request.user != user:
        return HttpResponseForbidden("이 포트폴리오는 비공개입니다.")

    # 조회수 증가 (본인 제외)
    if request.user != user:
        Portfolio.objects.filter(pk=portfolio.pk).update(view_count=F('view_count') + 1)
        portfolio.refresh_from_db()

    # 프로젝트 목록 (순서대로)
    projects = portfolio.projects.all()

    context = {
        'portfolio': portfolio,
        'projects': projects,
        'is_owner': request.user == user,
    }

    return render(request, 'community/portfolio_view.html', context)


@login_required
def portfolio_edit(request):
    """
    포트폴리오 편집
    """
    # 포트폴리오 가져오기 (없으면 생성)
    portfolio, created = Portfolio.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        # 포트폴리오 정보 업데이트
        portfolio.display_name = request.POST.get('display_name', '')
        portfolio.title = request.POST.get('title', '')
        portfolio.bio = request.POST.get('bio', '')
        portfolio.location = request.POST.get('location', '')
        portfolio.email = request.POST.get('email', '')
        portfolio.github_url = request.POST.get('github_url', '')
        portfolio.linkedin_url = request.POST.get('linkedin_url', '')
        portfolio.website_url = request.POST.get('website_url', '')
        portfolio.is_public = request.POST.get('is_public') == 'on'
        portfolio.theme = request.POST.get('theme', 'light')

        # 배경 그라데이션
        portfolio.hero_gradient = request.POST.get('hero_gradient', portfolio.hero_gradient)
        portfolio.skills_gradient = request.POST.get('skills_gradient', portfolio.skills_gradient)

        # 기술 스택 (쉼표로 구분된 문자열을 리스트로 변환)
        skills_str = request.POST.get('skills', '')
        if skills_str:
            portfolio.skills = [s.strip() for s in skills_str.split(',') if s.strip()]
        else:
            portfolio.skills = []

        # 프로필 이미지
        if 'profile_image' in request.FILES:
            portfolio.profile_image = request.FILES['profile_image']

        portfolio.save()

        return redirect('community:portfolio_view', user_id=request.user.id)

    # 기술 스택을 쉼표로 구분된 문자열로 변환
    skills_str = ', '.join(portfolio.skills) if portfolio.skills else ''

    context = {
        'portfolio': portfolio,
        'skills_str': skills_str,
    }

    return render(request, 'community/portfolio_edit.html', context)


@login_required
def project_create(request):
    """
    프로젝트 생성
    """
    # 포트폴리오 가져오기 (없으면 생성)
    portfolio, created = Portfolio.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        # 프로젝트 생성
        project = Project()
        project.portfolio = portfolio
        project.title = request.POST.get('title', '')
        project.description = request.POST.get('description', '')
        project.project_type = request.POST.get('project_type', 'dev')
        project.project_url = request.POST.get('project_url', '')
        project.github_url = request.POST.get('github_url', '')
        project.is_featured = request.POST.get('is_featured') == 'on'

        # 배경 그라데이션
        project.background_gradient = request.POST.get('background_gradient', 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)')

        # 기술 스택
        tech_stack_str = request.POST.get('tech_stack', '')
        if tech_stack_str:
            project.tech_stack = [s.strip() for s in tech_stack_str.split(',') if s.strip()]
        else:
            project.tech_stack = []

        # 날짜
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        if start_date:
            project.start_date = start_date
        if end_date:
            project.end_date = end_date

        # 이미지
        if 'image' in request.FILES:
            project.image = request.FILES['image']

        # 순서 (마지막에 추가)
        max_order = portfolio.projects.aggregate(max_order=Max('order'))['max_order'] or 0
        project.order = max_order + 1

        project.save()

        return redirect('community:portfolio_view', user_id=request.user.id)

    return render(request, 'community/project_create.html', {'portfolio': portfolio})


@login_required
def project_edit(request, project_id):
    """
    프로젝트 편집
    """
    project = get_object_or_404(Project, pk=project_id)

    # 본인 프로젝트만 수정 가능
    if project.portfolio.user != request.user:
        return HttpResponseForbidden("본인의 프로젝트만 수정할 수 있습니다.")

    if request.method == 'POST':
        project.title = request.POST.get('title', '')
        project.description = request.POST.get('description', '')
        project.project_type = request.POST.get('project_type', 'dev')
        project.project_url = request.POST.get('project_url', '')
        project.github_url = request.POST.get('github_url', '')
        project.is_featured = request.POST.get('is_featured') == 'on'

        # 배경 그라데이션
        project.background_gradient = request.POST.get('background_gradient', project.background_gradient)

        # 기술 스택
        tech_stack_str = request.POST.get('tech_stack', '')
        if tech_stack_str:
            project.tech_stack = [s.strip() for s in tech_stack_str.split(',') if s.strip()]
        else:
            project.tech_stack = []

        # 날짜
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        if start_date:
            project.start_date = start_date
        else:
            project.start_date = None
        if end_date:
            project.end_date = end_date
        else:
            project.end_date = None

        # 이미지
        if 'image' in request.FILES:
            project.image = request.FILES['image']

        project.save()

        return redirect('community:portfolio_view', user_id=request.user.id)

    # 기술 스택을 쉼표로 구분된 문자열로 변환
    tech_stack_str = ', '.join(project.tech_stack) if project.tech_stack else ''

    context = {
        'project': project,
        'tech_stack_str': tech_stack_str,
    }

    return render(request, 'community/project_edit.html', context)


@login_required
def project_delete(request, project_id):
    """
    프로젝트 삭제
    """
    project = get_object_or_404(Project, pk=project_id)

    # 본인 프로젝트만 삭제 가능
    if project.portfolio.user != request.user:
        return HttpResponseForbidden("본인의 프로젝트만 삭제할 수 있습니다.")

    if request.method == 'POST':
        project.delete()
        return redirect('community:portfolio_view', user_id=request.user.id)

    return render(request, 'community/project_delete.html', {'project': project})


@login_required
def project_reorder(request):
    """
    프로젝트 순서 변경 (AJAX)
    """
    if request.method == 'POST':
        import json
        from django.db import models

        data = json.loads(request.body)
        project_orders = data.get('orders', [])

        for item in project_orders:
            project_id = item.get('id')
            order = item.get('order')

            try:
                project = Project.objects.get(pk=project_id, portfolio__user=request.user)
                project.order = order
                project.save()
            except Project.DoesNotExist:
                pass

        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})
