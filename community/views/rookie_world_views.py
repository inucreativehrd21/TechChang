"""모든 리그 일정·구단·가상 선수·공개 회원 기록을 읽는 화면이에요."""
from types import SimpleNamespace

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from .. import rookie as R
from .. import rookie_world as W
from .. import rookie_world_hub as Hub
from .. import rookie_universe as Universe
from ..game_visibility import rookie_hidden


def world_hub(request, edition='daily'):
    # 정식판에서만 전체 리그·구단을 제공해요. 라이트·익스트림의 커리어 세계는 유지해요.
    if edition in ('lite', 'extreme'):
        raise Http404
    from . import rookie_lite_views as Lite
    from ..models import LiteCareer
    if edition == 'daily':
        p = R.current(request.user.id) if request.user.is_authenticated else None
        home = reverse('community:rookie_home')
        game_label = '정식 모드'
    else:
        mode = getattr(request, 'rookie_mode', 'lite')
        if mode != edition:
            raise Http404
        mine = Lite._mine(request)
        p = mine.filter(retired_at__isnull=True).first() or mine.order_by('-created_at').first()
        if request.GET.get('career', '').isdigit():
            p = LiteCareer.objects.filter(pk=int(request.GET['career']), mode=mode).select_related('user').first()
            if p is None or (p.user_id is None and not Lite._is_mine(request, p)) or (p.user_id and rookie_hidden(p.user)):
                raise Http404
        p = p or SimpleNamespace(pk=0, flags={}, pending={'kind': 'plan'}, year=1, club='', league='hs')
        home = reverse('community:' + mode + '_home')
        game_label = '익스트림 모드' if mode == 'extreme' else '라이트 모드'
    league = request.GET.get('lg', 'kbo1')
    if league not in W.LEAGUES:
        league = 'kbo1'
    try:
        year = int(request.GET.get('year', ''))
    except (TypeError, ValueError):
        year = None
    data = Hub.world(p, league, year)
    if not data:
        raise Http404
    club = request.GET.get('club', '')
    if club not in data['clubs']:
        club = p.club if p is not None and p.league == league and p.club in data['clubs'] else data['clubs'][0]
    try:
        round_ = max(1, min(data['played'], int(request.GET.get('round', data['played']))))
    except (TypeError, ValueError):
        round_ = data['played']
    if not data['played']:
        round_ = 0
    roster = Hub.team_stats(data, club)
    return render(request, 'community/rookie_world.html', dict(
        home=home, edition=edition, game_label=game_label, data=data, lg=league, club=club,
        career=request.GET.get('career', ''), league_name=W.league(league)['name'], club_name=W.club_label(league, club),
        league_choices=[dict(code=code, name=W.league(code)['name']) for code in W.LEAGUES],
        clubs_by_league={code: [dict(code=item, name=W.club_label(code, item)) for item in Universe.teams(code)]
                         for code in W.LEAGUES},
        club_choices=[dict(code=code, name=W.club_label(league, code)) for code in data['clubs']],
        rounds=range(1, data['played'] + 1), round=round_,
        fixtures=[row for row in data['fixtures'] if row['round'] == round_],
        batters=[row for row in roster if row['role'] == 'batter'], pitchers=[row for row in roster if row['role'] == 'pitcher'],
        members=Hub.member_stats(league, club, data['year'], mode=edition),
    ))
