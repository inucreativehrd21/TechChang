"""야구선수 키우기 화면 — 성장 규칙 community/rookie.py, 진로 rookie_career, 리그·기록·시상 rookie_league,
통산·이정표·베스트 9·명예의 전당 rookie_legacy, 리그·구단·학교 rookie_world.

화면 넷 + 선수 페이지: 내 선수(/rookie/) · 리그(/rookie/league/) · 시상식(/rookie/awards/) · 기록실(/rookie/records/)
· 선수(/rookie/p/<id>/). 훈련은 fetch 로 보내면 플레이 영역 HTML 을 통째로 돌려받아 갈아 끼운다
(규칙을 JS 에 다시 쓰지 않으려고). 자바스크립트가 없으면 같은 폼이 그대로 POST → 되돌아오기로 동작한다.
진학 지원·드래프트 결정은 일반 폼(POST → 되돌아오기).
"""
import logging
import random
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import rookie as R
from .. import rookie_card as K
from .. import rookie_career as C
from .. import rookie_league as L
from .. import rookie_legacy as G
from .. import rookie_versions as Versions
from .. import rookie_world as W
from ..game_visibility import rookie_hidden as is_hidden, rookie_visible as visible   # 야구는 운영자도 보인다
from ..rookie_card import render_png   # noqa: F401 — 테스트가 바꿔 끼운다
from ..models import RookieAward, RookieGame, RookiePlayer, RookieSeason, RookieSeasonStat

logger = logging.getLogger(__name__)
SYSTEM_ORDER = ('kbo', 'mlb', 'npb', 'cpbl', 'amateur')


def _ajax(request) -> bool:
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _catch_up(request):
    """밤 cron 이 빠졌을 때 로그인한 회원이 화면을 열면 전날 경기를 대신 치른다(이미 치렀으면 할 일 없음).
    비로그인·크롤러 요청은 무거운 배치를 돌리지 않는다. 다른 프로세스가 치르는 중이면 기다리지 않는다(skip_locked)."""
    if not request.user.is_authenticated:
        return
    try:
        L.advance()
    except Exception:  # noqa: BLE001 — 경기 진행 실패가 화면을 막지 않게
        logger.warning('야구선수 키우기 경기 진행 실패', exc_info=True)


def _league_order(code: str):
    """리그 고르기 순서 — KBO · 미국 · 일본 · 대만 · 아마추어, 같은 나라는 높은 리그부터."""
    sysname = W.system_of(code)
    return SYSTEM_ORDER.index(sysname), -W.LEAGUES[code]['step']


def _choice(code: str) -> dict:
    return {'code': code, 'short': W.short(code), 'name': W.league(code)['name'],
            'system': W.SYSTEM_NAME[W.system_of(code)]}


def _choices(codes) -> list:
    return [_choice(c) for c in sorted(set(codes) & set(W.LEAGUES), key=_league_order)]


def _base_ctx(request, section: str) -> dict:
    me = R.current(request.user.id)
    return {'section': section, 'season_now': L.season_state(),
            'teams': [R.TEAM[c] for c, _n, _c in R.TEAMS], 'roles': R.ROLES, 'earn': R.EARN,
            'welcome': R.WELCOME_TP, 'cost': R.TRAIN_COST, 'daily_max': R.DAILY_MAX, 'fatigue_at': R.FATIGUE_AT,
            'focus_bonus': int(round((R.FOCUS_BONUS - 1) * 100)), 'positions': L.POSITIONS, 'regions': W.REGIONS,
            'opp_first': L.opp_levels('kbo1'), 'grade_days': C.GRADE_DAYS, 'tp_max': R.TP_MAX,
            'lv': {c: int(v['level']) for c, v in W.LEAGUES.items()}, 'max_age': C.MAX_AGE,
            'my_id': me.id if me else None, 'my_league': me.league if me else ''}


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


def _pick_league(request, choices: list, default: str = 'kbo1') -> str:
    """고른 리그, 아니면 내 선수의 리그, 아니면 기본(KBO)."""
    codes = [c['code'] for c in choices]
    want = request.GET.get('lg', '')
    if want in codes:
        return want
    mine = R.current(request.user.id)
    if mine and mine.league in codes:
        return mine.league
    return default if default in codes or not codes else codes[0]


# ───────────────────────────── 내 선수
def rookie_home(request):
    _catch_up(request)
    if not request.user.is_authenticated:
        return render(request, 'community/rookie.html', dict(_base_ctx(request, 'home'), mode='intro'))
    with transaction.atomic():
        p = R.locked(request.user)
        if p is not None:
            R.settle(p)
            if p.retired_at:                    # 정산하다 은퇴 나이가 됐다
                p = None
            else:
                from .. import rookie_story as Story
                Story.prepare_daily(p, timezone.localdate())
                p.save(update_fields=['career', 'league', 'club', 'league_since', 'lineup', 'slot', 'role_since'])
    if p is None:
        profile = getattr(request.user, 'profile', None)
        name = (getattr(profile, 'nickname', '') or request.user.username)[:12]
        last = RookiePlayer.objects.filter(user=request.user, retired_at__isnull=False).order_by('-retired_at').first()
        return render(request, 'community/rookie.html', dict(_base_ctx(request, 'home'), mode='create',
                                                             default_name=name, last=last,
                                                             last_id=R.identity(last) if last else None,
                                                             heir=bool(R.inherits_from(request.user))))
    ctx = _play_ctx(request, p)
    ctx['test'] = request.session.pop('rookie_test', None)
    fx = (p.career or {}).get('awaken_fx')
    if fx:                                                     # 각성 연출 — 한 번 보여 주고 지운다
        p.career = {k: v for k, v in p.career.items() if k != 'awaken_fx'}
        p.save(update_fields=['career'])
        ctx['awaken_fx'] = fx
    afx = R.award_fx(p)                                        # 새로 받은 상 — 한 번 축하
    if afx:
        p.save(update_fields=['career'])
        ctx['award_fx'] = afx
    return render(request, 'community/rookie.html', ctx)


@login_required
@require_POST
def rookie_story_reply(request):
    from .. import rookie_story as Story
    try:
        with transaction.atomic():
            p = R.locked(request.user)
            if p is None or p.retired_at:
                raise ValueError('진행 중인 선수가 없어요.')
            R.settle(p)
            if p.retired_at:
                raise ValueError('이미 은퇴한 선수예요.')
            text = Story.daily_reply(p, request.POST.get('event_id', ''), request.POST.get('choice', ''),
                                     random.SystemRandom(), timezone.localdate())
            p.save(update_fields=['career', 'league', 'club', 'league_since', 'lineup', 'slot', 'role_since', 'position'])
            R._log(p, 'career', text[:200])
        messages.info(request, text)
    except ValueError as ex:
        messages.warning(request, str(ex))
    return redirect('community:rookie_home')


@login_required
@require_POST
def rookie_awaken(request):
    """각성 도전·미루기 — 결과 연출은 다음 화면(rookie_home)이 보여 준다."""
    try:
        r = R.awaken(request.user, request.POST.get('choice', ''))
        messages.info(request, r['text'])
    except R.GameError as ex:
        messages.warning(request, str(ex))
    return redirect('community:rookie_home')


@login_required
@require_POST
def rookie_create(request):
    if R.current(request.user.id):
        return redirect('community:rookie_home')
    role = request.POST.get('role', '')
    try:
        number = int(request.POST.get('number') or 0)
    except ValueError:
        number = 0
    try:
        p = R.create(request.user, name=request.POST.get('name', ''), role=role, team=request.POST.get('team', ''),
                     number=number, focus=request.POST.get(f'focus_{role}', ''),
                     position=request.POST.get('pitch_position', request.POST.get('position', '')) if role == 'pitcher' else request.POST.get('position', ''),
                     region=request.POST.get('region', ''))
    except R.GameError as ex:
        messages.warning(request, str(ex))
        return redirect('community:rookie_home')
    except IntegrityError:                      # 입단 버튼을 두 번 눌렀다 — 이미 만들어졌다
        return redirect('community:rookie_home')
    messages.success(request, f'{p.name} 선수, {p.club} 입단! 입단 보너스 {R.WELCOME_TP} TP로 첫 훈련을 해 보세요. '
                              f'중학교 진학까지 {C.GRADE_DAYS}일 — 희망 중학교도 골라 두세요.')
    return redirect('community:rookie_home')


@login_required
@require_POST
def rookie_train(request):
    try:
        r = R.train(request.user, request.POST.get('stat', ''), request.POST.get('times', 1))
    except (R.GameError, ValueError) as ex:
        text = str(ex) if isinstance(ex, R.GameError) else '훈련 요청이 올바르지 않아요. 화면을 새로고침해 주세요.'
        if _ajax(request):
            return JsonResponse({'ok': False, 'message': text}, status=400)
        messages.warning(request, text)
        return redirect('community:rookie_home')
    toast = f"{r['label']} {r['before']:.1f} → {r['after']:.1f}"
    if r['great']:
        toast += f" · 대성공 {r['great']}회!"
    if r['tired']:
        toast += ' · 피로로 효율 절반'
    if r['capped']:
        toast += ' · 지금 한계에 닿았어요'
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
    request.session['rookie_test'] = {'passed': r['passed'], 'league_name': r['league_name'], 'won': r['won'],
                                      'games': r['games'], 'total': R.TEST_GAMES}
    return redirect('community:rookie_home')


@login_required
@require_POST
def rookie_apply(request):
    """졸업 학년의 진학 지원 — 희망 학교 고르기(학년이 끝나는 날 합격 발표)."""
    try:
        messages.success(request, C.apply_school(request.user, request.POST.get('school', '')))
    except R.GameError as ex:
        messages.warning(request, str(ex))
    return redirect('community:rookie_home')


@login_required
@require_POST
def rookie_decide(request):
    """드래프트 뒤 진로 — 계약 / 육성선수 / 대학 / 해외(미국·일본·대만)."""
    try:
        text = C.decide(request.user, request.POST.get('choice', ''), school=request.POST.get('school', ''))
        messages.success(request, text or '진로를 정했어요.')
    except R.GameError as ex:
        messages.warning(request, str(ex))
    return redirect('community:rookie_home')


@login_required
@require_POST
def rookie_retire(request):
    if request.POST.get('confirm') != 'yes':
        messages.warning(request, '은퇴하려면 확인 칸에 체크해 주세요.')
        return redirect('community:rookie_home')
    if R.retire(request.user):
        messages.info(request, '은퇴했어요. 선수 페이지와 기록·수상은 그대로 남고, 명예의 전당 후보가 돼요. '
                               '새 선수로 리틀야구부터 다시 시작할 수 있어요.')
        last = RookiePlayer.objects.filter(user=request.user, retired_at__isnull=False).order_by('-retired_at').first()
        if last:                                               # 은퇴 카드부터 보여 준다
            return redirect(f"{reverse('community:rookie_card', args=[last.pk])}?new=1")
    return redirect('community:rookie_home')


# ───────────────────────────── 은퇴 카드(2026-10-19 사용자 요청: 라이트 판의 카드를 정식 판에도 — 이미지 저장·SNS·링크 미리보기)
def _card_player(request, pk: int):
    p = get_object_or_404(RookiePlayer.objects.select_related('user'), pk=pk)
    if is_hidden(p.user) and p.user_id != request.user.id:
        raise Http404
    return p


def _card_ctx(p) -> dict:
    card = K.main_card(p)
    ident = card.pop('identity')
    return {'c': p, 'card': card, 'team': ident['team'], 'pos_label': ident['pos_label'] or ident['role_label'],
            'style_label': f"주특기 {ident['focus_label']}" if ident['focus_label'] else ident['role_label']}


def rookie_card(request, pk: int):
    p = _card_player(request, pk)
    if not p.retired_at:
        return redirect('community:rookie_player', pk=pk)
    is_me = p.user_id == request.user.id
    return render(request, 'community/rookie_card.html',
                  dict(_base_ctx(request, 'records'), **_card_ctx(p), is_me=is_me, fresh=is_me and request.GET.get('new') == '1'))


def rookie_card_png(request, pk: int, kind: str = 'card'):
    p = _card_player(request, pk)
    if not p.retired_at or kind not in K.SHOTS:
        raise Http404
    return K.png_response(f'm{p.pk}', kind, f'{p.name}-은퇴카드.png', request.GET.get('download') == '1', render_png,
                          lambda: render_to_string('community/games/lite_card_shot.html', dict(_card_ctx(p), kind=kind)))


# ───────────────────────────── 선수 페이지(공개)
def rookie_player(request, pk: int):
    p = get_object_or_404(RookiePlayer.objects.select_related('user'), pk=pk)
    if is_hidden(p.user) and p.user_id != request.user.id:
        raise Http404
    _catch_up(request)
    career = sorted(RookieSeasonStat.objects.filter(player=p).select_related('season'),
                    key=lambda r: (-r.season.number, -W.level(r.league)))
    games = [L.game_view(g, p.club, p.role) for g in RookieGame.objects.filter(player=p).order_by('-day', '-no')[:20]]
    ctx = dict(_base_ctx(request, 'league'), p=p, **R.identity(p), path=C.career_view(p),
               ladder=None if p.retired_at else L.ladder_of(p), stats=R.stat_rows(p), career=L.season_lines(career),
               life=G.lifetime(p), games=games,
               trophies=list(RookieAward.objects.filter(player=p).select_related('season')
                             .order_by('-season__number', 'order')),
               miles=list(p.logs.filter(kind='mile').exclude(text__contains='베스트 9')[:12]),
               best9=p.logs.filter(kind='mile', text__contains='베스트 9').count(),
               is_me=p.user_id == request.user.id)
    return render(request, 'community/rookie_player.html', ctx)


# ───────────────────────────── 리그
def rookie_league(request):
    _catch_up(request)
    if request.user.is_authenticated:
        try:
            R.settle_all()              # 쉬는 선수를 순위에 그대로 두지 않게(밤 cron 이 돌았으면 할 일 없음)
        except Exception:  # noqa: BLE001 — 정산 실패가 리그 화면을 막지 않게
            logger.warning('야구선수 키우기 정산 실패', exc_info=True)
    tab = request.GET.get('tab') if request.GET.get('tab') in ('leaders', 'best9', 'players', 'teams') else 'leaders'
    seasons = _seasons()
    season = _pick_season(request, seasons)
    if tab == 'best9':
        codes = set(RookieGame.objects.values_list('league', flat=True).distinct()) | {'kbo1'}
    else:
        codes = set((RookieSeasonStat.objects.filter(season=season) if season else RookieSeasonStat.objects.none())
                    .values_list('league', flat=True).distinct()) | {'kbo1'}
    choices = _choices(codes)
    lg = _pick_league(request, choices)
    role = request.GET.get('role', '')
    ctx = dict(_base_ctx(request, 'league'), tab=tab, seasons=seasons, cur=season, lg=lg, lg_name=W.league(lg)['name'],
               lg_short=W.short(lg), lg_choices=choices, role=role if role in R.ROLES else '')
    if tab == 'leaders':
        if season:
            ctx['bat'] = L.leaders(season, lg, 'batter')
            ctx['pit'] = L.leaders(season, lg, 'pitcher')
            ctx['team_games'] = L.team_games(season, lg)
            ctx['qual_pa'] = int(L.QUAL_PA * ctx['team_games'] + 0.999)
            ctx['qual_ip'] = int(L.QUAL_IP * ctx['team_games'] + 0.999)
    elif tab == 'best9':
        day = G.latest_day(lg)
        nine = G.best_nine(day, lg) if day else []
        ctx.update(nine_day=day, nine=nine, spots=[dict(x, a=_spot(x)) for x in nine])
    elif tab == 'players':
        qs = R.ranked().select_related('user', 'user__profile')
        if ctx['role']:
            qs = qs.filter(role=ctx['role'])
        ctx['rows'] = [dict(R.identity(p), p=p, is_me=p.user_id == request.user.id)
                       for p in qs.order_by('-lv', '-ovr', 'created_at')[:100]]
    else:
        base = R.ranked()
        pro = base.filter(league__in=W.SYSTEMS['kbo'])
        agg = {a['club']: a for a in pro.values('club').annotate(
            n=Count('id'), first=Count('id', filter=Q(league='kbo1')), power=Sum('ovr'))}
        fans = dict(base.filter(league__in=W.SYSTEMS['amateur']).values('team').annotate(n=Count('id'))
                    .values_list('team', 'n'))
        teams = []
        for code, _name, _color in R.TEAMS:
            a = agg.get(code, {})
            n = a.get('n', 0)
            teams.append({'team': R.TEAM[code], 'n': n, 'first': a.get('first', 0), 'power': round(a.get('power') or 0),
                          'avg': round((a.get('power') or 0) / n, 1) if n else 0, 'fans': fans.get(code, 0)})
        teams.sort(key=lambda t: (-t['power'], -t['fans'], t['team']['name']))
        ctx['team_rows'] = teams
        me = R.current(request.user.id)
        ctx['my_team'] = (me.club if me and W.system_of(me.league) == 'kbo' else me.team) if me else ''
    return render(request, 'community/rookie_league.html', ctx)


class _Spot:
    """다이아몬드 칸(_rookie_spot.html)에 넘길 모양 — 수상 행과 같은 이름의 속성."""
    def __init__(self, x):
        p = x['p']
        self.player_id, self.name, self.team, self.value = p.pk, p.name, x['team'], x['value']


def _spot(x):
    return _Spot(x) if x.get('p') else None


def rookie_ranking(request):
    """예전 주소 — 리그의 선수 순위 탭으로."""
    tab = 'teams' if request.GET.get('tab') == 'teams' else 'players'
    return redirect(f"/rookie/league/?tab={tab}")


# ───────────────────────────── 시상식
def rookie_awards(request):
    _catch_up(request)
    seasons = _seasons()
    season = _pick_season(request, seasons, closed_only=True)
    ctx = dict(_base_ctx(request, 'awards'), seasons=[s for s in seasons if s.closed], cur=season,
               award_pa=int(L.AWARD_PA * L.SEASON_GAMES), award_ip=int(L.AWARD_IP * L.SEASON_GAMES + 0.999))
    if season:
        everyone = list(visible(RookieAward.objects.filter(season=season), 'user').select_related('player', 'stat'))
        choices = _choices({a.league for a in everyone} or {'kbo1'})
        lg = _pick_league(request, choices)
        awards = [a for a in everyone if a.league == lg]
        style = L.AWARD_STYLE.get(lg)
        ctx.update(lg=lg, lg_name=W.league(lg)['name'], lg_choices=choices, style=style,
                   mvp=next((a for a in awards if a.kind in ('mvp', 'minor')), None),
                   roy=next((a for a in awards if a.kind == 'rookie'), None),
                   ace=next((a for a in awards if a.kind == 'ace'), None),
                   titles=[a for a in awards if a.kind == 'title'],
                   others=sorted([a for a in everyone if a.league != lg and a.kind in ('mvp', 'minor')],
                                 key=lambda a: _league_order(a.league)))
        ctx['mvp_nums'] = L.highlights(ctx['mvp'].stat) if ctx['mvp'] else []
        gg = [a for a in awards if a.kind == 'gg']
        spots = {}
        for a in gg:
            spots.setdefault(a.position, []).append(a)
        ctx['gg'] = gg
        order = ('SP', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH') if not style or style['gg_pitcher'] else \
            ('C', '1B', '2B', '3B', 'SS', 'OF', 'DH')
        ctx['spots'] = [{'pos': pos, 'label': L.POS_LABEL[pos], 'winners': spots.get(pos, [])} for pos in order]
    else:
        # 아직 끝난 시즌이 없다 — 지금 시즌의 MVP 레이스(WAR 상위)를 보여 준다
        now = L.season_state()
        live = L.get_season(now['number']) if now['phase'] == 'season' else None
        race = []
        if live:
            race = sorted(L.stat_rows(live, 'kbo1', 'batter') + L.stat_rows(live, 'kbo1', 'pitcher'),
                          key=lambda r: r.war, reverse=True)[:5]
        ctx['race'] = [{'s': r, 'v': L.line_view(r.role, r.totals)} for r in race]
        ctx['ceremony'] = L.season_bounds(now['number'])[1] + timedelta(days=1)
    return render(request, 'community/rookie_awards.html', ctx)


# ───────────────────────────── 기록실
def rookie_records(request):
    _catch_up(request)
    view = request.GET.get('view') if request.GET.get('view') in ('highs', 'career', 'hof') else 'highs'
    version = Versions.selected(request.GET.get('version'))
    role = 'pitcher' if request.GET.get('role') == 'pitcher' else 'batter'
    if view == 'hof':
        choices = _choices(W.TOP_LEAGUES)
    else:
        choices = _choices(set(RookieSeasonStat.objects.values_list('league', flat=True).distinct()) | {'kbo1'})
    lg = _pick_league(request, choices)
    ctx = dict(_base_ctx(request, 'records'), view=view, role=role, lg=lg, lg_name=W.league(lg)['name'],
               lg_short=W.short(lg), lg_choices=choices, miles=G.recent_milestones(),
               hall_version=version, version_tabs=Versions.CHOICES)
    if view == 'highs':
        highs = L.career_highs(role, lg)
        ctx.update(highs=highs, top=highs[0] if highs else None, rest=highs[1:],
                   records=[r for r in L.season_records(lg) if r['role'] == role])
        if ctx['my_id']:
            ctx['mine'] = next((i for i, h in enumerate(highs, 1) if h['s'].player_id == ctx['my_id']), None)
    else:
        ctx['rows'] = G.league_career(lg, retired_only=view == 'hof', version=version if view == 'hof' else None)
        if view == 'hof':
            ctx['lineup'] = _lineup(G.league_career(lg, retired_only=True, limit=2000, version=version), lg)
    return render(request, 'community/rookie_records.html', ctx)


def _lineup(rows, lg: str) -> dict:
    """명예의 전당 역대 베스트 라인업(라이트 판과 같은 그림) — 정식 판 투수는 자리가 하나(SP)라 마지막 보직으로 선발·마무리를 가른다."""
    from types import SimpleNamespace

    from .. import rookie_lite as X
    BULLPEN = {'closer', 'setup', 'win', 'mop', 'chase'}
    rows = [dict(r, c=SimpleNamespace(pk=r['p'].pk, name=r['p'].name, role=r['p'].role,
                                      position=('RP' if r['p'].lineup in BULLPEN else 'SP') if r['p'].role == 'pitcher' else r['p'].position),
                 url=reverse('community:rookie_player', args=[r['p'].pk]), color=W.club_color(lg, r['team']))
            for r in rows]
    return X.best_lineup(rows)
