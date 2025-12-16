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
from django.db.models import Max, Sum, Count, Q
from django.contrib.auth.models import User
from django.core.cache import cache
from datetime import datetime
import random
import logging
import json

from ..models import Game2048

logger = logging.getLogger(__name__)


@login_required
def game2048_start(request):
    """
    2048 게임 시작 - 난이도 선택 페이지

    Returns:
        HttpResponse: 난이도 선택 페이지
    """
    return render(request, 'community/game2048_start.html')


@login_required
def game2048_create(request):
    """
    2048 게임 생성

    선택한 난이도로 새 게임을 생성합니다.

    Returns:
        HttpResponse: 게임 플레이 페이지로 리다이렉트
    """
    difficulty = request.GET.get('difficulty', 'normal')

    # 진행중인 게임이 있으면 그걸로 이동 (같은 난이도만)
    existing_game = Game2048.objects.filter(
        player=request.user,
        status='playing',
        difficulty=difficulty  # 같은 난이도의 게임만
    ).first()

    if existing_game:
        logger.info(f"User {request.user.username} resuming existing 2048 game {existing_game.id} - difficulty: {difficulty}")
        return redirect('community:game2048_play', game_id=existing_game.id)

    # 난이도별 설정
    if difficulty == 'hard':
        inactivity_limit = 15  # 15초 동안 입력 없으면 자동 패배
    else:
        inactivity_limit = 0  # 무제한

    # 새 게임 생성
    game = Game2048.objects.create(
        player=request.user,
        difficulty=difficulty,
        inactivity_limit=inactivity_limit,
        last_activity_time=timezone.now()
    )

    # 초기 타일 2개 추가
    add_random_tile(game)
    add_random_tile(game)
    game.save()

    logger.info(f"New 2048 game created by {request.user.username} (ID: {game.id}, difficulty: {difficulty})")
    return redirect('community:game2048_play', game_id=game.id)


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
        Game2048.objects.select_related('player'),
        id=game_id,
        player=request.user
    )

    # 세션에 게임 ID 캐싱 (이후 요청에서 세션 사용)
    request.session[f'game_2048_{game_id}'] = {
        'id': game.id,
        'board_state': game.board_state,
        'score': game.score,
        'best_score': game.best_score,
        'moves': game.moves,
        'status': game.status,
        'difficulty': game.difficulty,
        'inactivity_limit': game.inactivity_limit,
        'last_activity_time': game.last_activity_time.isoformat() if game.last_activity_time else None,
    }

    logger.info(f"User {request.user.username} playing 2048 game {game_id} - difficulty: {game.difficulty}, inactivity_limit: {game.inactivity_limit}")

    # 최고 점수 가져오기 (난이도별로 분리)
    best_score_result = Game2048.objects.filter(
        player=request.user,
        difficulty=game.difficulty  # 같은 난이도에서만
    ).aggregate(max_score=Max('best_score'))

    best_score = best_score_result['max_score'] or 0

    context = {
        'game': game,
        'best_score': best_score
    }
    return render(request, 'community/game2048_play.html', context)


@login_required
def game2048_move(request, game_id):
    """
    2048 게임 이동 처리 (세션 캐싱 최적화)

    사용자의 방향 입력을 받아 보드를 이동시키고,
    새 타일을 추가한 후 승패를 판정합니다.
    게임 진행 중에는 세션만 업데이트하고, 게임 종료 시에만 DB에 저장합니다.

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 이동 결과 (board, score, status 등)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    # 세션에서 게임 상태 가져오기 (캐시 우선)
    session_key = f'game_2048_{game_id}'
    game_data = request.session.get(session_key)

    if not game_data:
        # 세션에 없으면 DB에서 로드
        game = get_object_or_404(Game2048, id=game_id, player=request.user)
        game_data = {
            'id': game.id,
            'board_state': game.board_state,
            'score': game.score,
            'best_score': game.best_score,
            'moves': game.moves,
            'status': game.status,
            'difficulty': game.difficulty,
            'inactivity_limit': game.inactivity_limit,
            'last_activity_time': game.last_activity_time.isoformat() if game.last_activity_time else None,
            'last_request_ts': None,
        }

    if game_data['status'] != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    # 비활동 시간 체크 (하드모드)
    if game_data['inactivity_limit'] > 0 and game_data['last_activity_time']:
        # ISO 형식 문자열을 datetime으로 변환
        last_activity = datetime.fromisoformat(game_data['last_activity_time'])
        # timezone aware로 만들기
        if last_activity.tzinfo is None:
            last_activity = timezone.make_aware(last_activity)
        inactive_seconds = (timezone.now() - last_activity).total_seconds()
        if inactive_seconds >= game_data['inactivity_limit']:
            game_data['status'] = 'timeout'
            # 게임 종료 시에만 DB 저장
            game = Game2048.objects.get(id=game_id)
            game.status = 'timeout'
            game.end_date = timezone.now()
            game.save()
            del request.session[session_key]
            logger.info(f"User {request.user.username} timed out 2048 game {game_id} - difficulty: {game.difficulty}, score: {game_data['score']}")
            return JsonResponse({
                'success': False,
                'game_over': True,
                'status': 'timeout',
                'message': f'비활동 시간 초과! {game_data["inactivity_limit"]}초 동안 입력이 없어 게임이 종료되었습니다.'
            })

    direction = request.POST.get('direction')  # 'up', 'down', 'left', 'right'

    if direction not in ['up', 'down', 'left', 'right']:
        return JsonResponse({'success': False, 'message': '잘못된 방향입니다.'})

    # 서버 측 속도 제한 (초당 5회)
    rate_key = f'g2048_rate_{request.user.id}'
    current_count = cache.get(rate_key, 0)
    if current_count >= 5:
        return JsonResponse({
            'success': False,
            'message': '입력이 너무 빠릅니다. 잠시 후 다시 시도해주세요.',
            'cooldown': True
        })
    cache.set(rate_key, current_count + 1, timeout=1)

    # 요청 속도 제한 (과도한 입력 완화: 0.1초 간격)
    now_ts = timezone.now()
    last_ts = game_data.get('last_request_ts')
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts)
            if last_dt.tzinfo is None:
                last_dt = timezone.make_aware(last_dt)
            if (now_ts - last_dt).total_seconds() < 0.1:
                return JsonResponse({
                    'success': False,
                    'message': '입력이 너무 빠릅니다. 잠시만 기다려 주세요.',
                    'cooldown': True
                })
        except Exception:
            pass
    game_data['last_request_ts'] = now_ts.isoformat()

    # 보드 복사
    board_state = game_data['board_state']
    old_board = [row[:] for row in board_state]

    # 이동 처리
    moved, score_gained = move_board(board_state, direction)

    if not moved:
        return JsonResponse({'success': False, 'message': '이동할 수 없습니다.'})

    # 점수 업데이트 (세션에만)
    game_data['score'] += score_gained
    game_data['moves'] += 1
    game_data['last_activity_time'] = timezone.now().isoformat()
    game_data['board_state'] = board_state

    # 새 타일 추가
    add_random_tile(game_data)

    # 승리 확인 (2048 타일이 있는지)
    has_2048 = any(2048 in row for row in board_state)
    game_over = False

    if has_2048 and game_data['status'] == 'playing':
        game_data['status'] = 'won'
        game_over = True

        # 최고 점수 업데이트
        if game_data['score'] > game_data['best_score']:
            game_data['best_score'] = game_data['score']

        # 게임 종료 시 DB 저장
        game = Game2048.objects.get(id=game_id)
        game.board_state = board_state
        game.score = game_data['score']
        game.best_score = game_data['best_score']
        game.moves = game_data['moves']
        game.status = 'won'
        game.end_date = timezone.now()
        game.last_activity_time = timezone.now()
        game.save()

        del request.session[session_key]
        logger.info(f"User {request.user.username} won 2048 game {game_id} - difficulty: {game.difficulty}, score: {game_data['score']}, best_score: {game.best_score}")

    # 패배 확인 (더 이상 이동 불가능)
    elif not can_move(board_state):
        game_data['status'] = 'lost'
        game_over = True

        # 최고 점수 업데이트
        if game_data['score'] > game_data['best_score']:
            game_data['best_score'] = game_data['score']

        # 게임 종료 시 DB 저장
        game = Game2048.objects.get(id=game_id)
        game.board_state = board_state
        game.score = game_data['score']
        game.best_score = game_data['best_score']
        game.moves = game_data['moves']
        game.status = 'lost'
        game.end_date = timezone.now()
        game.last_activity_time = timezone.now()
        game.save()

        del request.session[session_key]
        logger.info(f"User {request.user.username} lost 2048 game {game_id} - difficulty: {game.difficulty}, score: {game_data['score']}, best_score: {game.best_score}")
    else:
        # 게임 진행 중: 세션만 업데이트 (DB 저장 안 함)
        request.session[session_key] = game_data
        request.session.modified = True

    return JsonResponse({
        'success': True,
        'board': board_state,
        'score': game_data['score'],
        'score_gained': score_gained,
        'status': game_data['status'],
        'game_over': game_over
    })


@login_required
def game2048_submit_final(request, game_id):
    """
    최종 점수만 서버에 반영하는 엔드포인트 (클라이언트 배치 전송용)

    클라이언트에서 게임 종료 후 최종 점수와 보드 상태를 전달할 때 사용.
    서버는 보드 형태/점수 유효성만 검증하며, 추가 무결성 검증은 추후 강화 가능.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(Game2048, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})

    final_score = int(payload.get('score', 0))
    moves = int(payload.get('moves', 0))
    status = payload.get('status', 'lost')
    board_state = payload.get('board_state')

    # 기본 검증
    if final_score < 0 or final_score > 10_000_000:
        return JsonResponse({'success': False, 'message': '점수 값이 비정상입니다.'})
    if status not in ['won', 'lost', 'timeout']:
        return JsonResponse({'success': False, 'message': '잘못된 상태입니다.'})

    # 보드 형태 검증 (4x4 숫자)
    def is_valid_board(board):
        if not isinstance(board, list) or len(board) != 4:
            return False
        for row in board:
            if not isinstance(row, list) or len(row) != 4:
                return False
            for cell in row:
                if not isinstance(cell, int) or cell < 0:
                    return False
        return True

    if not is_valid_board(board_state):
        return JsonResponse({'success': False, 'message': '보드 상태가 올바르지 않습니다.'})

    # 게임 업데이트
    game.board_state = board_state
    game.score = final_score
    if final_score > game.best_score:
        game.best_score = final_score
    game.moves = moves if moves > game.moves else game.moves
    game.status = status
    game.end_date = timezone.now()
    game.last_activity_time = timezone.now()
    game.save()

    return JsonResponse({'success': True, 'message': '최종 점수가 저장되었습니다.'})


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

    # 새 게임 생성 (이전 게임의 난이도 설정 유지)
    new_game = Game2048.objects.create(
        player=request.user,
        best_score=game.best_score,
        difficulty=game.difficulty,
        inactivity_limit=game.inactivity_limit,
        last_activity_time=timezone.now()
    )

    # 초기 타일 2개 추가
    add_random_tile(new_game)
    add_random_tile(new_game)
    new_game.save()

    return JsonResponse({
        'success': True,
        'redirect_url': f'/pybo/2048/{new_game.id}/'
    })


@login_required
def game2048_check_inactivity(request, game_id):
    """
    2048 게임 비활동 시간 체크

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 비활동 상태 및 시간 초과 여부
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(Game2048, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    # 비활동 시간 체크
    if game.inactivity_limit > 0 and game.last_activity_time:
        inactive_seconds = (timezone.now() - game.last_activity_time).total_seconds()
        if inactive_seconds >= game.inactivity_limit:
            game.status = 'timeout'
            game.end_date = timezone.now()
            game.save()

            return JsonResponse({
                'success': True,
                'timeout': True,
                'message': f'비활동 시간 초과! {game.inactivity_limit}초 동안 입력이 없어 게임이 종료되었습니다.'
            })

    return JsonResponse({
        'success': True,
        'timeout': False,
        'inactive_seconds': int((timezone.now() - game.last_activity_time).total_seconds()) if game.last_activity_time else 0,
        'inactivity_limit': game.inactivity_limit
    })


def game2048_leaderboard(request):
    """
    2048 게임 리더보드

    난이도별로 전체 사용자의 최고 점수를 기준으로 랭킹을 표시합니다.

    Returns:
        HttpResponse: 리더보드 페이지
    """
    # 난이도 필터
    difficulty = request.GET.get('difficulty', 'normal')
    if difficulty not in ['normal', 'hard']:
        difficulty = 'normal'

    # 디버깅: 난이도별 게임 수 확인
    total_games = Game2048.objects.filter(difficulty=difficulty).count()
    won_games = Game2048.objects.filter(difficulty=difficulty, status='won').count()
    logger.info(f"2048 leaderboard - difficulty: {difficulty}, total_games: {total_games}, won_games: {won_games}")

    # 사용자별 최고 점수 서브쿼리 (난이도별)
    user_best_scores = Game2048.objects.filter(
        player=models.OuterRef('pk'),
        difficulty=difficulty
    ).order_by('-best_score').values('best_score')[:1]

    # 최고 점수가 있는 사용자만 가져오기
    try:
        top_players = User.objects.annotate(
            top_score=models.Subquery(user_best_scores)
        ).filter(
            top_score__isnull=False,
            top_score__gt=0
        ).select_related('profile').order_by('-top_score')[:100]
    except Exception:
        # profile이 없는 경우를 위해 select_related 제외
        top_players = User.objects.annotate(
            top_score=models.Subquery(user_best_scores)
        ).filter(
            top_score__isnull=False,
            top_score__gt=0
        ).order_by('-top_score')[:100]

    # 각 사용자의 게임 통계 가져오기 (난이도별) - Bulk 쿼리 최적화
    # 모든 사용자의 통계를 한 번의 쿼리로 가져오기
    player_ids = [user.id for user in top_players]
    logger.info(f"2048 leaderboard - top_players count: {len(player_ids)}, player_ids: {player_ids}")
    stats_qs = Game2048.objects.filter(
        player_id__in=player_ids,
        difficulty=difficulty
    ).values('player_id').annotate(
        total_games=Count('id'),
        wins=Count('id', filter=Q(status='won')),
        cumulative_score=Sum('best_score')
    )

    # 딕셔너리로 변환하여 O(1) 조회
    stats_dict = {stat['player_id']: stat for stat in stats_qs}

    leaderboard_data = []
    for rank, user in enumerate(top_players, start=1):
        stats = stats_dict.get(user.id, {
            'total_games': 0,
            'wins': 0,
            'cumulative_score': 0
        })

        try:
            display_name = user.profile.display_name
            profile_image = user.profile.profile_image.url if user.profile.profile_image else None
        except AttributeError:
            display_name = user.username
            profile_image = None
        except Exception:
            display_name = user.username
            profile_image = None

        leaderboard_data.append({
            'rank': rank,
            'user': user,
            'display_name': display_name,
            'profile_image': profile_image,
            'best_score': user.top_score,
            'cumulative_score': stats.get('cumulative_score', 0) or 0,
            'total_games': stats.get('total_games', 0),
            'wins': stats.get('wins', 0),
        })

    # 디버그 정보 추가
    debug_info = {
        'total_games': total_games,
        'won_games': won_games,
        'top_players_count': len(player_ids),
    }

    context = {
        'leaderboard': leaderboard_data,
        'total_players': len(leaderboard_data),
        'difficulty': difficulty,
        'debug_info': debug_info,
    }

    return render(request, 'community/game2048_leaderboard.html', context)


# ========== 게임 로직 헬퍼 함수 ==========

def add_random_tile(game):
    """
    빈 칸에 랜덤 타일(2 또는 4) 추가

    Args:
        game (Game2048 또는 dict): 게임 인스턴스 또는 게임 데이터 딕셔너리

    Note:
        90% 확률로 2, 10% 확률로 4가 생성됩니다.
    """
    # 딕셔너리와 모델 인스턴스 모두 지원
    if isinstance(game, dict):
        board_state = game['board_state']
    else:
        board_state = game.board_state

    empty_cells = []
    for i in range(4):
        for j in range(4):
            if board_state[i][j] == 0:
                empty_cells.append((i, j))

    if empty_cells:
        i, j = random.choice(empty_cells)
        board_state[i][j] = 2 if random.random() < 0.9 else 4


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
