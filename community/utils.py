"""
커뮤니티 앱 유틸리티 함수들
"""

from django.db import transaction
from django.db.models import F
from common.models import Profile, PointHistory


def award_points(user, amount, description, reason=PointHistory.REASON_ADMIN):
    """
    사용자에게 포인트를 지급하고 히스토리를 기록합니다.

    Args:
        user: User 객체
        amount: 지급할 포인트 (양수)
        description: 포인트 지급 사유 설명
        reason: PointHistory의 REASON 선택지 (기본값: ADMIN)

    Returns:
        tuple: (profile, point_history) - 업데이트된 프로필과 생성된 히스토리
    """
    with transaction.atomic():
        profile, _ = Profile.objects.get_or_create(user=user)
        # F() 객체로 DB 레벨 원자연산 보장 (Race Condition 방지)
        profile.points = F('points') + amount
        profile.save(update_fields=['points'])
        profile.refresh_from_db()  # 메모리 값 동기화

        point_history = PointHistory.objects.create(
            user=user,
            amount=amount,
            reason=reason,
            description=description
        )

        return profile, point_history


def deduct_points(user, amount, description, reason=PointHistory.REASON_ADMIN, allow_negative=False):
    """
    사용자로부터 포인트를 차감하고 히스토리를 기록합니다.

    Args:
        user: User 객체
        amount: 차감할 포인트 (양수로 입력, 내부에서 음수로 변환)
        description: 포인트 차감 사유 설명
        reason: PointHistory의 REASON 선택지 (기본값: ADMIN)
        allow_negative: 음수 포인트 허용 여부 (기본값: False)

    Returns:
        tuple: (profile, point_history) - 업데이트된 프로필과 생성된 히스토리
    """
    with transaction.atomic():
        profile, _ = Profile.objects.get_or_create(user=user)

        if allow_negative:
            # F() 객체로 DB 레벨 원자연산 보장 (Race Condition 방지)
            profile.points = F('points') - amount
            profile.save(update_fields=['points'])
        else:
            # 음수 방지: 조건부 업데이트로 0 이하 방지
            # points >= amount인 경우: 차감
            # points < amount인 경우: 0으로 설정
            updated = Profile.objects.filter(id=profile.id, points__gte=amount).update(
                points=F('points') - amount
            )
            if not updated:
                Profile.objects.filter(id=profile.id).update(points=0)

        profile.refresh_from_db()  # 메모리 값 동기화

        point_history = PointHistory.objects.create(
            user=user,
            amount=-amount,  # 음수로 기록
            reason=reason,
            description=description
        )

        return profile, point_history


def adjust_points(user, amount, description, reason=PointHistory.REASON_ADMIN):
    """
    포인트를 조정합니다 (양수면 지급, 음수면 차감).

    Args:
        user: User 객체
        amount: 조정할 포인트 (양수 = 지급, 음수 = 차감)
        description: 포인트 조정 사유 설명
        reason: PointHistory의 REASON 선택지 (기본값: ADMIN)

    Returns:
        tuple: (profile, point_history) - 업데이트된 프로필과 생성된 히스토리
    """
    if amount > 0:
        return award_points(user, amount, description, reason)
    elif amount < 0:
        return deduct_points(user, abs(amount), description, reason)
    else:
        # amount가 0이면 아무것도 하지 않음
        profile, _ = Profile.objects.get_or_create(user=user)
        return profile, None


# ───────────────────────────── 답변 포인트 하루 상한(2026-11-24)
# 답변 1개 +20P 가 횟수 제한 없이 쌓여 짧은 답변을 반복하면 포인트(이모티콘 구매에 쓰임)·랭킹을 부풀릴 수 있었다.
# 하루(한국 시간) 답변으로 받는 포인트를 100P(답변 5개)까지로 둔다. 지급 기록 설명에 답변 번호를 남겨,
# 지울 때는 그 답변이 실제로 받은 만큼만 회수한다.
ANSWER_POINTS = 20
ANSWER_DAILY_CAP = 100
ANSWER_AWARD_PREFIX = '댓글 작성'          # 예전 기록 '댓글 작성: …' 과 새 기록 '댓글 작성 #12: …' 모두 이 말로 시작
ANSWER_CAP_SINCE = (2026, 11, 24)         # 이날 이전 답변은 번호 없는 예전 기록이라 지울 때 20P 를 회수한다


def answer_points_today(user) -> int:
    from django.db.models import Sum
    from django.utils import timezone
    return PointHistory.objects.filter(
        user=user, amount__gt=0, created_at__date=timezone.localdate(),
        description__startswith=ANSWER_AWARD_PREFIX).aggregate(s=Sum('amount'))['s'] or 0


def award_answer_points(user, answer) -> int:
    """답변 작성 포인트를 하루 상한 안에서 지급하고, 지급한 포인트를 돌려준다(0이면 오늘 상한에 닿음)."""
    with transaction.atomic():
        # 같은 사람이 동시에 답변을 올려도 상한을 넘지 않게 프로필 행을 잠가 순서대로 처리한다
        Profile.objects.get_or_create(user=user)
        Profile.objects.select_for_update().filter(user=user).first()
        amount = max(0, min(ANSWER_POINTS, ANSWER_DAILY_CAP - answer_points_today(user)))
        if amount:
            award_points(user, amount, f'{ANSWER_AWARD_PREFIX} #{answer.pk}: {answer.content[:30]}',
                         PointHistory.REASON_ADMIN)
    return amount


def answer_points_given(answer) -> int:
    """이 답변이 작성 때 받은 포인트(지울 때 회수할 양)."""
    from datetime import date
    from django.utils import timezone
    row = PointHistory.objects.filter(user_id=answer.author_id,
                                      description__startswith=f'{ANSWER_AWARD_PREFIX} #{answer.pk}:').first()
    if row:
        return row.amount
    created = timezone.localdate(answer.create_date) if answer.create_date else None
    return ANSWER_POINTS if created and created < date(*ANSWER_CAP_SINCE) else 0
