"""테크창 삼국지 — 사이트 활동 → 추가 군령(설계 3.1). 야구 TP(rookie_signals)와 같은 자리에서 받는다.

출석은 '달력 날짜 D 의 출석 = 게임일 D' 로 기록한다(06:00 경계와 자정 경계가 어긋나도 하루 한 번).
칼럼 읽기는 신호가 없어 글 상세 뷰(base_views.detail)가 samguk.safe_credit 을 직접 부른다.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from common.models import DailyCheckIn

from . import samguk as S
from .models import Answer, Comment


@receiver(post_save, sender=DailyCheckIn, dispatch_uid='samguk_checkin')
def samguk_checkin(sender, instance, created, **kwargs):
    if created:
        S.safe_credit(instance.user, 'checkin', ref=str(instance.check_in_date), day=instance.check_in_date)


@receiver(post_save, sender=Comment, dispatch_uid='samguk_comment')
def samguk_comment(sender, instance, created, **kwargs):
    if created and len((instance.content or '').strip()) >= S.MIN_COMMENT:
        S.safe_credit(instance.author, 'comment', ref=f'c{instance.pk}')


@receiver(post_save, sender=Answer, dispatch_uid='samguk_answer')
def samguk_answer(sender, instance, created, **kwargs):
    if created and not instance.is_ai and len((instance.content or '').strip()) >= S.MIN_COMMENT:
        S.safe_credit(instance.author, 'comment', ref=f'a{instance.pk}')
