"""숫자야구 게임 뷰"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
import random
import logging

from ..models import NumberBaseballGame, NumberBaseballAttempt

logger = logging.getLogger(__name__)


@login_required
def baseball_start(request):
    """숫자야구 게임 시작"""
    # 진행중인 게임이 있으면 그걸로 이동
    existing_game = NumberBaseballGame.objects.filter(
        player=request.user,
        status='playing'
    ).first()

    if existing_game:
        return redirect('pybo:baseball_play', game_id=existing_game.id)

    # 4자리 중복없는 랜덤 숫자 생성
    numbers = random.sample(range(10), 4)
    secret = ''.join(map(str, numbers))

    game = NumberBaseballGame.objects.create(
        player=request.user,
        secret_number=secret
    )

    return redirect('pybo:baseball_play', game_id=game.id)


@login_required
def baseball_play(request, game_id):
    """숫자야구 게임 플레이"""
    game = get_object_or_404(NumberBaseballGame, id=game_id, player=request.user)
    attempts = game.attempt_records.all()

    context = {
        'game': game,
        'attempts': attempts,
        'remaining_attempts': game.max_attempts - game.attempts
    }
    return render(request, 'pybo/baseball_play.html', context)


@login_required
def baseball_guess(request, game_id):
    """숫자야구 추측"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(NumberBaseballGame, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

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

        NumberBaseballAttempt.objects.create(
            game=game,
            guess_number=guess,
            strikes=strikes,
            balls=balls
        )

        # 정답 확인
        if strikes == 4:
            game.status = 'won'
            game.end_date = timezone.now()
            game.save()

            return JsonResponse({
                'success': True,
                'strikes': strikes,
                'balls': balls,
                'game_over': True,
                'won': True,
                'message': f'축하합니다! {game.attempts}번 만에 맞췄습니다!',
                'secret': secret
            })

        # 기회 소진
        if game.attempts >= game.max_attempts:
            game.status = 'giveup'
            game.end_date = timezone.now()
            game.save()

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
        'remaining': game.max_attempts - game.attempts
    })


@login_required
def baseball_giveup(request, game_id):
    """숫자야구 포기"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST 요청만 허용됩니다.'})

    game = get_object_or_404(NumberBaseballGame, id=game_id, player=request.user)

    if game.status != 'playing':
        return JsonResponse({'success': False, 'message': '이미 종료된 게임입니다.'})

    game.status = 'giveup'
    game.end_date = timezone.now()
    game.save()

    return JsonResponse({
        'success': True,
        'message': f'정답은 {game.secret_number}였습니다.',
        'secret': game.secret_number
    })
