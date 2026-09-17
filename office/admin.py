from django.contrib import admin

from .models import ColumnDraft, Decision, Meeting, WorkLog


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


@admin.register(WorkLog)
class WorkLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'agent', 'action', 'text')
    list_filter = ('agent', 'action')
