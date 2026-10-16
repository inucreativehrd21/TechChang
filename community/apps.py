from django.apps import AppConfig


class CommunityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'community'

    def ready(self):
        from . import signals  # noqa: F401 — Question 저장 → IndexNow
        from . import rookie_signals  # noqa: F401 — 출석·댓글·답변 → 야구선수 키우기 TP
