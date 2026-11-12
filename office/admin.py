from django.contrib import admin

from .models import ColumnDraft, Decision, Meeting, StageRun, WorkLog
from .security import is_operator


class OperatorAdminMixin:
    """Django 기본 관리자도 연구실 운영자 허용 목록을 우회하지 못한다."""
    def has_module_permission(self, request):
        return is_operator(request.user) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return is_operator(request.user) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return is_operator(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return is_operator(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return is_operator(request.user) and super().has_delete_permission(request, obj)


class StageRunInline(admin.TabularInline):
    """제작 단계 기록 — 읽기 전용 (무엇이 어떤 순서로 바뀌었는지 확인용)."""
    model = StageRun
    extra = 0
    can_delete = False
    fields = ('seq', 'stage', 'agent', 'kind', 'status', 'seconds', 'error', 'created_at')
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(StageRun)
class StageRunAdmin(OperatorAdminMixin, admin.ModelAdmin):
    list_display = ('created_at', 'run_id', 'seq', 'stage', 'agent', 'status', 'seconds')
    list_filter = ('stage', 'agent', 'status')
    readonly_fields = [f.name for f in StageRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DecisionInline(admin.TabularInline):
    model = Decision
    extra = 0
    fields = ('kind', 'topic', 'column_track', 'question', 'chosen_key', 'consumed_at')
    readonly_fields = ('consumed_at',)


@admin.register(Meeting)
class MeetingAdmin(OperatorAdminMixin, admin.ModelAdmin):
    list_display = ('week_start', 'held_at', 'status')
    inlines = [DecisionInline]


@admin.register(ColumnDraft)
class ColumnDraftAdmin(OperatorAdminMixin, admin.ModelAdmin):
    list_display = ('subject', 'topic', 'column_track', 'status', 'qa_score', 'revisions', 'created_at')
    list_filter = ('status', 'topic', 'column_track')
    readonly_fields = ('slot_key',)
    inlines = [StageRunInline]


@admin.register(WorkLog)
class WorkLogAdmin(OperatorAdminMixin, admin.ModelAdmin):
    list_display = ('created_at', 'agent', 'action', 'text')
    list_filter = ('agent', 'action')
from .models import HumanReview


@admin.register(HumanReview)
class HumanReviewAdmin(OperatorAdminMixin, admin.ModelAdmin):
    pass

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(OperatorAdminMixin, admin.ModelAdmin):
    list_display = ('sequence', 'created_at', 'action', 'actor_id', 'draft_id')
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
