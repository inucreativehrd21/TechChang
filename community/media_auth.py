"""Nginx auth_request gate for user-uploaded files with per-record visibility."""

from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from django.http import HttpResponse
from django.views.decorators.http import require_safe

from .models import (
    Answer, CollectionProject, Comment, Portfolio, PortfolioAsset,
    PortfolioCollection, Project, Question, QuestionImage,
)


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.bmp', '.tif', '.tiff', '.ico'}
DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.zip', '.hwp'}


def _question_visible(question, user):
    if question.is_deleted:
        return False
    if question.category.name == '문의':
        return user.is_authenticated and (user.is_staff or user.pk == question.author_id)
    return not question.is_locked or user.is_authenticated


def _portfolio_visible(portfolio, user):
    return (
        portfolio.is_publicly_visible()
        or (user.is_authenticated and (user.is_staff or user.pk == portfolio.user_id))
    )


def _question_media_visible(name, user):
    if name.startswith('question_files/'):
        questions = Question.objects.filter(file=name).select_related('category')
        return any(_question_visible(question, user) for question in questions)
    if name.startswith('questions/'):
        questions = Question.objects.filter(image=name).select_related('category')
        images = QuestionImage.objects.filter(image=name).select_related('question__category')
        return (any(_question_visible(question, user) for question in questions)
                or any(_question_visible(image.question, user) for image in images))
    if name.startswith('answers/'):
        answers = Answer.objects.filter(image=name, is_deleted=False).select_related('question__category')
        return any(_question_visible(answer.question, user) for answer in answers)
    if name.startswith('comments/'):
        comments = Comment.objects.filter(image=name).select_related('question__category', 'answer__question__category')
        return any(_question_visible(comment.question or comment.answer.question, user)
                   for comment in comments if comment.question_id or comment.answer_id)
    return False


def _portfolio_media_visible(name, user):
    if name.startswith('portfolio/html_assets/'):
        assets = PortfolioAsset.objects.filter(image=name).select_related('collection')
        return any(_portfolio_visible(asset.collection, user) for asset in assets)
    if name.startswith('portfolio/profiles/'):
        fields = ((Portfolio, 'profile_image'), (PortfolioCollection, 'profile_image'))
    elif name.startswith('portfolio/hero_backgrounds/'):
        fields = ((Portfolio, 'hero_background_image'), (PortfolioCollection, 'hero_background_image'))
    elif name.startswith('portfolio/projects/'):
        fields = ((Project, 'image'), (CollectionProject, 'image'))
    else:
        return False
    for model, field in fields:
        records = model.objects.filter(**{field: name})
        if model in (Project, CollectionProject):
            parent = 'portfolio' if model is Project else 'portfolio_collection'
            records = records.select_related(parent)
            if any(_portfolio_visible(getattr(record, parent), user) for record in records):
                return True
        elif any(_portfolio_visible(record, user) for record in records):
            return True
    return False


@require_safe
def media_authorization(request):
    """Return 204 only for an authorized, known upload; Nginx serves the bytes."""
    original_uri = request.headers.get('X-Original-URI', '')
    path = unquote(urlsplit(original_uri).path)
    if not path.startswith('/media/') or '\\' in path or '\x00' in path:
        return HttpResponse(status=403)
    name = path[len('/media/'):]
    if not name or any(part in ('', '.', '..') for part in name.split('/')):
        return HttpResponse(status=403)
    extension = PurePosixPath(name).suffix.lower()
    if name.startswith('question_files/'):
        allowed = extension in DOCUMENT_EXTENSIONS and _question_media_visible(name, request.user)
    elif name.startswith(('questions/', 'answers/', 'comments/')):
        allowed = extension in IMAGE_EXTENSIONS and _question_media_visible(name, request.user)
    elif name.startswith('portfolio/'):
        allowed = extension in IMAGE_EXTENSIONS and _portfolio_media_visible(name, request.user)
    else:
        allowed = False
    return HttpResponse(status=204 if allowed else 403)
