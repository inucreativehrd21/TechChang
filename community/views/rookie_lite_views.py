"""야구선수 키우기 라이트 화면 — 규칙은 community/rookie_lite.py.

/rookie/lite/            내 커리어(만들기 · 비시즌 · 시즌 결산 · 갈림길) — 단계는 LiteCareer.pending
/rookie/lite/new/        선수 만들기(POST)
/rookie/lite/act/        진행(POST: play · next · decide · quit)
/rookie/lite/hall/       명예의 전당(전체 · KBO · MLB · NPB · CPBL)
/rookie/lite/c/<id>/     커리어 페이지(공개)
/rookie/lite/c/<id>/card/ 은퇴 카드(공개 — 캡처해서 자랑하는 한 장)
/rookie/lite/cards/      내 은퇴 카드 보관함(회원)
모든 진행은 POST → 되돌아오기. 자바스크립트는 전광판 연출과 훈련 두 개 고르기 도움만 한다.
로그인 없이도 할 수 있다(2026-10-18 사용자 요청) — 손님 판은 세션 표식(SESSION_KEY)으로 찾고, 로그인하면 계정으로 옮긴다.
명예의 전당에는 계정에 붙은 판만 오른다.
"""
import logging
import random
import secrets

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import rookie as R
from .. import rookie_league as L
from .. import rookie_lite as X
from .. import rookie_world as W
from ..game_visibility import is_hidden
from ..models import LiteCareer

logger = logging.getLogger(__name__)
HALL_TABS = [('', '전체'), ('kbo', 'KBO'), ('mlb', '미국'), ('npb', '일본'), ('cpbl', '대만')]
SESSION_KEY = 'lite_guest'


def _rng():
    return random.SystemRandom()


def _guest(request, make: bool = False) -> str:
    token = request.session.get(SESSION_KEY, '')
    if not token and make:
        token = secrets.token_hex(12)
        request.session[SESSION_KEY] = token
    return token


def _mine(request):
    """이 사람의 커리어들 — 회원이면 계정, 손님이면 세션 표식."""
    if request.user.is_authenticated:
        return LiteCareer.objects.filter(user=request.user)
    token = _guest(request)
    return LiteCareer.objects.filter(user__isnull=True, guest=token) if token else LiteCareer.objects.none()


def _claim(request):
    """로그인한 뒤 처음 열면 손님으로 하던 판을 계정으로 옮긴다."""
    token = _guest(request)
    if not (token and request.user.is_authenticated):
        return
    if X.claim_guest(request.user, token):
        messages.info(request, '손님으로 하던 커리어를 내 계정으로 옮겼어요.')
    if not LiteCareer.objects.filter(user__isnull=True, guest=token).exists():
        request.session.pop(SESSION_KEY, None)


def _is_mine(request, c) -> bool:
    """이 판의 주인인가 — 회원 판은 계정, 손님 판은 세션 표식으로(비로그인끼리 None == None 이 되지 않게)."""
    if c.user_id:
        return c.user_id == request.user.id
    return bool(c.guest) and c.guest == _guest(request)


def _grade(c) -> str:
    if W.is_pro(c.league):
        return ''
    if c.grade > W.last_grade(c.league):                       # 졸업 학년을 마치고 드래프트를 맞는 중
        return f"{'고교' if c.league == 'hs' else '대학'} 졸업 · 드래프트"
    return W.grade_label(c.league, c.grade)


LADDERS = {'kbo': ('kbo3', 'kbo2', 'kbo1'), 'mlb': ('mlb_a', 'mlb_aa', 'mlb_aaa', 'mlb'), 'npb': ('npb2', 'npb1'),
           'cpbl': ('cpbl',)}


def _ladder(c) -> list:
    """HUD 의 사다리 — 학생은 학년, 프로는 그 나라 리그 계단."""
    if not W.is_pro(c.league):
        last = W.last_grade(c.league)
        return [{'label': W.grade_label(c.league, g), 'on': g == c.grade, 'done': g < c.grade} for g in range(1, last + 1)]
    steps = LADDERS.get(W.system_of(c.league), (c.league,))
    i = steps.index(c.league) if c.league in steps else 0
    return [{'label': W.short(x), 'on': k == i, 'done': k < i} for k, x in enumerate(steps)]


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
            'salary': X.man(c.salary), 'earnings': X.man(c.earnings), 'want': R.TEAM.get(c.team, {}),
            'cal_year': X.cal_year(c), 'trust': X.trust(c) if W.is_pro(c.league) else None, 'ladder': _ladder(c),
            'epithet': X.EPITHET.get(c.style, '')}


PROGRAM_ICON = {'contact': 'bat', 'power': 'weight', 'eye': 'eye', 'speed': 'run', 'defense': 'glove', 'balance': 'balance',
                'velocity': 'gauge', 'control': 'target', 'breaking': 'curve', 'stamina': 'heart', 'mental': 'mind'}


def _season_rows(c) -> list:
    rows = []
    for s in c.seasons.all():
        rows.append({'s': s, 'league': W.short(s.league), 'club': W.club_short(s.league, s.club),
                     'line': X._short(c.role, s.totals) if s.games else s.duty, 'kinds': [a['kind'] for a in s.awards]})
    return rows


def _school_groups() -> list:
    """지역마다 입학할 수 있는 고교 — 만들기 화면에서 고른 지역의 묶음만 보인다."""
    out = []
    for region in W.REGIONS:
        pool = X.school_choices(region)
        near = sorted({r for r, _s in pool if r != region}, key=W.REGIONS.index)
        out.append({'region': region, 'near': '·'.join(near),
                    'schools': [{'name': s, 'hard': W.powerhouse('hs', s)} for _r, s in pool]})
    return out


def _base(request, section: str) -> dict:
    return {'section': section, 'regions': W.REGIONS, 'teams': [R.TEAM[c] for c, _n, _c in R.TEAMS],
            'styles': X.STYLES, 'bat_positions': L.POSITIONS, 'pit_positions': X.PIT_POSITIONS,
            'roles': R.ROLES}


def lite_home(request):
    ctx = _base(request, 'home')
    _claim(request)
    mine = _mine(request)
    c = mine.filter(retired_at__isnull=True).first()
    if c is None:
        last = mine.filter(retired_at__isnull=False).order_by('-retired_at').first()
        name = ''
        if request.user.is_authenticated:
            name = (getattr(getattr(request.user, 'profile', None), 'nickname', '') or request.user.username)[:12]
        ctx.update(mode='create', last=_identity(last) if last else None,
                   last_line=X.career_line(last) if last else None,
                   mine=list(mine.filter(retired_at__isnull=False)[:10]), default_name=name,
                   hall=X.hall(limit=5), school_groups=_school_groups())
        return render(request, 'community/rookie_lite.html', ctx)
    pend = c.pending or {}
    ctx.update(mode=pend.get('kind', 'plan'), **_identity(c), seasons=_season_rows(c))
    if pend.get('kind') == 'plan':
        ctx['duty'] = X._duty_now(c)[2]
        rules = X.train_rules(c)
        labels = {p[0]: p[1] for p in X.PROGRAMS[c.role]}
        room = {k: X.room_of(c, k) for k in c.stats}
        ctx.update(programs=[{'code': code, 'label': lab, 'hint': hint, 'icon': PROGRAM_ICON.get(code, 'balance'),
                              'locked': code in rules['locked'], 'room': room.get(code)} for code, lab, hint, _e in X.PROGRAMS[c.role]],
                   banned=rules['banned'], banned_text=' + '.join(labels[p] for p in rules['banned']),
                   intensity=[{'code': k, 'label': v[0], 'risk': int(round(v[2] * 100))} for k, v in X.INTENSITY.items()],
                   event=X.event_view(c, pend.get('event')), intl=X.intl_view(c, pend.get('intl') or []),
                   offseason=(c.flags or {}).get('press') or [])
        step = 1 + bool(ctx['intl']) + bool(ctx['event'])
        ctx['steps'] = {'intl': 1, 'event': 1 + bool(ctx['intl']), 'train': step, 'power': step + 1}
    elif pend.get('kind') == 'review':
        s = c.seasons.filter(year=pend.get('year')).first()
        ctx.update(season=s, season_line=L.line_view(c.role, s.totals) if s and s.totals else None,
                   deltas=[{'label': lab, 'value': (s.deltas or {}).get(k, 0), 'why': ((s.deltas or {}).get('_why') or {}).get(k, [])}
                           for k, lab, _w in R.ROLES[c.role]['stats']] if s else [],
                   moments=pend.get('moments') or [],
                   drops=[],
                   season_league=W.league(s.league)['name'] if s else '', season_club=W.club_label(s.league, s.club) if s else '',
                   season_year=X.cal_year(c, s.year) if s else '', press=(s.press or []) if s else [],
                   splits=[dict(x, lg=W.league(x['league'])['name'], club_name=W.club_short(x['league'], x['club']))
                           for x in (s.splits or [])] if s and len(s.splits or []) > 1 else [],
                   meet_next=bool((c.flags or {}).get('move')))
        ctx['drops'] = [d for d in ctx.get('deltas') or [] if d['value'] < 0]
    elif pend.get('kind') == 'decision':
        ctx['decision'] = X.decision_view(c)
    return render(request, 'community/rookie_lite.html', ctx)


@require_POST
def lite_new(request):
    try:
        number = int(request.POST.get('number') or 0)
    except ValueError:
        number = 0
    role = request.POST.get('role', '')
    try:
        X.create(request.user if request.user.is_authenticated else None, name=request.POST.get('name', ''), role=role,
                 position=request.POST.get(f'position_{role}', ''), style=request.POST.get(f'style_{role}', ''),
                 region=request.POST.get('region', ''), team=request.POST.get('team', ''), number=number, rng=_rng(),
                 guest='' if request.user.is_authenticated else _guest(request, make=True),
                 school=request.POST.get('school', ''))
    except X.LiteError as ex:
        messages.warning(request, str(ex))
    return redirect('community:lite_home')


@require_POST
def lite_act(request):
    action = request.POST.get('action', '')
    rng = _rng()
    try:
        with transaction.atomic():
            c = _mine(request).select_for_update().filter(retired_at__isnull=True).first()
            if c is None:
                raise X.LiteError('진행 중인 커리어가 없어요. 새 선수를 만들어 주세요.')
            pend = c.pending or {}
            if action == 'play':
                if pend.get('kind') != 'plan':
                    raise X.LiteError('지금은 시즌을 시작할 차례가 아니에요.')
                X.check_programs(c, request.POST.getlist('program'))          # 훈련 두 개·잠김·같은 조합부터 알려 준다
                intensity = request.POST.get('intensity', '')
                choice = request.POST.get('event_choice', '')
                if pend.get('event') and choice not in [k for k, _l, _h in X.EVENTS[pend['event']]['choices']]:
                    raise X.LiteError('비시즌 이벤트에 어떻게 할지 먼저 골라 주세요.')
                intl = {k: request.POST.get(f'intl_{k}', '') for k in pend.get('intl') or []}
                if X.run_season(c, request.POST.getlist('program'), intensity, choice, rng, intl=intl) is None:
                    messages.info(request, '올스타 휴식기 — 감독이 면담을 요청했어요.')
            elif action == 'next':
                X.next_season(c, rng)
            elif action == 'decide':
                text = X.decide(c, request.POST.get('what', ''), request.POST.get('choice', ''), rng,
                                school=request.POST.get('school', ''))
                c.save()
                if text:
                    messages.info(request, text)
                if c.retired_at:
                    return redirect(f"{reverse('community:lite_card', args=[c.pk])}?new=1")
            elif action == 'quit':
                if request.POST.get('confirm') != 'yes':
                    raise X.LiteError('은퇴하려면 확인 칸에 체크해 주세요.')
                messages.info(request, X.retire(c, '스스로'))
                c.save()
                return redirect(f"{reverse('community:lite_card', args=[c.pk])}?new=1")
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
                       awards=awards, is_me=_is_mine(request, c), peak=W.league(c.peak or 'hs')['name']))


# ───────────────────────────── 은퇴 카드(2026-10-18 사용자 요청: 캡처해서 자랑, 회원은 보관함에서 다시 보기)
def _card(c) -> dict:
    """은퇴 카드 한 장 — 통산 줄·수상 묶음·거쳐 간 팀·등급(레전드·스타·프로·루키)."""
    seasons = list(c.seasons.all())
    pro = [s for s in seasons if s.games and W.is_pro(s.league)]
    played = [s for s in seasons if s.games]
    line = X.career_line(c)
    total = line['pro'] or (L.line_view(c.role, X._sum_totals(played)) if played else None)
    kinds = [a for s in seasons for a in s.awards]
    gg = sum(1 for a in kinds if a['kind'] == 'gg')
    titles = sum(1 for a in kinds if a['kind'] == 'title')
    golds = sum(1 for a in kinds if a['kind'] == 'national' and ('금메달' in a['label'] or a['label'].endswith('우승')))
    clubs = []
    for s in pro:
        name = W.club_short(s.league, s.club)
        if not clubs or clubs[-1] != name:
            clubs.append(name)
    best = max(pro, key=lambda s: s.war, default=None)
    best_ovr = max([s.ovr_end for s in seasons] or [c.best_ovr])
    if c.mvp >= 2 or best_ovr >= 80 or (c.mvp and golds):
        tier, tier_label = 'legend', '레전드'
    elif c.mvp or best_ovr >= 72 or gg + titles >= 4:
        tier, tier_label = 'star', '스타'
    elif any(s.league in W.TOP_LEAGUES for s in pro):
        tier, tier_label = 'pro', '프로'
    else:
        tier, tier_label = 'rookie', '루키'
    badges = [(c.mvp, 'MVP'), (gg, '골든글러브'), (titles, '타이틀'), (c.rings, '우승'), (golds, '국가대표 금')]
    first, last = X.cal_year(c, 1), X.cal_year(c, max(1, c.year - 1))
    eok, rest = divmod(int(c.earnings or 0), 10000)
    money = f'{eok:,}억' if eok else X.man(c.earnings)
    return {'tier': tier, 'tier_label': tier_label, 'line': total, 'war': round(sum(s.war for s in pro), 1), 'money': money,
            'best_ovr': round(best_ovr, 1), 'years': f'{first}–{last}', 'seasons': len(played),
            'clubs': clubs[:5], 'more_clubs': max(0, len(clubs) - 5),
            'badges': [{'n': n, 'label': lab} for n, lab in badges if n],
            'best': ({'year': X.cal_year(c, best.year), 'league': W.short(best.league), 'line': X._short(c.role, best.totals),
                      'war': best.war} if best else None),
            'peak': W.league(c.peak or 'hs')['name'], 'epithet': X.EPITHET.get(c.style, ''),
            'headline': X.retire_headline(c, len(played))}


def lite_card(request, pk: int):
    c = get_object_or_404(LiteCareer.objects.select_related('user'), pk=pk)
    if is_hidden(c.user) and c.user_id != request.user.id:
        raise Http404
    if not c.retired_at:
        return redirect('community:lite_career', pk=pk)
    return render(request, 'community/rookie_lite_card.html',
                  dict(_base(request, 'cards'), **_identity(c), card=_card(c), is_me=_is_mine(request, c),
                       fresh=request.GET.get('new') == '1' and _is_mine(request, c)))


def lite_cards(request):
    """내 은퇴 카드 보관함 — 회원은 계정의 은퇴 선수 모두, 손님은 이 브라우저에서 은퇴한 선수(로그인하면 보관)."""
    _claim(request)
    rows = [dict(_identity(c), card=_card(c)) for c in _mine(request).filter(retired_at__isnull=False).order_by('-retired_at')[:60]]
    return render(request, 'community/rookie_lite_cards.html', dict(_base(request, 'cards'), rows=rows))
