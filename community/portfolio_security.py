"""포트폴리오 HTML의 수신·저장·검토 자원 한도를 한 곳에서 관리해요."""
from datetime import timedelta
from functools import wraps
import os
from pathlib import Path
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import BinaryField, Case, F, TextField, Value, When
from django.db.models.functions import Cast, Length, Substr
from django.utils import timezone

MAX_HTML_BYTES = 20 * 1024 * 1024
MAX_PASTE_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 26 * 1024 * 1024
MAX_ACCOUNT_HTML_BYTES = 50 * 1024 * 1024
MAX_PREVIEW_CHARS = 64 * 1024


def html_byte_length():
    return Length(Cast('html_content', output_field=BinaryField()))


def with_html_summary(queryset, *, editor=False):
    queryset = queryset.defer('html_content').annotate(
        html_bytes=html_byte_length(), html_chars=Length('html_content'),
        html_preview=Substr('html_content', 1, MAX_PREVIEW_CHARS),
    )
    if editor:
        queryset = queryset.annotate(html_editor=Case(
            When(html_bytes__lte=MAX_PASTE_BYTES, then=F('html_content')),
            default=Value(''), output_field=TextField(),
        ))
    return queryset


def consume_upload_budget(user_id):
    """프로세스별 메모리 캐시가 아닌 DB 잠금으로 회원당 10분 10회를 제한해요."""
    from .models import PortfolioUploadBudget
    now = timezone.now()
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user_id)
        budget, _ = PortfolioUploadBudget.objects.get_or_create(user_id=user_id, defaults={'window_start': now})
        if budget.window_start <= now - timedelta(minutes=10):
            budget.window_start, budget.requests = now, 0
        if budget.requests >= 10:
            return False
        budget.requests += 1
        budget.save(update_fields=['window_start', 'requests'])
        return True


def serialized_portfolio_edit(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method != 'POST':
            return view(request, *args, **kwargs)
        # 한 회원이 동시에 다른 포트폴리오를 저장해 총량 검사를 우회하지 못하게 해요.
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            return view(request, *args, **kwargs)
    return wrapped


def backup_html(collection):
    """컬렉션마다 이전 원본 한 개만 보관해 무제한 이력 증가를 막아요."""
    from .models import PortfolioCollection
    original = PortfolioCollection.objects.only('html_content').get(pk=collection.pk).html_content
    if not original or original == collection.html_content:
        return
    directory = Path(getattr(settings, 'PORTFOLIO_HTML_BACKUP_ROOT', Path(settings.BASE_DIR) / 'backups' / 'portfolio_sources'))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / f'{collection.pk}.html'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(original.encode('utf-8'))
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
