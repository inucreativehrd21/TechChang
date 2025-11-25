"""
방명록 뷰

포스트잇 스타일의 방명록 기능을 제공합니다.
사용자는 색상을 선택하여 방명록을 작성할 수 있습니다.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator
import random
import logging

from ..models import GuestBook

logger = logging.getLogger(__name__)


def guestbook_list(request):
    """
    방명록 목록 페이지

    모든 방명록 항목을 최신순으로 보여줍니다.

    Returns:
        HttpResponse: 방명록 목록 페이지
    """
    # select_related로 author 정보를 함께 가져오기 (N+1 쿼리 방지)
    entries = GuestBook.objects.all().select_related('author').order_by('-create_date')

    context = {
        'entries': entries,
        'font_choices': GuestBook.FONT_CHOICES,
    }
    return render(request, 'pybo/guestbook_list.html', context)


@login_required
def guestbook_create(request):
    """
    방명록 작성

    사용자가 색상과 내용을 입력하여 방명록을 작성합니다.
    포스트잇은 랜덤한 위치와 각도로 배치됩니다.

    Returns:
        JsonResponse: 작성 결과 및 방명록 데이터
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    content = request.POST.get('content', '').strip()
    color = request.POST.get('color', '#fff475')
    font_family = request.POST.get('font_family', GuestBook.FONT_CHOICES[0][0])

    allowed_fonts = {choice[0] for choice in GuestBook.FONT_CHOICES}
    if font_family not in allowed_fonts:
        font_family = GuestBook.FONT_CHOICES[0][0]

    # 입력 검증
    if not content:
        return JsonResponse({'success': False, 'message': '내용을 입력해주세요.'})

    if len(content) > 200:
        return JsonResponse({'success': False, 'message': '200자 이내로 입력해주세요.'})

    # 랜덤 위치와 회전 (포스트잇 효과)
    position_x = random.randint(0, 80)  # 0-80% (오른쪽 여백)
    position_y = random.randint(0, 80)  # 0-80% (아래쪽 여백)
    rotation = random.uniform(-5, 5)  # -5도 ~ 5도

    entry = GuestBook.objects.create(
        author=request.user,
        content=content,
        color=color,
        font_family=font_family,
        position_x=position_x,
        position_y=position_y,
        rotation=rotation
    )

    # 작성자 표시명 가져오기 (프로필이 있으면 display_name, 없으면 username)
    try:
        author_display = request.user.profile.display_name
    except AttributeError:
        # profile 속성이 없는 경우
        author_display = request.user.username
    except Exception as e:
        # 기타 예상치 못한 오류
        logger.warning(f"Error getting display name for user {request.user.username}: {e}")
        author_display = request.user.username

    logger.info(f"Guestbook entry created by {request.user.username} (ID: {entry.id})")

    return JsonResponse({
        'success': True,
        'message': '방명록이 작성되었습니다!',
        'entry': {
            'id': entry.id,
            'content': entry.content,
            'color': entry.color,
            'font_family': entry.font_family,
            'position_x': entry.position_x,
            'position_y': entry.position_y,
            'rotation': entry.rotation,
            'author': author_display,
            'create_date': entry.create_date.strftime('%Y-%m-%d %H:%M')
        }
    })


@login_required
def guestbook_delete(request, entry_id):
    """
    방명록 삭제

    작성자 본인만 자신의 방명록을 삭제할 수 있습니다.

    Args:
        entry_id (int): 방명록 ID

    Returns:
        JsonResponse: 삭제 결과
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    entry = get_object_or_404(
        GuestBook.objects.select_related('author'),
        id=entry_id
    )

    # 권한 확인
    if entry.author != request.user:
        logger.warning(f"User {request.user.username} tried to delete guestbook {entry_id} by {entry.author.username}")
        return JsonResponse({'success': False, 'message': '삭제 권한이 없습니다.'})

    entry.delete()
    logger.info(f"Guestbook entry {entry_id} deleted by {request.user.username}")

    return JsonResponse({
        'success': True,
        'message': '방명록이 삭제되었습니다.'
    })
