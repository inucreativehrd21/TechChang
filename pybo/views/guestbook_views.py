"""방명록 뷰"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator
import random
import logging

from ..models import GuestBook

logger = logging.getLogger(__name__)


def guestbook_list(request):
    """방명록 목록"""
    entries = GuestBook.objects.all().select_related('author')

    context = {
        'entries': entries
    }
    return render(request, 'pybo/guestbook_list.html', context)


@login_required
def guestbook_create(request):
    """방명록 작성"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    content = request.POST.get('content', '').strip()
    color = request.POST.get('color', '#fff475')

    if not content:
        return JsonResponse({'success': False, 'message': '내용을 입력해주세요.'})

    if len(content) > 200:
        return JsonResponse({'success': False, 'message': '200자 이내로 입력해주세요.'})

    # 랜덤 위치와 회전
    position_x = random.randint(0, 80)  # 0-80% (오른쪽 여백)
    position_y = random.randint(0, 80)  # 0-80% (아래쪽 여백)
    rotation = random.uniform(-5, 5)  # -5도 ~ 5도

    entry = GuestBook.objects.create(
        author=request.user,
        content=content,
        color=color,
        position_x=position_x,
        position_y=position_y,
        rotation=rotation
    )

    try:
        author_display = request.user.profile.display_name
    except:
        author_display = request.user.username

    return JsonResponse({
        'success': True,
        'message': '방명록이 작성되었습니다!',
        'entry': {
            'id': entry.id,
            'content': entry.content,
            'color': entry.color,
            'position_x': entry.position_x,
            'position_y': entry.position_y,
            'rotation': entry.rotation,
            'author': author_display,
            'create_date': entry.create_date.strftime('%Y-%m-%d %H:%M')
        }
    })


@login_required
def guestbook_delete(request, entry_id):
    """방명록 삭제"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    entry = get_object_or_404(GuestBook, id=entry_id)

    if entry.author != request.user:
        return JsonResponse({'success': False, 'message': '삭제 권한이 없습니다.'})

    entry.delete()

    return JsonResponse({
        'success': True,
        'message': '방명록이 삭제되었습니다.'
    })
