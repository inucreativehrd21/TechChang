"""
2048 게임 뷰

2048 게임은 4x4 보드에서 타일을 움직여 2048 타일을 만드는 퍼즐 게임입니다.
같은 숫자의 타일이 만나면 합쳐져서 두 배가 됩니다.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction, models
from django.db.models import Max
from django.contrib.auth.models import User
import random
import logging

from ..models import Game2048

logger = logging.getLogger(__name__)


@login_required
def game2048_start(request):
    """
    2048 게임 시작

    진행 중인 게임이 있으면 해당 게임으로 리다이렉트하고,
    없으면 새 게임을 생성합니다.

    Returns:
        HttpResponse: 게임 플레이 페이지로 리다이렉트
    """
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

    logger.info(f"New 2048 game created by {request.user.username} (ID: {game.id})")
    return redirect('pybo:game2048_play', game_id=game.id)


@login_required
def game2048_play(request, game_id):
    """
    2048 게임 플레이 페이지

    Args:
        game_id (int): 게임 ID

    Returns:
        HttpResponse: 게임 플레이 페이지
    """
    game = get_object_or_404(
        Game2048.select_related('player'),
        id=game_id,
        player=request.user
    )

    # 최고 점수 가져오기 (쿼리 최적화: aggregate 사용)
    best_score_result = Game2048.objects.filter(
        player=request.user
    ).aggregate(max_score=Max('best_score'))

    best_score = best_score_result['max_score'] or 0

    context = {
        'game': game,
        'best_score': best_score
    }
    return render(request, 'pybo/game2048_play.html', context)


@login_required
def game2048_move(request, game_id):
    """
    2048 게임 이동 처리

    사용자의 방향 입력을 받아 보드를 이동시키고,
    새 타일을 추가한 후 승패를 판정합니다.

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 이동 결과 (board, score, status 등)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(
        Game2048.select_related('player'),
        id=game_id,
        player=request.user
    )

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

        logger.info(f"User {request.user.username} won 2048 game {game_id} with score {game.score}")

    # 패배 확인 (더 이상 이동 불가능)
    elif not can_move(game.board_state):
        game.status = 'lost'
        game.end_date = timezone.now()

        # 최고 점수 업데이트
        if game.score > game.best_score:
            game.best_score = game.score

        logger.info(f"User {request.user.username} lost 2048 game {game_id} with score {game.score}")

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
    """
    2048 게임 재시작

    현재 게임의 최고 점수를 저장하고 새 게임을 생성합니다.

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 새 게임의 URL
    """
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


def game2048_leaderboard(request):
    """
    2048 게임 리더보드

    전체 사용자의 최고 점수를 기준으로 랭킹을 표시합니다.

    Returns:
        HttpResponse: 리더보드 페이지
    """
    # 사용자별 최고 점수 서브쿼리
    user_best_scores = Game2048.objects.filter(
        player=models.OuterRef('pk')
    ).order_by('-best_score').values('best_score')[:1]

    # 최고 점수가 있는 사용자만 가져오기 (try-except 패턴 적용)
    try:
        top_players = User.objects.annotate(
            top_score=models.Subquery(user_best_scores)
        ).filter(
            top_score__isnull=False,
            top_score__gt=0
        ).order_by('-top_score')[:100]
    except Exception:
        # profile이 없는 경우를 위해 select_related 제외
        top_players = User.objects.annotate(
            top_score=models.Subquery(user_best_scores)
        ).filter(
            top_score__isnull=False,
            top_score__gt=0
        ).order_by('-top_score')[:100]

    # 각 사용자의 게임 통계 가져오기
    leaderboard_data = []
    for rank, user in enumerate(top_players, start=1):
        user_games = Game2048.objects.filter(player=user)
        total_games = user_games.count()
        wins = user_games.filter(status='won').count()

        try:
            display_name = user.profile.display_name
        except AttributeError:
            display_name = user.username
        except Exception:
            display_name = user.username

        leaderboard_data.append({
            'rank': rank,
            'user': user,
            'display_name': display_name,
            'best_score': user.top_score,
            'total_games': total_games,
            'wins': wins,
        })

    context = {
        'leaderboard': leaderboard_data,
        'total_players': len(leaderboard_data),
    }

    return render(request, 'pybo/game2048_leaderboard.html', context)


# ========== 게임 로직 헬퍼 함수 ==========

def add_random_tile(game):
    """
    빈 칸에 랜덤 타일(2 또는 4) 추가

    Args:
        game (Game2048): 게임 인스턴스

    Note:
        90% 확률로 2, 10% 확률로 4가 생성됩니다.
    """
    empty_cells = []
    for i in range(4):
        for j in range(4):
            if game.board_state[i][j] == 0:
                empty_cells.append((i, j))

    if empty_cells:
        i, j = random.choice(empty_cells)
        game.board_state[i][j] = 2 if random.random() < 0.9 else 4


def move_board(board, direction):
    """
    보드를 특정 방향으로 이동

    Args:
        board (list): 4x4 보드 상태
        direction (str): 이동 방향 ('up', 'down', 'left', 'right')

    Returns:
        tuple: (이동 여부, 획득한 점수)
    """
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
    """
    한 줄을 왼쪽으로 밀고 합치기

    Args:
        row (list): 한 줄의 타일 값들 (길이 4)

    Returns:
        tuple: (합쳐진 줄, 획득한 점수)
    """
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
    """
    더 이상 이동 가능한지 확인

    빈 칸이 있거나 인접한 같은 숫자가 있으면 이동 가능합니다.

    Args:
        board (list): 4x4 보드 상태

    Returns:
        bool: 이동 가능 여부
    """
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
