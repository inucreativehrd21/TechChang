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
