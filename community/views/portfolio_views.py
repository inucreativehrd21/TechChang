from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseForbidden
from django.utils import timezone
from django.db import models
from django.db.models import F, Max
import json

from ..models import Portfolio, Project, Experience


def get_background_css(portfolio, section='hero'):
    """
    포트폴리오 배경 타입에 따라 CSS 값 생성

    Args:
        portfolio: Portfolio 인스턴스
        section: 'hero' 또는 'skills'

    Returns:
        CSS background 속성값 (gradient, solid color, 또는 hex color)
    """
    if section == 'hero':
        bg_type = portfolio.hero_background_type
        if bg_type == 'gradient':
            return portfolio.hero_gradient
        elif bg_type == 'solid':
            return portfolio.hero_solid_color if portfolio.hero_solid_color else portfolio.hero_gradient
        elif bg_type == 'white':
            return '#ffffff'
        elif bg_type == 'custom':
            return portfolio.hero_custom_color if portfolio.hero_custom_color else '#667eea'
    else:  # skills
        bg_type = portfolio.skills_background_type
        if bg_type == 'gradient':
            return portfolio.skills_gradient
        elif bg_type == 'solid':
            return portfolio.skills_solid_color if portfolio.skills_solid_color else portfolio.skills_gradient
        elif bg_type == 'white':
            return '#ffffff'
        elif bg_type == 'custom':
            return portfolio.skills_custom_color if portfolio.skills_custom_color else '#f093fb'

    # Fallback
    return portfolio.hero_gradient if section == 'hero' else portfolio.skills_gradient


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

    # 경력 사항 목록 (순서대로)
    experiences = portfolio.experiences.all().order_by('order')

    context = {
        'portfolio': portfolio,
        'projects': projects,
        'experiences': experiences,
        'is_owner': request.user == user,
        'hero_background': get_background_css(portfolio, 'hero'),
        'skills_background': get_background_css(portfolio, 'skills'),
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
        portfolio.show_experience = request.POST.get('show_experience') == 'on'
        portfolio.theme = request.POST.get('theme', 'light')

        # 배경 그라데이션
        portfolio.hero_gradient = request.POST.get('hero_gradient', portfolio.hero_gradient)
        portfolio.skills_gradient = request.POST.get('skills_gradient', portfolio.skills_gradient)

        # 배경 타입 및 커스텀 색상 처리
        # Hero 배경
        hero_bg_type = request.POST.get('hero_background_type', 'gradient')
        portfolio.hero_background_type = hero_bg_type

        if hero_bg_type == 'gradient':
            portfolio.hero_gradient = request.POST.get('hero_gradient', portfolio.hero_gradient)
        elif hero_bg_type == 'solid':
            portfolio.hero_solid_color = request.POST.get('hero_solid_color', '')
        elif hero_bg_type == 'custom':
            portfolio.hero_custom_color = request.POST.get('hero_custom_color', '#667eea')

        # Skills 배경
        skills_bg_type = request.POST.get('skills_background_type', 'gradient')
        portfolio.skills_background_type = skills_bg_type

        if skills_bg_type == 'gradient':
            portfolio.skills_gradient = request.POST.get('skills_gradient', portfolio.skills_gradient)
        elif skills_bg_type == 'solid':
            portfolio.skills_solid_color = request.POST.get('skills_solid_color', '')
        elif skills_bg_type == 'custom':
            portfolio.skills_custom_color = request.POST.get('skills_custom_color', '#f093fb')

        # 스킬 표시 설정 - 활성화된 스킬 타입
        enabled_types = request.POST.getlist('enabled_skill_types')
        portfolio.enabled_skill_types = enabled_types

        # 1. Simple 스킬 (기존 기술 스택)
        if 'simple' in enabled_types:
            skills_str = request.POST.get('skills', '')
            portfolio.skills = [s.strip() for s in skills_str.split(',') if s.strip()] if skills_str else []
        else:
            portfolio.skills = []

        # 2. Leveled 스킬 (레벨별)
        if 'leveled' in enabled_types:
            level_names = request.POST.getlist('skill_level_name[]')
            level_values = request.POST.getlist('skill_level_value[]')
            portfolio.skills_with_levels = [
                {"name": name, "level": level}
                for name, level in zip(level_names, level_values)
                if name and level
            ]
        else:
            portfolio.skills_with_levels = []

        # 3. Categorized 스킬 (카테고리별)
        if 'categorized' in enabled_types:
            cat_names = request.POST.getlist('category_name[]')
            cat_skills = request.POST.getlist('category_skills[]')
            portfolio.categorized_skills = {
                name: [s.strip() for s in skills.split(',') if s.strip()]
                for name, skills in zip(cat_names, cat_skills)
                if name and skills
            }
        else:
            portfolio.categorized_skills = {}

        # 4. Free text 스킬 (자유형)
        if 'freetext' in enabled_types:
            portfolio.free_text_skills = request.POST.get('free_text_skills', '')
            tags_str = request.POST.get('skill_tags', '')
            portfolio.skill_tags = [s.strip() for s in tags_str.split(',') if s.strip()] if tags_str else []
        else:
            portfolio.free_text_skills = ''
            portfolio.skill_tags = []

        # 프로필 이미지
        if 'profile_image' in request.FILES:
            portfolio.profile_image = request.FILES['profile_image']

        portfolio.save()

        return redirect('community:portfolio_view', user_id=request.user.id)

    # 기술 스택을 쉼표로 구분된 문자열로 변환
    skills_str = ', '.join(portfolio.skills) if portfolio.skills else ''

    # 그라데이션 선택지 (모델의 GRADIENT_CHOICES 사용)
    gradient_choices = Portfolio.GRADIENT_CHOICES

    context = {
        'portfolio': portfolio,
        'skills_str': skills_str,
        'gradient_choices': gradient_choices,
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


# ========== 경력 관리 ==========

@login_required
def experience_create(request):
    """
    경력 추가
    """
    portfolio, created = Portfolio.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        # 폼 데이터 받기
        company = request.POST.get('company')
        position = request.POST.get('position')
        location = request.POST.get('location', '')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_current = request.POST.get('is_current') == 'on'
        description = request.POST.get('description', '')

        # 성과 데이터 처리 (JSON)
        achievements_str = request.POST.get('achievements', '')
        try:
            achievements = json.loads(achievements_str) if achievements_str else []
        except json.JSONDecodeError:
            achievements = []

        # 기술 스택 처리
        tech_stack_str = request.POST.get('tech_stack', '')
        tech_stack = [tech.strip() for tech in tech_stack_str.split(',') if tech.strip()] if tech_stack_str else []

        # 현재 재직 중이면 end_date를 None으로
        if is_current:
            end_date = None

        # 순서 자동 설정 (가장 큰 순서 + 1)
        max_order = Experience.objects.filter(portfolio=portfolio).aggregate(Max('order'))['order__max']
        order = (max_order or 0) + 1

        # 경력 생성
        Experience.objects.create(
            portfolio=portfolio,
            company=company,
            position=position,
            location=location,
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            description=description,
            achievements=achievements,
            tech_stack=tech_stack,
            order=order
        )

        return redirect('community:portfolio_edit')

    context = {
        'portfolio': portfolio,
    }

    return render(request, 'community/experience_create.html', context)


@login_required
def experience_edit(request, experience_id):
    """
    경력 수정
    """
    experience = get_object_or_404(Experience, pk=experience_id)

    # 본인 경력만 수정 가능
    if experience.portfolio.user != request.user:
        return HttpResponseForbidden("본인의 경력만 수정할 수 있습니다.")

    if request.method == 'POST':
        experience.company = request.POST.get('company')
        experience.position = request.POST.get('position')
        experience.location = request.POST.get('location', '')
        experience.start_date = request.POST.get('start_date')
        experience.is_current = request.POST.get('is_current') == 'on'
        experience.description = request.POST.get('description', '')

        # 현재 재직 중이면 end_date를 None으로
        if experience.is_current:
            experience.end_date = None
        else:
            experience.end_date = request.POST.get('end_date')

        # 성과 데이터 처리
        achievements_str = request.POST.get('achievements', '')
        try:
            experience.achievements = json.loads(achievements_str) if achievements_str else []
        except json.JSONDecodeError:
            experience.achievements = []

        # 기술 스택 처리
        tech_stack_str = request.POST.get('tech_stack', '')
        experience.tech_stack = [tech.strip() for tech in tech_stack_str.split(',') if tech.strip()] if tech_stack_str else []

        experience.save()

        return redirect('community:portfolio_edit')

    # 성과를 문자열로 변환 (편집 폼에 표시하기 위해)
    achievements_str = json.dumps(experience.achievements, ensure_ascii=False) if experience.achievements else '[]'

    # 기술 스택을 문자열로 변환
    tech_stack_str = ', '.join(experience.tech_stack) if experience.tech_stack else ''

    context = {
        'experience': experience,
        'achievements_str': achievements_str,
        'tech_stack_str': tech_stack_str,
    }

    return render(request, 'community/experience_edit.html', context)


@login_required
def experience_delete(request, experience_id):
    """
    경력 삭제
    """
    experience = get_object_or_404(Experience, pk=experience_id)

    # 본인 경력만 삭제 가능
    if experience.portfolio.user != request.user:
        return HttpResponseForbidden("본인의 경력만 삭제할 수 있습니다.")

    if request.method == 'POST':
        experience.delete()
        return redirect('community:portfolio_edit')

    return render(request, 'community/experience_delete.html', {'experience': experience})


@login_required
def experience_reorder(request):
    """
    경력 순서 변경 (AJAX)
    """
    if request.method == 'POST':
        data = json.loads(request.body)
        experience_orders = data.get('orders', [])

        for item in experience_orders:
            experience_id = item.get('id')
            order = item.get('order')

            try:
                experience = Experience.objects.get(pk=experience_id, portfolio__user=request.user)
                experience.order = order
                experience.save()
            except Experience.DoesNotExist:
                pass

        return JsonResponse({'success': True})

    return JsonResponse({'success': False})
