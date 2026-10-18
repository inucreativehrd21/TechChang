"""야구선수 키우기 라이트 화면 — 규칙은 community/rookie_lite.py.

/rookie/lite/            내 커리어(만들기 · 비시즌 · 시즌 결산 · 갈림길) — 단계는 LiteCareer.pending
/rookie/lite/new/        선수 만들기(POST)
/rookie/lite/act/        진행(POST: play · next · decide · quit)
/rookie/lite/hall/       명예의 전당(전체 · KBO · MLB · NPB · CPBL)
/rookie/lite/c/<id>/     커리어 페이지(공개)
모든 진행은 POST → 되돌아오기. 자바스크립트는 전광판 연출과 훈련 두 개 고르기 도움만 한다.
"""
import logging
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import rookie as R
from .. import rookie_league as L
from .. import rookie_lite as X
from .. import rookie_world as W
from ..game_visibility import is_hidden
from ..models import LiteCareer

logger = logging.getLogger(__name__)
HALL_TABS = [('', '전체'), ('kbo', 'KBO'), ('mlb', '미국'), ('npb', '일본'), ('cpbl', '대만')]


def _rng():
    return random.SystemRandom()


def _active(user):
    return LiteCareer.objects.filter(user=user, retired_at__isnull=True).first() if user.is_authenticated else None


def _grade(c) -> str:
    if W.is_pro(c.league):
        return ''
    if c.grade > W.last_grade(c.league):                       # 졸업 학년을 마치고 드래프트를 맞는 중
        return f"{'고교' if c.league == 'hs' else '대학'} 졸업 · 드래프트"
    return W.grade_label(c.league, c.grade)


def _identity(c) -> dict:
    stars = X.scout_stars(c)
    return {'c': c, 'team': {'name': W.club_label(c.league, c.club), 'color': W.club_color(c.league, c.club)},
            'league_name': W.league(c.league)['name'], 'league_short': W.short(c.league),
            'league_kind': R.league_kind(c.league), 'style_label': X.STYLES[c.role][c.style]['label'],
            'pos_label': L.POS_LABEL.get(c.position, dict(X.PIT_POSITIONS).get(c.position, '')),
            'grade_label': _grade(c),
            'stars': stars, 'star_note': X.STAR_NOTE[stars], 'star_range': range(5),
            'traits': [{'name': X.TRAITS[t][0], 'desc': X.TRAITS[t][1]} for t in (c.traits_seen or []) if t in X.TRAITS],
            'stat_rows': [{'key': k, 'label': lab, 'value': float(c.stats.get(k, 25)), 'shown': int(float(c.stats.get(k, 25))),
                           'bar': round(float(c.stats.get(k, 25)) / 99 * 100, 1)} for k, lab, _w in R.ROLES[c.role]['stats']],
            'salary': X.man(c.salary), 'earnings': X.man(c.earnings), 'want': R.TEAM.get(c.team, {})}


def _season_rows(c) -> list:
    rows = []
    for s in c.seasons.all():
        rows.append({'s': s, 'league': W.short(s.league), 'club': W.club_short(s.league, s.club),
                     'line': X._short(c.role, s.totals) if s.games else s.duty, 'kinds': [a['kind'] for a in s.awards]})
    return rows


def _base(request, section: str) -> dict:
    return {'section': section, 'regions': W.REGIONS, 'teams': [R.TEAM[c] for c, _n, _c in R.TEAMS],
            'styles': X.STYLES, 'bat_positions': L.POSITIONS, 'pit_positions': X.PIT_POSITIONS,
            'roles': R.ROLES}


def lite_home(request):
    ctx = _base(request, 'home')
    if not request.user.is_authenticated:
        ctx.update(mode='intro', hall=X.hall(limit=5))
        return render(request, 'community/rookie_lite.html', ctx)
    c = _active(request.user)
    if c is None:
        last = LiteCareer.objects.filter(user=request.user).order_by('-retired_at').first()
        ctx.update(mode='create', last=_identity(last) if last else None,
                   last_line=X.career_line(last) if last else None,
                   mine=list(LiteCareer.objects.filter(user=request.user, retired_at__isnull=False)[:10]),
                   default_name=(getattr(getattr(request.user, 'profile', None), 'nickname', '') or request.user.username)[:12])
        return render(request, 'community/rookie_lite.html', ctx)
    pend = c.pending or {}
    ctx.update(mode=pend.get('kind', 'plan'), **_identity(c), seasons=_season_rows(c))
    if pend.get('kind') == 'plan':
        ctx['duty'] = X.duty_for(c, W.level(c.league))[2]
        ctx.update(programs=[{'code': code, 'label': lab, 'hint': hint} for code, lab, hint, _e in X.PROGRAMS[c.role]],
                   intensity=[{'code': k, 'label': v[0], 'risk': int(round(v[2] * 100))} for k, v in X.INTENSITY.items()],
                   event=X.event_view(c, pend.get('event')))
    elif pend.get('kind') == 'review':
        s = c.seasons.filter(year=pend.get('year')).first()
        ctx.update(season=s, season_line=L.line_view(c.role, s.totals) if s and s.totals else None,
                   deltas=[{'label': lab, 'value': (s.deltas or {}).get(k, 0)} for k, lab, _w in R.ROLES[c.role]['stats']] if s else [],
                   season_league=W.league(s.league)['name'] if s else '', season_club=W.club_label(s.league, s.club) if s else '')
    elif pend.get('kind') == 'decision':
        ctx['decision'] = X.decision_view(c)
    return render(request, 'community/rookie_lite.html', ctx)


@login_required
@require_POST
def lite_new(request):
    try:
        number = int(request.POST.get('number') or 0)
    except ValueError:
        number = 0
    role = request.POST.get('role', '')
    try:
        X.create(request.user, name=request.POST.get('name', ''), role=role,
                 position=request.POST.get(f'position_{role}', ''), style=request.POST.get(f'style_{role}', ''),
                 region=request.POST.get('region', ''), team=request.POST.get('team', ''), number=number, rng=_rng())
    except X.LiteError as ex:
        messages.warning(request, str(ex))
    return redirect('community:lite_home')


@login_required
@require_POST
def lite_act(request):
    action = request.POST.get('action', '')
    rng = _rng()
    try:
        with transaction.atomic():
            c = LiteCareer.objects.select_for_update().filter(user=request.user, retired_at__isnull=True).first()
            if c is None:
                raise X.LiteError('진행 중인 커리어가 없습니다.')
            pend = c.pending or {}
            if action == 'play':
                if pend.get('kind') != 'plan':
                    raise X.LiteError('지금은 시즌을 시작할 차례가 아닙니다.')
                valid = [p[0] for p in X.PROGRAMS[c.role]]
                programs = [p for p in request.POST.getlist('program') if p in valid]
                if len(set(programs)) != 2:
                    raise X.LiteError('훈련 프로그램을 두 개 골라 주세요.')
                intensity = request.POST.get('intensity', '')
                if intensity not in X.INTENSITY:
                    raise X.LiteError('훈련 강도를 골라 주세요.')
                choice = request.POST.get('event_choice', '')
                if pend.get('event') and choice not in [k for k, _l, _h in X.EVENTS[pend['event']]['choices']]:
                    raise X.LiteError('이벤트에 어떻게 할지 골라 주세요.')
                X.run_season(c, sorted(set(programs)), intensity, choice, rng)
            elif action == 'next':
                X.next_season(c, rng)
            elif action == 'decide':
                text = X.decide(c, request.POST.get('what', ''), request.POST.get('choice', ''), rng,
                                school=request.POST.get('school', ''))
                c.save()
                if text:
                    messages.info(request, text)
            elif action == 'quit':
                if request.POST.get('confirm') != 'yes':
                    raise X.LiteError('은퇴하려면 확인 칸에 체크해 주세요.')
                messages.info(request, X.retire(c, '스스로'))
                c.save()
            else:
                raise X.LiteError('다시 시도해 주세요.')
    except X.LiteError as ex:
        messages.warning(request, str(ex))
    return redirect('community:lite_home')


def lite_hall(request):
    tab = request.GET.get('lg', '')
    tab = tab if tab in dict(HALL_TABS) else ''
    rows = X.hall(tab)
    return render(request, 'community/rookie_lite_hall.html',
                  dict(_base(request, 'hall'), tab=tab, tabs=HALL_TABS, rows=rows,
                       tab_name=dict(HALL_TABS)[tab]))


def lite_career(request, pk: int):
    c = get_object_or_404(LiteCareer.objects.select_related('user'), pk=pk)
    if is_hidden(c.user) and c.user_id != request.user.id:
        raise Http404
    awards = [dict(a, year=s.year, age=s.age, league=W.short(s.league)) for s in c.seasons.all() for a in s.awards]
    return render(request, 'community/rookie_lite_career.html',
                  dict(_base(request, 'hall'), **_identity(c), seasons=_season_rows(c), line=X.career_line(c),
                       awards=awards, is_me=c.user_id == request.user.id, peak=W.league(c.peak or 'hs')['name']))
