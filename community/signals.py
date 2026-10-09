"""Question 저장 → 검색엔진 알림(IndexNow).

글이 생기는 곳이 여러 군데라(회원 작성·수정, 연구팀 발행 office.pipeline/views, 자동 연재 명령,
관리자 수정) 각 지점에 넣지 않고 저장 신호 하나로 받는다. 조회수·투표는 .update()/M2M 이라
여기에 걸리지 않는다. 삭제(is_deleted)·잠금도 알린다 — 검색엔진이 다시 와서 빠진 걸 확인하게.
"""
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from .models import Question


@receiver(post_save, sender=Question, dispatch_uid='question_indexnow')
def question_saved(sender, instance, created, update_fields=None, **kwargs):
    from common.services import indexnow

    if not indexnow.enabled():
        return
    if created and not instance.is_indexable:
        return              # 처음부터 색인 대상이 아닌 짧은 글은 알릴 것이 없다
    url = 'https://techchang.com' + reverse('community:detail', kwargs={'question_id': instance.id})
    transaction.on_commit(lambda: indexnow.notify(url))
