"""
숫자야구 게임 뷰

숫자야구는 4자리 중복되지 않는 숫자를 맞추는 게임입니다.
사용자는 최대 10번의 기회 안에 정답을 맞춰야 합니다.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Avg, Q, Min
from django.contrib.auth.models import User
import random
import logging

from ..models import NumberBaseballGame, NumberBaseballAttempt

logger = logging.getLogger(__name__)


@login_required
def baseball_start(request):
    """
    숫자야구 게임 시작 - 난이도 선택 페이지

    Returns:
        HttpResponse: 난이도 선택 페이지
    """
    return render(request, 'pybo/baseball_start.html')


@login_required
def baseball_create(request):
    """
    숫자야구 게임 생성

    선택한 난이도로 새 게임을 생성합니다.

    Returns:
        HttpResponse: 게임 플레이 페이지로 리다이렉트
    """
    difficulty = request.GET.get('difficulty', 'normal')

    # 진행중인 게임이 있으면 그걸로 이동
    existing_game = NumberBaseballGame.objects.filter(
        player=request.user,
        status='playing'
    ).first()

    if existing_game:
        return redirect('pybo:baseball_play', game_id=existing_game.id)

    # 난이도별 설정
    if difficulty == 'hard':
        max_attempts = 7
        time_limit = 300  # 5분
        inactivity_limit = 30  # 30초 동안 입력 없으면 자동 패배
    else:  # normal
        max_attempts = 10
        time_limit = 0  # 무제한
        inactivity_limit = 0  # 무제한

    # 4자리 중복없는 랜덤 숫자 생성
    numbers = random.sample(range(10), 4)
    secret = ''.join(map(str, numbers))

    game = NumberBaseballGame.objects.create(
        player=request.user,
        difficulty=difficulty,
        secret_number=secret,
        max_attempts=max_attempts,
        time_limit=time_limit,
        inactivity_limit=inactivity_limit,
        last_activity_time=timezone.now()
    )

    logger.info(f"New baseball game created by {request.user.username} (ID: {game.id}, difficulty: {difficulty})")
    return redirect('pybo:baseball_play', game_id=game.id)


@login_required
def baseball_play(request, game_id):
    """
    숫자야구 게임 플레이 페이지

    Args:
        game_id (int): 게임 ID

    Returns:
        HttpResponse: 게임 플레이 페이지
    """
    game = get_object_or_404(
        NumberBaseballGame.objects.select_related('player'),
        id=game_id,
        player=request.user
    )

    # prefetch로 시도 기록을 한 번에 가져오기 (N+1 쿼리 방지)
    attempts = game.attempt_records.all().order_by('create_date')

    context = {
        'game': game,
        'attempts': attempts,
        'remaining_attempts': game.max_attempts - game.attempts
    }
    return render(request, 'pybo/baseball_play.html', context)


@login_required
def baseball_guess(request, game_id):
    """
    숫자야구 추측 처리

    사용자의 추측을 받아 스트라이크/볼을 계산하고,
    게임 진행 상태를 업데이트합니다.

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 추측 결과 (strikes, balls, game_over 등)
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(
        NumberBaseballGame.objects.select_related('player'),
        id=game_id,
        player=request.user
    )

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    # 비활동 시간 체크 (하드모드)
    if game.inactivity_limit > 0 and game.last_activity_time:
        inactive_seconds = (timezone.now() - game.last_activity_time).total_seconds()
        if inactive_seconds >= game.inactivity_limit:
            game.status = 'timeout'
            game.end_date = timezone.now()
            game.save()
            return JsonResponse({
                'success': False,
                'game_over': True,
                'message': f'비활동 시간 초과! {game.inactivity_limit}초 동안 입력이 없어 게임이 종료되었습니다.',
                'secret': game.secret_number
            })

    guess = request.POST.get('guess', '').strip()

    # 입력 검증
    if not guess or len(guess) != 4:
        return JsonResponse({'success': False, 'message': '4자리 숫자를 입력해주세요.'})

    if not guess.isdigit():
        return JsonResponse({'success': False, 'message': '숫자만 입력 가능합니다.'})

    if len(set(guess)) != 4:
        return JsonResponse({'success': False, 'message': '중복되지 않은 숫자를 입력해주세요.'})

    # 스트라이크/볼 계산
    strikes = 0
    balls = 0
    secret = game.secret_number

    for i in range(4):
        if guess[i] == secret[i]:
            strikes += 1
        elif guess[i] in secret:
            balls += 1

    # 시도 기록
    with transaction.atomic():
        game.attempts += 1
        game.last_activity_time = timezone.now()  # 활동 시간 업데이트

        NumberBaseballAttempt.objects.create(
            game=game,
            guess_number=guess,
            strikes=strikes,
            balls=balls
        )

        # 하드모드: 연속 실패 페널티
        if game.difficulty == 'hard':
            if strikes == 0:
                game.consecutive_misses += 1
                # 3회 연속 0 strike시 시도 횟수 1회 차감
                if game.consecutive_misses >= 3:
                    game.attempts += 1
                    game.consecutive_misses = 0
                    penalty_message = " (⚠️ 3회 연속 실패! 시도 횟수 1회 차감)"
                else:
                    penalty_message = ""
            else:
                game.consecutive_misses = 0
                penalty_message = ""
        else:
            penalty_message = ""

        # 정답 확인
        if strikes == 4:
            game.status = 'won'
            game.end_date = timezone.now()
            game.save()

            time_bonus = ""
            if game.time_limit > 0:
                time_bonus = f" (소요 시간: {game.time_elapsed}초)"

            logger.info(f"User {request.user.username} won baseball game {game_id} - difficulty: {game.difficulty}, attempts: {game.attempts}")

            return JsonResponse({
                'success': True,
                'strikes': strikes,
                'balls': balls,
                'game_over': True,
                'won': True,
                'message': f'축하합니다! {game.attempts}번 만에 맞췄습니다!{time_bonus}',
                'secret': secret
            })

        # 기회 소진
        if game.attempts >= game.max_attempts:
            game.status = 'giveup'
            game.end_date = timezone.now()
            game.save()

            logger.info(f"User {request.user.username} lost baseball game {game_id} - difficulty: {game.difficulty}, attempts: {game.attempts}")

            return JsonResponse({
                'success': True,
                'strikes': strikes,
                'balls': balls,
                'game_over': True,
                'won': False,
                'message': f'게임 오버! 정답은 {secret}였습니다.',
                'secret': secret
            })

        game.save()

    return JsonResponse({
        'success': True,
        'strikes': strikes,
        'balls': balls,
        'attempts': game.attempts,
        'remaining': game.max_attempts - game.attempts,
        'penalty_message': penalty_message if 'penalty_message' in locals() else ""
    })


@login_required
def baseball_update_time(request, game_id):
    """
    게임 시간 업데이트

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 업데이트 결과 및 시간 초과 여부
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(NumberBaseballGame, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    time_elapsed = int(request.POST.get('time', 0))
    game.time_elapsed = time_elapsed

    # 전체 시간 제한 체크
    if game.time_limit > 0 and time_elapsed >= game.time_limit:
        game.status = 'timeout'
        game.end_date = timezone.now()
        game.save()

        logger.info(f"User {request.user.username} timed out baseball game {game_id} - difficulty: {game.difficulty}, time_elapsed: {time_elapsed}")

        return JsonResponse({
            'success': True,
            'timeout': True,
            'message': f'제한 시간 초과! 정답은 {game.secret_number}였습니다.',
            'secret': game.secret_number
        })

    # 비활동 시간 체크
    if game.inactivity_limit > 0 and game.last_activity_time:
        inactive_seconds = (timezone.now() - game.last_activity_time).total_seconds()
        if inactive_seconds >= game.inactivity_limit:
            game.status = 'timeout'
            game.end_date = timezone.now()
            game.save()

            logger.info(f"User {request.user.username} inactivity timeout baseball game {game_id} - difficulty: {game.difficulty}, inactive_seconds: {inactive_seconds}")

            return JsonResponse({
                'success': True,
                'timeout': True,
                'inactivity_timeout': True,
                'message': f'비활동 시간 초과! {game.inactivity_limit}초 동안 입력이 없어 게임이 종료되었습니다.',
                'secret': game.secret_number
            })

    game.save()
    return JsonResponse({
        'success': True,
        'timeout': False,
        'inactive_seconds': int((timezone.now() - game.last_activity_time).total_seconds()) if game.last_activity_time else 0,
        'inactivity_limit': game.inactivity_limit
    })


@login_required
def baseball_giveup(request, game_id):
    """
    숫자야구 게임 포기

    사용자가 게임을 포기하면 정답을 공개하고 게임을 종료합니다.

    Args:
        game_id (int): 게임 ID

    Returns:
        JsonResponse: 포기 결과 및 정답
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(NumberBaseballGame, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    game.status = 'giveup'
    game.end_date = timezone.now()
    game.save()

    logger.info(f"User {request.user.username} gave up on baseball game {game_id}")

    return JsonResponse({
        'success': True,
        'message': f'정답은 {game.secret_number}였습니다.',
        'secret': game.secret_number
    })


@login_required
def baseball_leaderboard(request):
    """
    숫자야구 게임 리더보드

    난이도별로 전체 사용자의 통계를 표시합니다.

    Returns:
        HttpResponse: 리더보드 페이지
    """
    # 난이도 필터
    difficulty = request.GET.get('difficulty', 'normal')
    if difficulty not in ['normal', 'hard']:
        difficulty = 'normal'

    # 디버깅: 난이도별 게임 수 확인
    total_games = NumberBaseballGame.objects.filter(difficulty=difficulty).count()
    won_games = NumberBaseballGame.objects.filter(difficulty=difficulty, status='won').count()
    logger.info(f"Baseball leaderboard - difficulty: {difficulty}, total_games: {total_games}, won_games: {won_games}")

    # Bulk 쿼리 최적화: N+1 쿼리 방지

    # 승리한 게임이 있는 사용자만 가져오기 (중복 제거를 확실히 하기 위해 list로 변환)
    users_with_wins = list(set(NumberBaseballGame.objects.filter(
        status='won',
        difficulty=difficulty
    ).values_list('player_id', flat=True)))

    logger.info(f"Baseball leaderboard - users_with_wins count: {len(users_with_wins)}, user_ids: {users_with_wins}")

    # 모든 사용자 정보를 한 번에 가져오기
    users_dict = {user.id: user for user in User.objects.select_related('profile').filter(id__in=users_with_wins)}

    # 모든 사용자의 통계를 한 번의 쿼리로 가져오기
    stats_qs = NumberBaseballGame.objects.filter(
        player_id__in=users_with_wins,
        difficulty=difficulty
    ).values('player_id').annotate(
        total_games=Count('id'),
        wins=Count('id', filter=Q(status='won')),
        avg_attempts=Avg('attempts', filter=Q(status='won')),
        best_attempts=Min('attempts', filter=Q(status='won'))
    )

    # 딕셔너리로 변환하여 O(1) 조회
    stats_dict = {stat['player_id']: stat for stat in stats_qs}

    leaderboard_data = []

    for user_id in users_with_wins:
        user = users_dict.get(user_id)
        if not user:
            continue

        stats = stats_dict.get(user_id, {})
        total_games = stats.get('total_games', 0)
        wins = stats.get('wins', 0)
        win_rate = (wins / total_games * 100) if total_games > 0 else 0

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
            'user': user,
            'display_name': display_name,
            'profile_image': profile_image,
            'total_games': total_games,
            'wins': wins,
            'win_rate': round(win_rate, 1),
            'avg_attempts': round(stats.get('avg_attempts', 0) or 0, 1),
            'best_attempts': stats.get('best_attempts', 999) or 999,
        })

    # 베스트 기록(최소 시도 횟수) 기준으로 정렬, 동점이면 승률 높은 순
    leaderboard_data.sort(key=lambda x: (x['best_attempts'], -x['win_rate']))

    # 랭킹 추가
    for rank, entry in enumerate(leaderboard_data, start=1):
        entry['rank'] = rank

    # 상위 100명만
    leaderboard_data = leaderboard_data[:100]

    # 디버그 정보 추가
    debug_info = {
        'total_games': total_games,
        'won_games': won_games,
        'users_with_wins_count': len(users_with_wins),
    }

    context = {
        'leaderboard': leaderboard_data,
        'total_players': len(leaderboard_data),
        'difficulty': difficulty,
        'debug_info': debug_info,
    }

    return render(request, 'pybo/baseball_leaderboard.html', context)
