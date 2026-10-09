"""회원 탈퇴 — 개인정보를 즉시 파기하고 계정을 '탈퇴한 회원'으로 익명화한다.

예전 탈퇴는 is_active=False 로 막고 이메일·아이디 앞에 'deleted_' 만 붙여 원래 값을 그대로 보관했다.
처리방침의 "탈퇴 시 지체 없이 파기"(「개인정보 보호법」 제21조)와 맞지 않아 2026-10-09 에 바꿨다.

User 행 자체를 지우지 않는 이유: 질문·답변·게임 기록이 author FK(CASCADE)로 묶여 있어,
지우면 다른 회원이 단 답변까지 함께 사라진다. 대신 개인을 알아볼 수 있는 값을 모두 비운다.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

WITHDRAWN_PREFIX = 'withdrawn_'


def is_withdrawn(user) -> bool:
    return user.username.startswith(WITHDRAWN_PREFIX)


def _delete_file(field):
    try:
        if field:
            field.delete(save=False)
    except Exception:  # noqa: BLE001 — 파일이 이미 없어도 나머지 파기는 계속한다
        logger.warning('탈퇴 파일 삭제 실패', exc_info=True)


@transaction.atomic
def withdraw(user) -> None:
    """user 의 개인정보를 파기하고 비활성 익명 계정으로 바꾼다. 여러 번 불러도 안전하다."""
    from common.models import EmailVerification, KakaoUser, Profile
    from community.models import Portfolio, PortfolioCollection

    now = timezone.now()
    old_email = user.email or ''
    old_username = user.username

    # 1) 작성한 질문·답변은 비공개(삭제 처리) — 기존 정책 유지
    user.author_question.filter(is_deleted=False).update(is_deleted=True, deleted_date=now)
    user.author_answer.filter(is_deleted=False).update(is_deleted=True, deleted_date=now)

    # 2) 프로필·포트폴리오 — 회원이 입력한 개인정보 덩어리
    profile = Profile.objects.filter(user=user).first()
    if profile:
        _delete_file(profile.profile_image)
        profile.profile_image = None
        profile.nickname = None
        profile.save()
    for pf in Portfolio.objects.filter(user=user):
        _delete_file(pf.profile_image)
        _delete_file(pf.hero_background_image)
        pf.delete()
    PortfolioCollection.objects.filter(user=user).delete()

    # 3) 소셜 로그인 연동 정보(카카오 회원번호·토큰·닉네임·이메일)
    if old_username.startswith('kakao_'):
        kakao_id = old_username.removeprefix('kakao_')
        if kakao_id.isdigit():
            KakaoUser.objects.filter(kakao_id=int(kakao_id)).delete()
    try:
        from allauth.socialaccount.models import SocialAccount
        SocialAccount.objects.filter(user=user).delete()
    except Exception:  # noqa: BLE001 — allauth 미설치 환경
        pass
    try:
        from allauth.account.models import EmailAddress
        EmailAddress.objects.filter(user=user).delete()
    except Exception:  # noqa: BLE001
        pass
    if old_email:
        EmailVerification.objects.filter(email=old_email).delete()

    # 4) 계정 익명화 — 로그인 불가, 다시 쓸 수 없는 고유 아이디
    user.username = f'{WITHDRAWN_PREFIX}{user.id}'
    user.email = ''
    user.first_name = ''
    user.last_name = ''
    user.is_active = False
    user.set_unusable_password()
    user.save()
    logger.info('회원 탈퇴 처리: user_id=%s', user.id)
