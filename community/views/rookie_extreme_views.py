"""기능 플래그와 운영자 인증이 모두 있어야 열리는 익스트림 실험실이에요."""
import random

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .. import rookie_extreme as E
from .. import rookie_extreme_preview as Preview
from .. import rookie_lite as X
from .. import rookie_modes as Modes
from .. import rookie_world as W
from .. import rookie as R
from ..models import LiteCareer


@never_cache
@require_http_methods(['GET', 'POST'])
def preview(request):
    if not Modes.allowed(request.user):
        raise Http404
    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST.get('action')
                if action == 'create':
                    role = request.POST.get('role', '')
                    if role not in X.STYLES:
                        raise E.ExtremeError('투수 또는 타자를 골라 주세요.')
                    seed = int(request.POST.get('seed', '20261024'))
                    if not 0 <= seed <= 2**32 - 1:
                        raise ValueError
                    c = X.create(request.user, mode=Modes.EXTREME, name='시제품선수', role=role,
                                 position='SP' if role == 'pitcher' else 'SS', style=next(iter(X.STYLES[role])),
                                 region='서울', team='lg', rng=random.Random(seed))
                    c.flags['extreme']['seed'] = seed
                    c.save(update_fields=['flags'])
                else:
                    c = get_object_or_404(LiteCareer.objects.select_for_update(), pk=request.POST.get('career'),
                                          mode=Modes.EXTREME, user=request.user)
                    if action == 'event':
                        E.resolve(c.pk, request.user, request.POST.get('event_id', ''),
                                  request.POST.get('choice', ''), Preview.random_for(c, 'event'))
                    elif action == 'advance':
                        Preview.advance(c, request.POST.get('token', ''))
                    else:
                        raise E.ExtremeError('실험 동작을 다시 확인해 주세요.')
        except (E.ExtremeError, X.LiteError) as ex:
            messages.warning(request, str(ex))
        except (ValueError, TypeError):
            messages.warning(request, '선수와 시드 값을 다시 확인해 주세요.')
        return redirect('community:extreme_preview')
    mine = LiteCareer.objects.filter(user=request.user, mode=Modes.EXTREME)
    c = mine.filter(retired_at__isnull=True).first() or mine.order_by('-created_at').first()
    event = E.event_view(c) if c else None
    if event:
        event['has_contest'] = any(choice['contest'] for choice in event['choices'])
        for choice in event['choices']:
            choice['training_percent'] = round(choice['training'] * 100)
            choice['risk_percent'] = round(choice['risk'] * 100)
    state = ((c.flags or {}).get('extreme') or {}) if c else {}
    history = []
    for record in list(reversed(state.get('history', [])))[:8]:
        item = E.EVENTS[record['key']]
        picked = next(choice for choice in item['choices'] if choice['key'] == record['choice'])
        history.append(dict(record, title=item['title'], choice_label=picked['label'],
                            training_percent=round(record['training'] * 100), risk_percent=round(record['risk'] * 100)))
    labels = dict((key, label) for key, label, _weight in R.ROLES[c.role]['stats']) if c else {}
    response = render(request, 'community/rookie_extreme_preview.html', dict(
        c=c, event=event, rivals=state.get('rivals', []), history=history,
        turn_token=Preview.token(c) if c else '', league_name=W.short(c.league) if c else '',
        stats=[(labels.get(key, key), value) for key, value in c.stats.items()] if c else [],
        seasons=[dict(year=s.year, league=W.short(s.league), war=s.war, ovr_end=s.ovr_end)
                 for s in c.seasons.order_by('-year')[:5]] if c else [],
    ))
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
