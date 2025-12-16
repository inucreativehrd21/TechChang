"""
지뢰찾기 게임 뷰

클래식 지뢰찾기 게임입니다. 지뢰가 없는 모든 칸을 공개하면 승리합니다.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Count, Avg, Min, Q
from django.contrib.auth.models import User
import json
import random
import logging

from ..models import MinesweeperGame

logger = logging.getLogger(__name__)


@login_required
def minesweeper_start(request):
    """
    지뢰찾기 게임 시작

    난이도를 선택하는 페이지를 보여줍니다.

    Returns:
        HttpResponse: 난이도 선택 페이지
    """
    return render(request, 'community/minesweeper_start.html')


@login_required
def minesweeper_create(request):
    """
    지뢰찾기 게임 생성

    선택한 난이도로 새 게임을 생성합니다.

    Returns:
        HttpResponse: 게임 플레이 페이지로 리다이렉트
    """
    difficulty = request.GET.get('difficulty', 'easy')

    # 난이도별 설정
    difficulty_settings = {
        'easy': {'rows': 9, 'cols': 9, 'mines': 10},
        'medium': {'rows': 16, 'cols': 16, 'mines': 40},
        'hard': {'rows': 16, 'cols': 30, 'mines': 99},
    }

    settings = difficulty_settings.get(difficulty, difficulty_settings['easy'])

    # 새 게임 생성
    game = MinesweeperGame.objects.create(
        player=request.user,
        difficulty=difficulty,
        rows=settings['rows'],
        cols=settings['cols'],
        mines_count=settings['mines']
    )

    # 지뢰 배치
    place_mines(game)
    game.save()

    logger.info(f"New minesweeper game created by {request.user.username} (ID: {game.id}, difficulty: {difficulty})")
    return redirect('pybo:minesweeper_play', game_id=game.id)


@login_required
def minesweeper_play(request, game_id):
    """
    지뢰찾기 게임 플레이 페이지

    Args:
        game_id (int): 게임 ID

    Returns:
        HttpResponse: 게임 플레이 페이지
    """
    game = get_object_or_404(
        MinesweeperGame.objects.select_related('player'),
        id=game_id,
        player=request.user
    )

    context = {
        'game': game,
    }
    return render(request, 'community/minesweeper_play.html', context)


def _format_time(seconds):
    """초 단위를 mm:ss 문자열로 변환"""
    if seconds is None:
        return "-"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "-"
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def minesweeper_leaderboard(request):
    """
    지뢰찾기 리더보드

    난이도별로 최고 기록과 신뢰도 지표(승률, 평균/최고 시간, 지뢰 클릭 수)를 보여줍니다.
    """
    difficulty = request.GET.get('difficulty', 'easy')
    if difficulty not in ['easy', 'medium', 'hard']:
        difficulty = 'easy'

    qs = MinesweeperGame.objects.filter(difficulty=difficulty)
    total_games = qs.count()
    wins_qs = qs.filter(status='won')
    losses_qs = qs.filter(status='lost')

    # 사용자별 집계 (승리 경험이 있는 사용자만 랭킹에 포함)
    stats_qs = qs.values('player').annotate(
        total_games=Count('id'),
        wins=Count('id', filter=Q(status='won')),
        losses=Count('id', filter=Q(status='lost')),
        best_time=Min('time_elapsed', filter=Q(status='won')),
        avg_time=Avg('time_elapsed', filter=Q(status='won')),
    ).filter(wins__gt=0)

    # 사용자 객체 한번에 로드
    user_ids = [entry['player'] for entry in stats_qs]
    users = {u.id: u for u in User.objects.select_related('profile').filter(id__in=user_ids)}

    leaderboard = []
    for entry in stats_qs:
        user = users.get(entry['player'])
        if not user:
            continue

        total = entry['total_games'] or 0
        wins = entry['wins'] or 0
        losses = entry['losses'] or 0
        win_rate = (wins / total * 100) if total else 0

        try:
            display_name = user.profile.display_name
            profile_image = user.profile.profile_image.url if user.profile.profile_image else None
        except Exception:
            display_name = user.username
            profile_image = None

        leaderboard.append({
            'user': user,
            'display_name': display_name,
            'profile_image': profile_image,
            'best_time': entry['best_time'],
            'best_time_display': _format_time(entry['best_time']),
            'avg_time': entry['avg_time'],
            'avg_time_display': _format_time(entry['avg_time']),
            'total_games': total,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'mine_clicks': losses,  # 패배 횟수를 지뢰 클릭 수로 간주
        })

    # 정렬: 최고 기록 빠른 순 → 승률 높은 순 → 지뢰 클릭(패배) 적은 순
    leaderboard.sort(key=lambda x: (
        x['best_time'] if x['best_time'] is not None else 999999,
        -x['win_rate'],
        x['mine_clicks'],
    ))

    for idx, item in enumerate(leaderboard, start=1):
        item['rank'] = idx

    context = {
        'difficulty': difficulty,
        'leaderboard': leaderboard[:100],
        'total_players': len(leaderboard),
        'summary': {
            'total_games': total_games,
            'wins': wins_qs.count(),
            'losses': losses_qs.count(),
            'mine_clicks_total': losses_qs.count(),
            'best_overall': _format_time(wins_qs.aggregate(best=Min('time_elapsed'))['best']),
            'avg_overall': _format_time(wins_qs.aggregate(avg=Avg('time_elapsed'))['avg']),
        }
    }

    return render(request, 'community/minesweeper_leaderboard.html', context)


@login_required
def minesweeper_reveal(request, game_id):
    """
    지뢰찾기 칸 공개

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 공개 결과
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(MinesweeperGame, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    row = int(request.POST.get('row'))
    col = int(request.POST.get('col'))

    # 이미 공개된 칸인지 확인
    if [row, col] in game.board_state['revealed']:
        return JsonResponse({'success': False, 'message': '이미 공개된 칸입니다.'})

    # 깃발이 꽂혀있는지 확인
    if [row, col] in game.board_state['flagged']:
        return JsonResponse({'success': False, 'message': '깃발이 꽂혀있습니다.'})

    # 지뢰를 밟았는지 확인
    if [row, col] in game.board_state['mines']:
        game.status = 'lost'
        game.end_date = timezone.now()
        game.save()

        return JsonResponse({
            'success': True,
            'hit_mine': True,
            'game_over': True,
            'message': '지뢰를 밟았습니다!',
            'mines': game.board_state['mines']
        })

    # 칸 공개 (연쇄 공개 포함)
    revealed_cells = reveal_cell(game, row, col)
    game.board_state['revealed'].extend(revealed_cells)
    game.save()

    # 승리 확인 (지뢰가 아닌 모든 칸을 공개했는지)
    total_cells = game.rows * game.cols
    revealed_count = len(game.board_state['revealed'])
    if revealed_count == total_cells - game.mines_count:
        game.status = 'won'
        game.end_date = timezone.now()
        game.save()

        return JsonResponse({
            'success': True,
            'revealed': revealed_cells,
            'game_over': True,
            'won': True,
            'message': '축하합니다! 모든 지뢰를 찾았습니다!',
            'mines': game.board_state['mines']
        })

    return JsonResponse({
        'success': True,
        'revealed': revealed_cells
    })


@login_required
def minesweeper_flag(request, game_id):
    """
    지뢰찾기 깃발 토글

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 깃발 토글 결과
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(MinesweeperGame, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    row = int(request.POST.get('row'))
    col = int(request.POST.get('col'))

    # 이미 공개된 칸인지 확인
    if [row, col] in game.board_state['revealed']:
        return JsonResponse({'success': False, 'message': '이미 공개된 칸입니다.'})

    # 깃발 토글
    if [row, col] in game.board_state['flagged']:
        game.board_state['flagged'].remove([row, col])
        flagged = False
    else:
        game.board_state['flagged'].append([row, col])
        flagged = True

    game.save()

    return JsonResponse({
        'success': True,
        'flagged': flagged,
        'flags_count': len(game.board_state['flagged'])
    })


@login_required
def minesweeper_update_time(request, game_id):
    """
    게임 시간 업데이트

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 업데이트 결과
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(MinesweeperGame, id=game_id, player=request.user)

    if game.status == 'playing':
        time_elapsed = int(request.POST.get('time', 0))
        game.time_elapsed = time_elapsed
        game.save()

        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'message': '게임이 종료되었습니다.'})


# ========== 게임 로직 헬퍼 함수 ==========

def place_mines(game):
    """
    지뢰를 랜덤하게 배치

    Args:
        game (MinesweeperGame): 게임 인스턴스
    """
    mines = []
    while len(mines) < game.mines_count:
        row = random.randint(0, game.rows - 1)
        col = random.randint(0, game.cols - 1)
        if [row, col] not in mines:
            mines.append([row, col])

    game.board_state['mines'] = mines
    game.board_state['revealed'] = []
    game.board_state['flagged'] = []


def count_adjacent_mines(game, row, col):
    """
    인접한 지뢰의 개수를 계산

    Args:
        game (MinesweeperGame): 게임 인스턴스
        row (int): 행
        col (int): 열

    Returns:
        int: 인접한 지뢰의 개수
    """
    count = 0
    for dr in [-1, 0, 1]:
        for dc in [-1, 0, 1]:
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if 0 <= nr < game.rows and 0 <= nc < game.cols:
                if [nr, nc] in game.board_state['mines']:
                    count += 1
    return count


def reveal_cell(game, row, col):
    """
    칸을 공개 (연쇄 공개 포함)

    Args:
        game (MinesweeperGame): 게임 인스턴스
        row (int): 행
        col (int): 열

    Returns:
        list: 공개된 칸들의 리스트
    """
    revealed = []
    stack = [(row, col)]

    while stack:
        r, c = stack.pop()

        # 이미 공개된 칸이거나 범위를 벗어나면 스킵
        if [r, c] in revealed or [r, c] in game.board_state['revealed']:
            continue
        if r < 0 or r >= game.rows or c < 0 or c >= game.cols:
            continue

        revealed.append([r, c])

        # 인접한 지뢰 개수 확인
        adjacent_mines = count_adjacent_mines(game, r, c)

        # 인접한 지뢰가 없으면 주변 칸도 공개
        if adjacent_mines == 0:
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < game.rows and 0 <= nc < game.cols:
                        if [nr, nc] not in game.board_state['mines']:
                            stack.append((nr, nc))

    return revealed


def get_cell_info(game, row, col):
    """
    특정 칸의 정보를 반환

    Args:
        game (MinesweeperGame): 게임 인스턴스
        row (int): 행
        col (int): 열

    Returns:
        dict: 칸 정보 (is_mine, adjacent_mines, is_revealed, is_flagged)
    """
    return {
        'is_mine': [row, col] in game.board_state['mines'],
        'adjacent_mines': count_adjacent_mines(game, row, col),
        'is_revealed': [row, col] in game.board_state['revealed'],
        'is_flagged': [row, col] in game.board_state['flagged'],
    }
