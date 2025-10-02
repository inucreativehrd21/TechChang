"""
끝말잇기 게임 뷰
대학생들이 강의시간에 딴짓을 하기 위한 끝말잇기 게시판
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from django.utils.dateparse import parse_datetime
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count

from ..models import WordChainGame, WordChainEntry, WordChainChatMessage
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.contrib.auth import get_user_model


def wordchain_list(request):
    """끝말잇기 게임 목록"""
    # 활성 게임과 종료된 게임을 분리
    active_games = WordChainGame.objects.filter(status='active').annotate(
        entry_count=Count('entries')
    ).order_by('-create_date')
    
    finished_games = WordChainGame.objects.filter(status='finished').annotate(
        entry_count=Count('entries')
    ).order_by('-end_date')[:10]  # 최근 종료된 게임 10개만
    
    # 페이징 (활성 게임만)
    paginator = Paginator(active_games, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'active_games': page_obj,
        'finished_games': finished_games,
    }
    return render(request, 'pybo/wordchain_list.html', context)


@login_required
def wordchain_create(request):
    """새 끝말잇기 게임 생성"""
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        first_word = request.POST.get('first_word', '').strip()
        
        if not title:
            title = f"{request.user.username}님의 끝말잇기"
            
        if not first_word:
            messages.error(request, '첫 단어를 입력해주세요.')
            return redirect('pybo:wordchain_list')
        
        if len(first_word) < 2:
            messages.error(request, '단어는 2글자 이상이어야 합니다.')
            return redirect('pybo:wordchain_list')
            
        # 한글만 허용
        if not all('\uac00' <= char <= '\ud7a3' for char in first_word):
            messages.error(request, '한글 단어만 입력 가능합니다.')
            return redirect('pybo:wordchain_list')
        
        try:
            with transaction.atomic():
                # 게임 생성
                game = WordChainGame.objects.create(
                    title=title,
                    creator=request.user,
                    participant_count=1
                )
                
                # 첫 단어 추가
                WordChainEntry.objects.create(
                    game=game,
                    author=request.user,
                    word=first_word
                )
                
                messages.success(request, f'"{title}" 게임이 시작되었습니다!')
                return redirect('pybo:wordchain_detail', game_id=game.id)
                
        except Exception as e:
            messages.error(request, '게임 생성 중 오류가 발생했습니다.')
            return redirect('pybo:wordchain_list')
    
    return redirect('pybo:wordchain_list')


def wordchain_detail(request, game_id):
    """끝말잇기 게임 상세"""
    game = get_object_or_404(WordChainGame, id=game_id)
    entries = game.entries.select_related('author').order_by('create_date')
    
    context = {
        'game': game,
        'entries': entries,
        'total_entries': entries.count(),
        'participants': entries.values('author__username').distinct().count(),
    }
    return render(request, 'pybo/wordchain_detail.html', context)


@login_required
def wordchain_add_word(request, game_id):
    """단어 추가"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})
    
    game = get_object_or_404(WordChainGame, id=game_id)
    
    if game.status != 'active':
        return JsonResponse({'success': False, 'message': '종료된 게임입니다.'})
    
    word = request.POST.get('word', '').strip()
    
    # 단어 검증
    if not word:
        return JsonResponse({'success': False, 'message': '단어를 입력해주세요.'})
    
    if len(word) < 2:
        return JsonResponse({'success': False, 'message': '단어는 2글자 이상이어야 합니다.'})
    
    # 한글만 허용
    if not all('\uac00' <= char <= '\ud7a3' for char in word):
        return JsonResponse({'success': False, 'message': '한글 단어만 입력 가능합니다.'})
    
    # 마지막 단어 확인
    last_word = game.last_word
    if last_word and word[0] != last_word[-1]:
        return JsonResponse({
            'success': False, 
            'message': f'"{last_word[-1]}"로 시작하는 단어를 입력해주세요.'
        })
    
    # 중복 단어 확인
    if game.entries.filter(word=word).exists():
        return JsonResponse({'success': False, 'message': '이미 사용된 단어입니다.'})
    
    try:
        with transaction.atomic():
            # 단어 추가
            entry = WordChainEntry.objects.create(
                game=game,
                author=request.user,
                word=word
            )
            
            # 참가자 수 업데이트
            unique_participants = game.entries.values('author').distinct().count()
            game.participant_count = unique_participants
            game.save()
            
            return JsonResponse({
                'success': True,
                'message': '단어가 추가되었습니다!',
                'word': word,
                'author': request.user.username,
                'next_char': word[-1],
                'entry_count': game.entries.count(),
            })
            
    except Exception as e:
        return JsonResponse({'success': False, 'message': '단어 추가 중 오류가 발생했습니다.'})


@login_required
@require_POST
def wordchain_add_chat(request, game_id):
    """채팅 메시지 추가 (AJAX POST)
    요청: message
    반환: JSON {success, message, author, create_date}
    """
    game = get_object_or_404(WordChainGame, id=game_id)
    if game.status != 'active':
        return JsonResponse({'success': False, 'message': '종료된 게임입니다.'})

    text = request.POST.get('message', '').strip()
    if not text:
        return JsonResponse({'success': False, 'message': '메시지를 입력해주세요.'})

    try:
        # 서버 측 중복 방지: 동일 작성자(author)와 동일 메시지(message)가
        # 최근 short_window(초) 이내에 저장되어 있다면 새로 생성하지 않고
        # 기존 메시지의 정보를 반환합니다. 이는 빠른 연속 클릭/중복 전송을 방지합니다.
        short_window = 3  # seconds
        cutoff = timezone.now() - timedelta(seconds=short_window)
        existing = game.chat_messages.filter(
            author=request.user,
            message=text,
            create_date__gte=cutoff
        ).order_by('-create_date').first()
        if existing:
            # try to get display name from profile, fallback to username
            try:
                author_display = existing.author.profile.display_name
            except Exception:
                author_display = existing.author.username
            return JsonResponse({
                'success': True,
                'author': existing.author.username,
                'author_display': author_display,
                'message': existing.message,
                'create_date': existing.create_date.isoformat(),
                'note': 'duplicate_ignored'
            })
        chat = WordChainChatMessage.objects.create(
            game=game,
            author=request.user,
            message=text,
            create_date=timezone.now()
        )
        # return ISO formatted datetime so client and server can exchange reliably
        try:
            author_display = chat.author.profile.display_name
        except Exception:
            author_display = chat.author.username
        return JsonResponse({
            'success': True,
            'author': request.user.username,
            'author_display': author_display,
            'message': chat.message,
            'create_date': chat.create_date.isoformat()
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': '메시지 전송 중 오류가 발생했습니다.'})


@require_GET
def wordchain_get_chats(request, game_id):
    """최근 채팅 메시지 반환 (AJAX GET)
    파라미터: since (옵션, ISO datetime) -> 해당 시간 이후 메시지
    """
    game = get_object_or_404(WordChainGame, id=game_id)
    since = request.GET.get('since')
    qs = game.chat_messages.select_related('author')
    if since:
        try:
            # parse a variety of datetime formats (including ISO and space-separated)
            parsed = parse_datetime(since)
            if parsed is None:
                # try replacing space with T and parse again
                parsed = parse_datetime(since.replace(' ', 'T'))
            if parsed is not None:
                # if naive, make aware using current timezone
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
                qs = qs.filter(create_date__gt=parsed)
        except Exception:
            # fall back: ignore since and return recent messages
            pass

    messages = []
    for m in qs.order_by('create_date')[:200]:
        try:
            author_display = m.author.profile.display_name
        except Exception:
            author_display = m.author.username
        messages.append({
            'author': m.author.username,
            'author_display': author_display,
            'message': m.message,
            'create_date': m.create_date.isoformat()
        })

    return JsonResponse({'success': True, 'messages': messages})


@login_required
def wordchain_finish(request, game_id):
    """게임 종료"""
    game = get_object_or_404(WordChainGame, id=game_id)
    
    # 게임 생성자만 종료 가능
    if request.user != game.creator:
        messages.error(request, '게임 생성자만 게임을 종료할 수 있습니다.')
        return redirect('pybo:wordchain_detail', game_id=game_id)
    
    if game.status == 'finished':
        messages.info(request, '이미 종료된 게임입니다.')
        return redirect('pybo:wordchain_detail', game_id=game_id)
    
    game.status = 'finished'
    game.end_date = timezone.now()
    game.save()
    
    messages.success(request, f'게임이 종료되었습니다! 총 {game.entries.count()}개의 단어가 등록되었습니다.')
    return redirect('pybo:wordchain_detail', game_id=game_id)