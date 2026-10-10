from django.apps import AppConfig


class OfficeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'office'
    verbose_name = '가상 연구실'

    def ready(self):
        from . import signals  # noqa: F401 — 칼럼 저장 → 칼럼 지도 갱신
