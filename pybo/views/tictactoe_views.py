"""틱택토 게임 뷰"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging

from ..models import TicTacToeGame

logger = logging.getLogger(__name__)


@login_required
def tictactoe_list(request):
    """틱택토 게임 목록"""
    games = TicTacToeGame.objects.all().select_related('creator', 'player_x', 'player_o', 'winner')
    context = {
        'games': games
    }
    return render(request, 'pybo/tictactoe_list.html', context)


@login_required
def tictactoe_create(request):
    """틱택토 게임 생성"""
    if request.method == 'POST':
        title = request.POST.get('title', f"{request.user.username}의 틱택토 게임")

        game = TicTacToeGame.objects.create(
            title=title,
            creator=request.user,
            player_x=request.user
        )

        return redirect('pybo:tictactoe_detail', game_id=game.id)

    return render(request, 'pybo/tictactoe_create.html')


@login_required
def tictactoe_detail(request, game_id):
    """틱택토 게임 상세"""
    game = get_object_or_404(TicTacToeGame, id=game_id)

    # 플레이어 구분
    is_player_x = game.player_x == request.user
    is_player_o = game.player_o == request.user
    can_join = game.status == 'waiting' and not is_player_x and not is_player_o

    context = {
        'game': game,
        'is_player_x': is_player_x,
        'is_player_o': is_player_o,
        'can_join': can_join
    }
    return render(request, 'pybo/tictactoe_detail.html', context)


@login_required
def tictactoe_join(request, game_id):
    """틱택토 게임 참가"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(TicTacToeGame, id=game_id)

    # 검증
    if game.status != 'waiting':
        return JsonResponse({'success': False, 'message': '이미 시작된 게임입니다.'})

    if game.player_x == request.user:
        return JsonResponse({'success': False, 'message': '이미 참가한 게임입니다.'})

    if game.player_o:
        return JsonResponse({'success': False, 'message': '게임이 이미 꽉 찼습니다.'})

    # 플레이어 O로 참가
    game.player_o = request.user
    game.status = 'playing'
    game.start_date = timezone.now()
    game.save()

    # WebSocket 브로드캐스트
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'tictactoe_{game_id}',
            {
                'type': 'game_update',
                'data': {
                    'action': 'game_started',
                    'player_o': request.user.username
                }
            }
        )
    except Exception as e:
        logger.error(f"WebSocket broadcast error: {e}")

    return JsonResponse({'success': True, 'message': '게임에 참가했습니다!'})


@login_required
def tictactoe_move(request, game_id):
    """틱택토 수 두기"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(TicTacToeGame, id=game_id)

    # 검증
    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '진행중인 게임이 아닙니다.'})

    # 턴 검증
    if game.current_turn == 'X' and game.player_x != request.user:
        return JsonResponse({'success': False, 'message': '당신의 턴이 아닙니다.'})
    if game.current_turn == 'O' and game.player_o != request.user:
        return JsonResponse({'success': False, 'message': '당신의 턴이 아닙니다.'})

    # 위치 가져오기
    try:
        row = int(request.POST.get('row'))
        col = int(request.POST.get('col'))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': '잘못된 위치입니다.'})

    # 위치 검증
    if not (0 <= row <= 2 and 0 <= col <= 2):
        return JsonResponse({'success': False, 'message': '잘못된 위치입니다.'})

    if game.board_state[row][col]:
        return JsonResponse({'success': False, 'message': '이미 놓인 위치입니다.'})

    # 수 두기
    with transaction.atomic():
        game.board_state[row][col] = game.current_turn

        # 승리 체크
        winner = check_winner(game.board_state)

        if winner:
            game.status = 'finished'
            game.winner = game.player_x if winner == 'X' else game.player_o
            game.end_date = timezone.now()
            game.save()

            # WebSocket 브로드캐스트
            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'tictactoe_{game_id}',
                    {
                        'type': 'game_update',
                        'data': {
                            'action': 'game_over',
                            'row': row,
                            'col': col,
                            'mark': game.current_turn,
                            'winner': winner,
                            'winner_username': game.winner.username
                        }
                    }
                )
            except Exception as e:
                logger.error(f"WebSocket broadcast error: {e}")

            return JsonResponse({
                'success': True,
                'message': f'{winner} 승리!',
                'winner': winner,
                'game_over': True
            })

        # 무승부 체크
        if is_board_full(game.board_state):
            game.status = 'finished'
            game.end_date = timezone.now()
            game.save()

            # WebSocket 브로드캐스트
            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'tictactoe_{game_id}',
                    {
                        'type': 'game_update',
                        'data': {
                            'action': 'game_over',
                            'row': row,
                            'col': col,
                            'mark': game.current_turn,
                            'draw': True
                        }
                    }
                )
            except Exception as e:
                logger.error(f"WebSocket broadcast error: {e}")

            return JsonResponse({
                'success': True,
                'message': '무승부!',
                'draw': True,
                'game_over': True
            })

        # 턴 변경
        game.current_turn = 'O' if game.current_turn == 'X' else 'X'
        game.save()

        # WebSocket Delta Update
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'tictactoe_{game_id}',
                {
                    'type': 'game_update',
                    'data': {
                        'action': 'move',
                        'row': row,
                        'col': col,
                        'mark': 'X' if game.current_turn == 'O' else 'O',  # 방금 둔 마크
                        'next_turn': game.current_turn
                    }
                }
            )
        except Exception as e:
            logger.error(f"WebSocket broadcast error: {e}")

    return JsonResponse({
        'success': True,
        'message': '수를 두었습니다!',
        'next_turn': game.current_turn
    })


def check_winner(board):
    """승자 체크"""
    # 가로 체크
    for row in board:
        if row[0] == row[1] == row[2] and row[0]:
            return row[0]

    # 세로 체크
    for col in range(3):
        if board[0][col] == board[1][col] == board[2][col] and board[0][col]:
            return board[0][col]

    # 대각선 체크
    if board[0][0] == board[1][1] == board[2][2] and board[0][0]:
        return board[0][0]
    if board[0][2] == board[1][1] == board[2][0] and board[0][2]:
        return board[0][2]

    return None


def is_board_full(board):
    """보드가 꽉 찼는지 체크"""
    for row in board:
        if '' in row:
            return False
    return True
