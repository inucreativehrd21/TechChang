"""연구팀 칼럼이 저장되면 칼럼 지도를 갱신한다(office.digest).

발행 경로가 여러 군데라(새 칼럼 office.pipeline.publish_draft, 연재 series_pipeline.publish, 리메이크 제자리 갱신,
관리 화면 발행·수정) 각 지점에 넣지 않고 저장 신호 하나로 받는다(community.signals 의 IndexNow 와 같은 방식).
- 제목·본문이 요약했을 때와 같으면 아무것도 하지 않는다 — 조회수·투표는 .update() 라 여기 오지도 않는다.
- 바뀌었으면 커밋 뒤에 update_column_map 을 백그라운드로 띄운다. 요약은 모델 호출이라 저장 안에서 돌리지 않는다.
- 구독 경로만 쓴다(CLAUDE_CLI_FALLBACK=false) — 지도 요약에 유료 API 를 쓰지 않는다. 실패하면 다음 저장 때 함께 다시 한다.
"""
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from community.models import Question


@receiver(post_save, sender=Question, dispatch_uid='office_column_map')
def column_saved(sender, instance, created, update_fields=None, **kwargs):
    if instance.is_deleted or not instance.author_id:
        return
    if update_fields and not ({'subject', 'content'} & set(update_fields)):
        return
    if instance.author.username != Question.BOT_USERNAME:
        return
    from . import digest
    from .models import ColumnDigest
    current = ColumnDigest.objects.filter(question_id=instance.pk).values_list('content_hash', flat=True).first()
    if current == digest.content_hash(instance):
        return

    def launch():
        from .jobs import spawn
        spawn(['update_column_map', '--settle', '15'], by='column_saved', env={'CLAUDE_CLI_FALLBACK': 'false'})

    transaction.on_commit(launch)
