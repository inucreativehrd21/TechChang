"""야구선수 키우기 — 사이트 활동 → 훈련 포인트(TP). 출석·댓글·답변은 쓰는 곳이 여러 군데라 저장 신호로 받는다.

칼럼 읽기는 신호가 없어(조회수는 .update()) 글 상세 뷰(base_views.detail)가 직접 부른다.
게임 쪽 오류가 글·댓글·출석을 막지 않게 모두 safe_award 로 부른다.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from common.models import DailyCheckIn

from . import rookie as R
from .models import Answer, Comment


@receiver(post_save, sender=DailyCheckIn, dispatch_uid='rookie_checkin')
def rookie_checkin(sender, instance, created, **kwargs):
    if created:
        R.safe_award(instance.user, 'checkin', ref=str(instance.check_in_date))


@receiver(post_save, sender=Comment, dispatch_uid='rookie_comment')
def rookie_comment(sender, instance, created, **kwargs):
    if created and len((instance.content or '').strip()) >= R.MIN_COMMENT:
        R.safe_award(instance.author, 'comment', ref=f'c{instance.pk}')


@receiver(post_save, sender=Answer, dispatch_uid='rookie_answer')
def rookie_answer(sender, instance, created, **kwargs):
    if created and not instance.is_ai and len((instance.content or '').strip()) >= R.MIN_COMMENT:
        R.safe_award(instance.author, 'comment', ref=f'a{instance.pk}')
