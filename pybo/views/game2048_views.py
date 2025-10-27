"""2048 게임 뷰"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
import random
import logging

from ..models import Game2048

logger = logging.getLogger(__name__)


@login_required
def game2048_start(request):
    """2048 게임 시작"""
    # 진행중인 게임이 있으면 그걸로 이동
    existing_game = Game2048.objects.filter(
        player=request.user,
        status='playing'
    ).first()

    if existing_game:
        return redirect('pybo:game2048_play', game_id=existing_game.id)

    # 새 게임 생성
    game = Game2048.objects.create(player=request.user)

    # 초기 타일 2개 추가
    add_random_tile(game)
    add_random_tile(game)
    game.save()

    return redirect('pybo:game2048_play', game_id=game.id)


@login_required
def game2048_play(request, game_id):
    """2048 게임 플레이"""
    game = get_object_or_404(Game2048, id=game_id, player=request.user)

    # 최고 점수 가져오기
    best_score = Game2048.objects.filter(
        player=request.user
    ).order_by('-best_score').values_list('best_score', flat=True).first() or 0

    context = {
        'game': game,
        'best_score': best_score
    }
    return render(request, 'pybo/game2048_play.html', context)


@login_required
def game2048_move(request, game_id):
    """2048 이동 처리"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(Game2048, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    direction = request.POST.get('direction')  # 'up', 'down', 'left', 'right'

    if direction not in ['up', 'down', 'left', 'right']:
        return JsonResponse({'success': False, 'message': '잘못된 방향입니다.'})

    # 보드 복사
    old_board = [row[:] for row in game.board_state]

    # 이동 처리
    moved, score_gained = move_board(game.board_state, direction)

    if not moved:
        return JsonResponse({'success': False, 'message': '이동할 수 없습니다.'})

    # 점수 업데이트
    game.score += score_gained
    game.moves += 1

    # 새 타일 추가
    add_random_tile(game)

    # 승리 확인 (2048 타일이 있는지)
    has_2048 = any(2048 in row for row in game.board_state)

    if has_2048 and game.status == 'playing':
        game.status = 'won'
        game.end_date = timezone.now()

        # 최고 점수 업데이트
        if game.score > game.best_score:
            game.best_score = game.score

    # 패배 확인 (더 이상 이동 불가능)
    elif not can_move(game.board_state):
        game.status = 'lost'
        game.end_date = timezone.now()

        # 최고 점수 업데이트
        if game.score > game.best_score:
            game.best_score = game.score

    game.save()

    return JsonResponse({
        'success': True,
        'board': game.board_state,
        'score': game.score,
        'score_gained': score_gained,
        'status': game.status,
        'game_over': game.status != 'playing'
    })


@login_required
def game2048_restart(request, game_id):
    """2048 게임 재시작"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(Game2048, id=game_id, player=request.user)

    # 최고 점수 저장
    if game.score > game.best_score:
        game.best_score = game.score
        game.save()

    # 새 게임 생성
    new_game = Game2048.objects.create(
        player=request.user,
        best_score=game.best_score
    )

    # 초기 타일 2개 추가
    add_random_tile(new_game)
    add_random_tile(new_game)
    new_game.save()

    return JsonResponse({
        'success': True,
        'redirect_url': f'/pybo/2048/{new_game.id}/'
    })


# ========== 게임 로직 헬퍼 함수 ==========

def add_random_tile(game):
    """빈 칸에 랜덤 타일(2 또는 4) 추가"""
    empty_cells = []
    for i in range(4):
        for j in range(4):
            if game.board_state[i][j] == 0:
                empty_cells.append((i, j))

    if empty_cells:
        i, j = random.choice(empty_cells)
        game.board_state[i][j] = 2 if random.random() < 0.9 else 4


def move_board(board, direction):
    """보드를 특정 방향으로 이동"""
    moved = False
    score = 0

    if direction == 'left':
        for i in range(4):
            merged, row_score = merge_row(board[i])
            if merged != board[i]:
                moved = True
                board[i] = merged
                score += row_score

    elif direction == 'right':
        for i in range(4):
            reversed_row = board[i][::-1]
            merged, row_score = merge_row(reversed_row)
            merged = merged[::-1]
            if merged != board[i]:
                moved = True
                board[i] = merged
                score += row_score

    elif direction == 'up':
        for j in range(4):
            column = [board[i][j] for i in range(4)]
            merged, col_score = merge_row(column)
            if merged != column:
                moved = True
                for i in range(4):
                    board[i][j] = merged[i]
                score += col_score

    elif direction == 'down':
        for j in range(4):
            column = [board[i][j] for i in range(4)]
            column = column[::-1]
            merged, col_score = merge_row(column)
            merged = merged[::-1]
            if merged != column[::-1]:
                moved = True
                for i in range(4):
                    board[i][j] = merged[i]
                score += col_score

    return moved, score


def merge_row(row):
    """한 줄을 왼쪽으로 밀고 합치기"""
    # 0이 아닌 값만 추출
    non_zero = [x for x in row if x != 0]

    # 합치기
    merged = []
    score = 0
    skip = False

    for i in range(len(non_zero)):
        if skip:
            skip = False
            continue

        if i + 1 < len(non_zero) and non_zero[i] == non_zero[i + 1]:
            # 같은 숫자 합치기
            merged.append(non_zero[i] * 2)
            score += non_zero[i] * 2
            skip = True
        else:
            merged.append(non_zero[i])

    # 나머지를 0으로 채우기
    merged.extend([0] * (4 - len(merged)))

    return merged, score


def can_move(board):
    """더 이상 이동 가능한지 확인"""
    # 빈 칸이 있는지
    for row in board:
        if 0 in row:
            return True

    # 인접한 같은 숫자가 있는지 (가로)
    for i in range(4):
        for j in range(3):
            if board[i][j] == board[i][j + 1]:
                return True

    # 인접한 같은 숫자가 있는지 (세로)
    for i in range(3):
        for j in range(4):
            if board[i][j] == board[i + 1][j]:
                return True

    return False
