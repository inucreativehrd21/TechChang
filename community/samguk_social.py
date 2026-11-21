"""테크창 삼국지 — 방명록·친구·차단(설계 7.2). 장원 층이라 PC 전용 화면에서만 부른다.

- 방명록: 100자 이하, 장원마다 하루 1개. 하루 첫 방명록이면 양쪽 명성 +1(받는 쪽 하루 +10, 쓰는 쪽 하루 5회까지).
  링크는 막는다(광고 글). 주인은 숨기기·지우기, 누구나 신고(관리 화면에서 reported 로 본다).
- 친구: 신청 → 수락하면 양방향. 최대 100명. 차단하면 방명록·친구 신청이 막히고 맺어진 친구도 끊긴다.
- 탈퇴하면 User CASCADE 로 함께 지워진다(처리방침 점검은 설계 12장 9단계).
"""
from __future__ import annotations

import re

from django.db import transaction
from django.db.models import F, Q

from . import samguk as S
from .models import SamgukFriend, SamgukGuestbook, SamgukMember

GB_MAX = 100
GB_FAME = 1
GB_RECEIVE_CAP = 10
GB_WRITE_CAP = 5
FRIEND_MAX = 100
LINK_RE = re.compile(r'(https?://|www\.|\.[a-z]{2,}/)', re.I)


def blocked_between(a, b) -> bool:
    return SamgukFriend.objects.filter(status='blocked').filter(
        Q(from_user=a, to_user=b) | Q(from_user=b, to_user=a)).exists()


# ── 방명록 ──────────────────────────────────────────────────────────────
def guestbook_write(owner, author, text: str) -> dict:
    text = (text or '').strip()
    if owner == author:
        raise S.GameError('내 장원에는 방명록을 남길 수 없어요.')
    if not text:
        raise S.GameError('인사 글을 적어 주세요.')
    if len(text) > GB_MAX:
        raise S.GameError(f'방명록은 {GB_MAX}자까지예요.')
    if LINK_RE.search(text):
        raise S.GameError('방명록에는 링크를 남길 수 없어요.')
    if blocked_between(owner, author):
        raise S.GameError('이 장원에는 방명록을 남길 수 없어요.')
    day = S.game_day()
    with transaction.atomic():
        S.member(owner)
        S.member(author)
        if SamgukGuestbook.objects.filter(owner=owner, author=author, day=day).exists():
            raise S.GameError('이 장원에는 오늘 이미 인사를 남겼어요.')
        written_today = SamgukGuestbook.objects.filter(author=author, day=day).count()
        received_today = SamgukGuestbook.objects.filter(owner=owner, day=day).count()
        SamgukGuestbook.objects.create(owner=owner, author=author, text=text, day=day)
        fame = {'author': 0, 'owner': 0}
        if written_today < GB_WRITE_CAP:
            SamgukMember.objects.filter(user=author).update(fame=F('fame') + GB_FAME)
            fame['author'] = GB_FAME
        if received_today < GB_RECEIVE_CAP:
            SamgukMember.objects.filter(user=owner).update(fame=F('fame') + GB_FAME)
            fame['owner'] = GB_FAME
    return fame


def guestbook_list(owner, viewer, limit: int = 30) -> list:
    qs = SamgukGuestbook.objects.filter(owner=owner).select_related('author', 'author__profile')
    if viewer != owner:
        qs = qs.filter(hidden=False)
    return list(qs[:limit])


def guestbook_moderate(entry_id: int, user, how: str) -> None:
    entry = SamgukGuestbook.objects.filter(pk=entry_id).first()
    if entry is None:
        raise S.GameError('없는 글이에요.')
    if how == 'report':
        SamgukGuestbook.objects.filter(pk=entry.pk).update(reported=True)
        return
    if entry.owner != user and not user.is_staff:
        raise S.GameError('장원 주인만 할 수 있어요.')
    if how == 'hide':
        SamgukGuestbook.objects.filter(pk=entry.pk).update(hidden=not entry.hidden)
    elif how == 'delete':
        entry.delete()
    else:
        raise S.GameError('알 수 없는 요청이에요.')


# ── 친구 ───────────────────────────────────────────────────────────────
def friends(user) -> list:
    return [f.to_user for f in SamgukFriend.objects.filter(from_user=user, status='accepted')
            .select_related('to_user', 'to_user__profile')]


def friend_ids(user) -> set:
    return set(SamgukFriend.objects.filter(from_user=user, status='accepted').values_list('to_user_id', flat=True))


def incoming(user) -> list:
    return [f.from_user for f in SamgukFriend.objects.filter(to_user=user, status='pending')
            .select_related('from_user', 'from_user__profile')]


def relation(viewer, other) -> str:
    """none / pending_out / pending_in / friend / blocked(내가 막음) / blocked_by(상대가 막음)"""
    rows = {(f.from_user_id, f.to_user_id): f.status for f in SamgukFriend.objects.filter(
        Q(from_user=viewer, to_user=other) | Q(from_user=other, to_user=viewer))}
    mine, theirs = rows.get((viewer.pk, other.pk)), rows.get((other.pk, viewer.pk))
    if mine == 'blocked':
        return 'blocked'
    if theirs == 'blocked':
        return 'blocked_by'
    if mine == 'accepted':
        return 'friend'
    if mine == 'pending':
        return 'pending_out'
    if theirs == 'pending':
        return 'pending_in'
    return 'none'


def friend_request(user, other) -> str:
    if user == other:
        raise S.GameError('나와는 친구를 맺을 수 없어요.')
    rel = relation(user, other)
    if rel in ('blocked', 'blocked_by'):
        raise S.GameError('친구 신청을 할 수 없는 상대예요.')
    if rel == 'friend':
        return 'friend'
    if rel == 'pending_in':                                  # 상대가 먼저 신청했으면 바로 맺는다
        return friend_accept(user, other)
    if len(friend_ids(user)) >= FRIEND_MAX:
        raise S.GameError(f'친구는 {FRIEND_MAX}명까지예요.')
    SamgukFriend.objects.get_or_create(from_user=user, to_user=other, defaults={'status': 'pending'})
    return 'pending_out'


def friend_accept(user, other) -> str:
    with transaction.atomic():
        req = SamgukFriend.objects.select_for_update().filter(from_user=other, to_user=user, status='pending').first()
        if req is None:
            raise S.GameError('받은 친구 신청이 없어요.')
        if len(friend_ids(user)) >= FRIEND_MAX or len(friend_ids(other)) >= FRIEND_MAX:
            raise S.GameError(f'친구는 {FRIEND_MAX}명까지예요.')
        req.status = 'accepted'
        req.save(update_fields=['status'])
        SamgukFriend.objects.update_or_create(from_user=user, to_user=other, defaults={'status': 'accepted'})
    return 'friend'


def friend_remove(user, other) -> None:
    """친구 끊기·신청 취소·거절 — 양쪽 줄을 지운다(차단 줄은 그대로)."""
    SamgukFriend.objects.filter(Q(from_user=user, to_user=other) | Q(from_user=other, to_user=user)) \
        .exclude(status='blocked').delete()


def block(user, other) -> None:
    if user == other:
        raise S.GameError('나를 차단할 수는 없어요.')
    with transaction.atomic():
        SamgukFriend.objects.filter(from_user=other, to_user=user).exclude(status='blocked').delete()
        SamgukFriend.objects.update_or_create(from_user=user, to_user=other, defaults={'status': 'blocked'})


def unblock(user, other) -> None:
    SamgukFriend.objects.filter(from_user=user, to_user=other, status='blocked').delete()
