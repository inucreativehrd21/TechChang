from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse
from django.utils import timezone

from . import conf, services
from .forms import EventForm
from .ics import build_ics
from .layout import KIND_ORDER, build_month, items_on, month_dates
from .models import Event

WEEKDAY_KO = ['월', '화', '수', '목', '금', '토', '일']
UPCOMING_DAYS = 14
UPCOMING_LIMIT = 6
YEAR_RANGE = (2000, 2100)


def _month_url(d: date) -> str:
    return reverse('schedule:month_at', args=[d.year, d.month])


def _shift_month(year: int, month: int, delta: int) -> date:
    index = year * 12 + (month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def _parse_day(value: str) -> date:
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise Http404('날짜 형식이 올바르지 않습니다.')
    if not (YEAR_RANGE[0] <= d.year <= YEAR_RANGE[1]):
        raise Http404
    return d


def month_view(request, year=None, month=None):
    today = timezone.localdate()
    explicit = year is not None
    if not explicit:
        year, month = today.year, today.month
    if not (YEAR_RANGE[0] <= year <= YEAR_RANGE[1] and 1 <= month <= 12):
        raise Http404

    first = conf.get('FIRST_WEEKDAY')
    dates = month_dates(year, month, first)
    grid_start, grid_end = dates[0][0], dates[-1][-1]
    upcoming_end = today + timedelta(days=UPCOMING_DAYS)
    items = services.calendar_items(request.user, min(grid_start, today), max(grid_end, upcoming_end))
    weather, snapshot = services.latest_weather()
    weeks = build_month(year, month, items, first_weekday=first, today=today, weather=weather)

    upcoming = sorted((it for it in items if it.listed and today < it.start_date <= upcoming_end),
                      key=lambda it: (it.start_date, it.day_sort_key))[:UPCOMING_LIMIT]
    month_items = [it for it in items if it.start_date <= grid_end and it.end_date >= grid_start]
    # 모바일 목록: 여러 날 일정은 시작일(이전 달에 시작했으면 이달 첫날)에 한 번만 싣는다
    agenda = []
    first_of_month = date(year, month, 1)
    for week in weeks:
        for day in week.days:
            if day.in_month:
                on_day = [it for it in items_on(day.date, month_items)
                          if it.start_date == day.date or (day.date == first_of_month and it.start_date < day.date)]
                if on_day:
                    agenda.append((day, on_day))

    prev_month, next_month = _shift_month(year, month, -1), _shift_month(year, month, 1)
    context = {
        'year': year,
        'month': month,
        'month_label': f'{year}년 {month}월',
        'weekday_headers': [(WEEKDAY_KO[(first + i) % 7], (first + i) % 7 == 6) for i in range(7)],
        'weeks': weeks,
        'agenda': agenda,
        'today': today,
        'today_items': items_on(today, items),
        'today_weather': weather.get(today.isoformat()),
        'weather_snapshot': snapshot if weather else None,
        'upcoming': upcoming,
        'upcoming_days': UPCOMING_DAYS,
        'is_current_month': (year, month) == (today.year, today.month),
        'prev_url': _month_url(prev_month),
        'next_url': _month_url(next_month),
        'prev_label': f'{prev_month.month}월',
        'next_label': f'{next_month.month}월',
        'has_lab': any(it.kind == 'lab' for it in items),
        'noindex': explicit,
        'ics_url': request.build_absolute_uri(reverse('schedule:community_ics')),
        'kind_order': KIND_ORDER,
        'login_url': resolve_url(settings.LOGIN_URL),
    }
    return render(request, 'schedule/month.html', context)


def day_view(request, day):
    d = _parse_day(day)
    items = services.calendar_items(request.user, d, d)
    weather, snapshot = services.latest_weather()
    context = {
        'day': d,
        'items': items_on(d, items),
        'weather': weather.get(d.isoformat()),
        'weather_snapshot': snapshot if weather else None,
        'is_today': d == timezone.localdate(),
        'month_url': _month_url(d),
        'prev_url': reverse('schedule:day', args=[(d - timedelta(days=1)).isoformat()]),
        'next_url': reverse('schedule:day', args=[(d + timedelta(days=1)).isoformat()]),
        'noindex': True,
    }
    return render(request, 'schedule/day.html', context)


def event_detail(request, pk):
    event = get_object_or_404(Event.objects.select_related('owner'), pk=pk)
    if not event.is_visible_to(request.user):
        raise Http404
    return render(request, 'schedule/event_detail.html', {
        'event': event,
        'can_edit': event.can_edit(request.user),
        'month_url': _month_url(event.start_date),
        'noindex': not event.is_community,
    })


@login_required
def event_create(request):
    initial = {}
    raw = request.GET.get('date')
    if raw:
        try:
            initial['start_date'] = date.fromisoformat(raw)
        except ValueError:
            pass
    form = EventForm(request.POST or None, user=request.user, initial=initial)
    if request.method == 'POST' and form.is_valid():
        event = form.save(commit=False)
        event.owner = request.user
        if not request.user.is_staff:
            event.visibility = Event.PRIVATE
        event.save()
        messages.success(request, '일정을 추가했어요.')
        return redirect(_month_url(event.start_date))
    cancel_url = _month_url(initial.get('start_date') or timezone.localdate())
    return render(request, 'schedule/event_form.html', {'form': form, 'is_new': True, 'cancel_url': cancel_url,
                                                        'noindex': True})


def _editable(request, pk) -> Event:
    event = get_object_or_404(Event, pk=pk)
    if not event.is_visible_to(request.user):
        raise Http404
    if not event.can_edit(request.user):
        raise PermissionDenied
    return event


@login_required
def event_edit(request, pk):
    event = _editable(request, pk)
    form = EventForm(request.POST or None, instance=event, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, '변경 내용을 저장했어요.')
        return redirect(event.get_absolute_url())
    return render(request, 'schedule/event_form.html', {'form': form, 'event': event, 'is_new': False,
                                                        'cancel_url': event.get_absolute_url(), 'noindex': True})


@login_required
def event_delete(request, pk):
    event = _editable(request, pk)
    if request.method == 'POST':
        month_url = _month_url(event.start_date)
        event.delete()
        messages.success(request, '일정을 삭제했어요.')
        return redirect(month_url)
    return render(request, 'schedule/event_confirm_delete.html', {'event': event, 'noindex': True})


def community_ics(request):
    """커뮤니티 일정 + 공개 피드를 구독용 iCalendar 로. 개인 일정은 넣지 않는다."""
    today = timezone.localdate()
    anon = AnonymousUser()
    start, end = today - timedelta(days=60), today + timedelta(days=180)
    items = [it for it in services.calendar_items(anon, start, end) if it.public]
    items.sort(key=lambda it: (it.start_date, it.day_sort_key))
    body = build_ics(items, name=conf.get('CALENDAR_NAME'), host=request.get_host().split(':')[0],
                     absolute=request.build_absolute_uri)
    response = HttpResponse(body, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'inline; filename="myochil.ics"'
    response['Cache-Control'] = 'public, max-age=900'
    return response
