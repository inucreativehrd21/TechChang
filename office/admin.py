from django.contrib import admin

from .models import ColumnDraft, Decision, Meeting, StageRun, WorkLog


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
class StageRunAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'run_id', 'seq', 'stage', 'agent', 'status', 'seconds')
    list_filter = ('stage', 'agent', 'status')
    readonly_fields = [f.name for f in StageRun._meta.fields]

    def has_add_permission(self, request):
        return False


class DecisionInline(admin.TabularInline):
    model = Decision
    extra = 0
    fields = ('kind', 'topic', 'question', 'chosen_key', 'consumed_at')
    readonly_fields = ('consumed_at',)


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ('week_start', 'held_at', 'status')
    inlines = [DecisionInline]


@admin.register(ColumnDraft)
class ColumnDraftAdmin(admin.ModelAdmin):
    list_display = ('subject', 'topic', 'status', 'qa_score', 'revisions', 'created_at')
    list_filter = ('status', 'topic')
    inlines = [StageRunInline]


@admin.register(WorkLog)
class WorkLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'agent', 'action', 'text')
    list_filter = ('agent', 'action')
