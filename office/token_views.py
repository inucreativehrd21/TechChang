"""관리 화면 토큰 탭 — 칼럼별·단계별 토큰 사용량과 팩트체크 누수 신호(office.token_usage). 모델 호출은 없어요."""
from django.shortcuts import render

from .security import operator_required as admin_required

DAY_CHOICES = (7, 30, 90)


@admin_required
def token_usage(request):
    from . import token_usage as T
    from .views import TOPIC_LABEL
    try:
        days = int(request.GET.get('days', 30))
    except ValueError:
        days = 30
    days = days if days in DAY_CHOICES else 30
    data = T.overview(days=days)
    for c in data['columns']:
        c['topic_name'] = TOPIC_LABEL.get(c['draft'].topic, '')
        c['bars'] = [{'key': key, 'label': label, 'in': c['groups'].get(key, {}).get('in', 0)}
                     for key, label in T.GROUPS if c['groups'].get(key)]
    detail = None
    if request.GET.get('draft', '').isdigit():
        detail = T.detail(int(request.GET['draft'])) or None
    peak = max((g['in'] for g in data['groups']), default=0)
    for g in data['groups']:
        g['bar'] = round(g['in'] / peak * 100) if peak else 0
    return render(request, 'office/tokens.html', {'data': data, 'detail': detail, 'days': days,
                                                  'day_choices': DAY_CHOICES, 'groups': T.GROUPS})
