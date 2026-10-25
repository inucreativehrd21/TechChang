from django.contrib import admin

from .models import Event, WeatherSnapshot


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'start_date', 'end_date', 'visibility', 'owner')
    list_filter = ('visibility',)
    search_fields = ('title', 'location', 'owner__username')
    date_hierarchy = 'start_date'
    raw_id_fields = ('owner',)


@admin.register(WeatherSnapshot)
class WeatherSnapshotAdmin(admin.ModelAdmin):
    list_display = ('region', 'announced_at', 'fetched_at')
    readonly_fields = ('region', 'announced_at', 'days', 'fetched_at')
