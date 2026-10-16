"""야구선수 키우기 화면 — 성장 규칙은 community/rookie.py, 리그·기록·시상은 community/rookie_league.py.

화면 넷 + 선수 페이지: 내 선수(/rookie/) · 리그(/rookie/league/) · 시상식(/rookie/awards/) · 기록실(/rookie/records/)
· 선수(/rookie/p/<id>/). 훈련은 fetch 로 보내면 플레이 영역 HTML 을 통째로 돌려받아 갈아 끼운다
(규칙을 JS 에 다시 쓰지 않으려고). 자바스크립트가 없으면 같은 폼이 그대로 POST → 되돌아오기로 동작한다.
"""
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import rookie as R
from .. import rookie_league as L
from ..game_visibility import is_hidden, visible
from ..models import RookieAward, RookieGame, RookiePlayer, RookieSeason, RookieSeasonStat

logger = logging.getLogger(__name__)


def _ajax(request) -> bool:
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _catch_up():
    """밤 cron 이 빠졌을 때 화면을 연 사람이 전날 경기를 대신 치르게 한다(이미 치렀으면 할 일 없음)."""
    try:
        L.advance()
    except Exception:  # noqa: BLE001 — 경기 진행 실패가 화면을 막지 않게
        logger.warning('야구선수 키우기 경기 진행 실패', exc_info=True)


def _base_ctx(request, section: str) -> dict:
    return {'section': section, 'season_now': L.season_state(),
            'teams': [R.TEAM[c] for c, _n, _c in R.TEAMS], 'roles': R.ROLES, 'earn': R.EARN, 'tiers': R.TIERS,
            'welcome': R.WELCOME_TP, 'cost': R.TRAIN_COST, 'daily_max': R.DAILY_MAX, 'fatigue_at': R.FATIGUE_AT,
            'focus_bonus': int(round((R.FOCUS_BONUS - 1) * 100)), 'positions': L.POSITIONS,
            'opp_first': L.opp_levels(2),
            'my_id': RookiePlayer.objects.filter(user_id=request.user.id).values_list('id', flat=True).first()}


def _play_ctx(request, p) -> dict:
    return dict(_base_ctx(request, 'home'), mode='play', **R.dashboard(p))


def _seasons():
    return list(RookieSeason.objects.filter(start__lte=timezone.localdate()).order_by('-number'))


def _pick_season(request, seasons, *, closed_only=False):
    pool = [s for s in seasons if s.closed] if closed_only else seasons
    try:
        n = int(request.GET.get('season', ''))
    except ValueError:
        n = None
    return next((s for s in pool if s.number == n), pool[0] if pool else None)


# ───────────────────────────── 내 선수
def rookie_home(request):
    _catch_up()
    if not request.user.is_authenticated:
        return render(request, 'community/rookie.html', dict(_base_ctx(request, 'home'), mode='intro'))
    with transaction.atomic():
        p = R.locked(request.user)
        if p is not None:
            R.settle(p)
    if p is None:
        profile = getattr(request.user, 'profile', None)
        name = (getattr(profile, 'nickname', '') or request.user.username)[:12]
        return render(request, 'community/rookie.html', dict(_base_ctx(request, 'home'), mode='create',
                                                             default_name=name))
    ctx = _play_ctx(request, p)
    ctx['test'] = request.session.pop('rookie_test', None)
    return render(request, 'community/rookie.html', ctx)


@login_required
@require_POST
def rookie_create(request):
    if RookiePlayer.objects.filter(user=request.user).exists():
        return redirect('community:rookie_home')
    role = request.POST.get('role', '')
    try:
        number = int(request.POST.get('number') or 0)
    except ValueError:
        number = 0
    try:
        p = R.create(request.user, name=request.POST.get('name', ''), role=role, team=request.POST.get('team', ''),
                     number=number, focus=request.POST.get(f'focus_{role}', ''),
                     position=request.POST.get('position', ''))
    except R.GameError as ex:
        messages.warning(request, str(ex))
        return redirect('community:rookie_home')
    messages.success(request, f"{p.name} 선수, {R.TEAM[p.team]['name']} 육성군 입단! 입단 보너스 {R.WELCOME_TP} TP로 첫 훈련을 해 보세요.")
    return redirect('community:rookie_home')


@login_required
@require_POST
def rookie_train(request):
    try:
        r = R.train(request.user, request.POST.get('stat', ''), request.POST.get('times', 1))
    except (R.GameError, ValueError) as ex:
        if _ajax(request):
            return JsonResponse({'ok': False, 'message': str(ex)}, status=400)
        messages.warning(request, str(ex))
        return redirect('community:rookie_home')
    toast = f"{r['label']} {r['before']:.1f} → {r['after']:.1f}"
    if r['great']:
        toast += f" · 대성공 {r['great']}회!"
    if r['tired']:
        toast += ' · 피로로 효율 절반'
    if not _ajax(request):
        messages.success(request, toast)
        return redirect('community:rookie_home')
    html = render_to_string('community/games/_rookie_play.html', _play_ctx(request, r['player']), request=request)
    return JsonResponse({'ok': True, 'html': html, 'toast': toast, 'great': bool(r['great']), 'stat': r['stat']})


@login_required
@require_POST
def rookie_test(request):
    try:
        r = R.promotion_test(request.user)
    except R.GameError as ex:
        messages.warning(request, str(ex))
        return redirect('community:rookie_home')
    request.session['rookie_test'] = {'passed': r['passed'], 'tier_name': r['tier_name'], 'won': r['won'],
                                      'games': r['games'], 'total': R.TEST_GAMES}
    return redirect('community:rookie_home')


@login_required
@require_POST
def rookie_retire(request):
    if request.POST.get('confirm') != 'yes':
        messages.warning(request, '은퇴하려면 확인 칸에 체크해 주세요.')
        return redirect('community:rookie_home')
    if R.retire(request.user):
        messages.info(request, '은퇴했습니다. 시즌 기록과 수상은 기록실에 남습니다. 새 선수로 다시 시작할 수 있습니다.')
    return redirect('community:rookie_home')


# ───────────────────────────── 선수 페이지(공개)
def rookie_player(request, pk: int):
    p = get_object_or_404(RookiePlayer.objects.select_related('user'), pk=pk)
    if is_hidden(p.user) and p.user_id != request.user.id:
        raise Http404
    _catch_up()
    career = list(RookieSeasonStat.objects.filter(player=p).select_related('season').order_by('-season__number', '-league'))
    games = [L.game_view(g, p.team, p.role) for g in RookieGame.objects.filter(player=p).order_by('-day', '-no')[:20]]
    ctx = dict(_base_ctx(request, 'league'), p=p, team=R.TEAM.get(p.team, {}), role_label=R.ROLES[p.role]['label'],
               pos_label=L.POS_LABEL.get(p.position, ''), tier_name=R.TIERS[p.tier]['name'],
               focus_label=dict((k, lab) for k, lab, _w in R.ROLES[p.role]['stats']).get(p.focus, ''),
               title=R.title(p.role, p.tier, p.ovr), stats=R.stat_rows(p), career=L.season_lines(career),
               games=games, trophies=list(RookieAward.objects.filter(player=p).select_related('season')
                                          .order_by('-season__number', 'order')),
               is_me=p.user_id == request.user.id)
    return render(request, 'community/rookie_player.html', ctx)


# ───────────────────────────── 리그
def rookie_league(request):
    _catch_up()
    R.settle_all()                      # 쉬는 선수를 순위에 그대로 두지 않게(밤 cron 이 돌았으면 할 일 없음)
    tab = request.GET.get('tab') if request.GET.get('tab') in ('leaders', 'players', 'teams') else 'leaders'
    seasons = _seasons()
    season = _pick_season(request, seasons)
    lg = 1 if request.GET.get('lg') == '1' else 2
    role = request.GET.get('role', '')
    ctx = dict(_base_ctx(request, 'league'), tab=tab, seasons=seasons, cur=season, lg=lg, lg_name=L.LEAGUE[lg],
               role=role if role in R.ROLES else '')
    base = visible(RookiePlayer.objects.all(), 'user')       # 운영자(admin) 선수는 순위에서 뺀다
    if tab == 'leaders':
        if season:
            ctx['bat'] = L.leaders(season, lg, 'batter')
            ctx['pit'] = L.leaders(season, lg, 'pitcher')
            ctx['team_games'] = L.team_games(season)
            ctx['qual_pa'] = int(L.QUAL_PA * ctx['team_games'] + 0.999)
            ctx['qual_ip'] = int(L.QUAL_IP * ctx['team_games'] + 0.999)
    elif tab == 'players':
        qs = base.select_related('user', 'user__profile')
        if ctx['role']:
            qs = qs.filter(role=ctx['role'])
        ctx['rows'] = [{'p': p, 'team': R.TEAM.get(p.team, {}), 'role_label': R.ROLES[p.role]['label'],
                        'pos_label': L.POS_LABEL.get(p.position, ''), 'tier_name': R.TIERS[p.tier]['name'],
                        'title': R.title(p.role, p.tier, p.ovr), 'is_me': p.user_id == request.user.id}
                       for p in qs.order_by('-tier', '-ovr', 'created_at')[:100]]
    else:
        agg = {a['team']: a for a in base.values('team').annotate(
            n=Count('id'), first=Count('id', filter=Q(tier=2)), power=Sum('ovr'))}
        teams = []
        for code, _name, _color in R.TEAMS:
            a = agg.get(code, {})
            n = a.get('n', 0)
            teams.append({'team': R.TEAM[code], 'n': n, 'first': a.get('first', 0), 'power': round(a.get('power') or 0),
                          'avg': round((a.get('power') or 0) / n, 1) if n else 0})
        teams.sort(key=lambda t: (-t['power'], t['team']['name']))
        ctx['team_rows'] = teams
        ctx['my_team'] = RookiePlayer.objects.filter(user_id=request.user.id).values_list('team', flat=True).first() or ''
    return render(request, 'community/rookie_league.html', ctx)


def rookie_ranking(request):
    """예전 주소 — 리그의 선수 순위 탭으로."""
    tab = 'teams' if request.GET.get('tab') == 'teams' else 'players'
    return redirect(f"/rookie/league/?tab={tab}")


# ───────────────────────────── 시상식
def rookie_awards(request):
    _catch_up()
    seasons = _seasons()
    season = _pick_season(request, seasons, closed_only=True)
    ctx = dict(_base_ctx(request, 'awards'), seasons=[s for s in seasons if s.closed], cur=season,
               award_pa=int(L.AWARD_PA * L.SEASON_GAMES), award_ip=int(L.AWARD_IP * L.SEASON_GAMES + 0.999))
    if season:
        awards = list(visible(RookieAward.objects.filter(season=season), 'user').select_related('player', 'stat'))
        ctx['mvp'] = next((a for a in awards if a.kind == 'mvp'), None)
        ctx['mvp_nums'] = L.highlights(ctx['mvp'].stat) if ctx['mvp'] else []
        ctx['roy'] = next((a for a in awards if a.kind == 'rookie'), None)
        ctx['futures'] = next((a for a in awards if a.kind == 'futures'), None)
        ctx['titles'] = [a for a in awards if a.kind == 'title']
        gg = [a for a in awards if a.kind == 'gg']
        spots = {}
        for a in gg:
            spots.setdefault(a.position, []).append(a)
        ctx['gg'] = gg
        ctx['spots'] = [{'pos': pos, 'label': L.POS_LABEL[pos], 'winners': spots.get(pos, [])}
                        for pos in ('SP', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH')]
    else:
        # 아직 끝난 시즌이 없다 — 지금 시즌의 MVP 레이스(WAR 상위)를 보여 준다
        now = L.season_state()
        live = L.get_season(now['number']) if now['phase'] == 'season' else None
        race = []
        if live:
            race = sorted(L.stat_rows(live, 2, 'batter') + L.stat_rows(live, 2, 'pitcher'),
                          key=lambda r: r.war, reverse=True)[:5]
        ctx['race'] = [{'s': r, 'v': L.line_view(r.role, r.totals)} for r in race]
        ctx['ceremony'] = L.season_bounds(now['number'])[1] + timedelta(days=1)
    return render(request, 'community/rookie_awards.html', ctx)


# ───────────────────────────── 기록실
def rookie_records(request):
    _catch_up()
    role = 'pitcher' if request.GET.get('role') == 'pitcher' else 'batter'
    highs = L.career_highs(role)
    ctx = dict(_base_ctx(request, 'records'), role=role, highs=highs, top=highs[0] if highs else None,
               rest=highs[1:], records=[r for r in L.season_records() if r['role'] == role])
    if ctx['my_id']:
        ctx['mine'] = next((i for i, h in enumerate(highs, 1) if h['s'].player_id == ctx['my_id']), None)
    return render(request, 'community/rookie_records.html', ctx)
