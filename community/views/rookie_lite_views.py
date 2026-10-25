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
import hashlib
import json
import os
import random
import secrets
import threading
from functools import wraps

from django.contrib import messages
from django.db import transaction
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import rookie as R
from .. import rookie_league as L
from .. import rookie_lite as X
from .. import rookie_series as Series
from .. import rookie_env as Env
from .. import rookie_env_presentation as EnvUI
from .. import rookie_universe as Universe
from .. import rookie_card as K
from .. import rookie_staff as S
from ..rookie_card import _palette, _jersey_name, render_png   # noqa: F401 — 테스트가 render_png 를 바꿔 끼운다
from .. import rookie_world as W
from .. import rookie_story as Story
from .. import rookie_versions as Versions
from .. import rookie_presentation as Presentation
from .. import rookie_peers as Peers
from .. import rookie_modes as Modes
from .. import rookie_extreme as Extreme
from ..game_visibility import rookie_hidden as is_hidden   # 야구는 운영자도 보인다
from ..rookie_text import signed
from ..models import LiteCareer

logger = logging.getLogger(__name__)
HALL_TABS = [('kbo', 'KBO'), ('mlb', '미국'), ('npb', '일본'), ('cpbl', '대만')]     # 리그를 섞은 전체 순위는 없앴다(2026-10-19)
HALL_ROLES = [('', '전체'), ('pitcher', '투수'), ('batter', '타자')]
SESSION_KEY = 'lite_guest'


def _mode(request):
    return getattr(request, 'rookie_mode', Modes.LITE)


def _route(request, name):
    return f'community:{_mode(request)}_{name}'


def extreme_endpoint(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not Modes.public_enabled():
            raise Http404
        request.rookie_mode = Modes.EXTREME
        return view(request, *args, **kwargs)
    return wrapped


def _session_key(request):
    return 'extreme_guest' if _mode(request) == Modes.EXTREME else SESSION_KEY


def _rng():
    return random.SystemRandom()


def _guest(request, make: bool = False) -> str:
    token = request.session.get(_session_key(request), '')
    if not token and make:
        token = secrets.token_hex(12)
        request.session[_session_key(request)] = token
    return token


def _mine(request):
    """이 사람의 커리어들 — 회원이면 계정, 손님이면 세션 표식."""
    if request.user.is_authenticated:
        return LiteCareer.objects.filter(user=request.user, mode=_mode(request))
    token = _guest(request)
    return LiteCareer.objects.filter(user__isnull=True, guest=token, mode=_mode(request)) if token else LiteCareer.objects.none()


def _claim(request):
    """로그인한 뒤 처음 열면 손님으로 하던 판을 계정으로 옮긴다."""
    token = _guest(request)
    if not (token and request.user.is_authenticated):
        return
    if X.claim_guest(request.user, token, mode=_mode(request)):
        messages.info(request, '손님으로 하던 커리어를 내 계정으로 옮겼어요.')
    if not LiteCareer.objects.filter(user__isnull=True, guest=token, mode=_mode(request)).exists():
        request.session.pop(_session_key(request), None)


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
    return {'c': c, 'bloom_info': X.Bloom.info(c), 'mind': Story.view(c), 'team': {'name': W.club_label(c.league, c.club), 'color': W.club_color(c.league, c.club)},
            'league_name': W.league(c.league)['name'], 'league_short': W.short(c.league),
            'league_kind': R.league_kind(c.league), 'style_label': X.STYLES[c.role][c.style]['label'],
        'pos_label': L.POS_LABEL.get(c.position, dict(X.PIT_POSITIONS).get(c.position, '')),
        'top_war': X.Balance.totals(c)['war'],
            'grade_label': _grade(c),
            'stars': stars, 'star_note': X.STAR_NOTE[stars], 'star_range': range(5), 'stars_total': min(5, stars + X.awakened(c)), 'awakened': X.awakened(c),
            'traits': EnvUI.visible_traits(c),
            'stat_rows': [{'key': k, 'label': lab, 'value': float(c.stats.get(k, 25)), 'shown': int(float(c.stats.get(k, 25))),
                           'bar': round(float(c.stats.get(k, 25)) / 99 * 100, 1)} for k, lab, _w in R.ROLES[c.role]['stats']],
            'salary': X.man(c.salary), 'earnings': X.man(c.earnings), 'want': R.TEAM.get(c.team, {}),
            'cal_year': X.cal_year(c), 'trust': X.trust(c) if W.is_pro(c.league) else None, 'ladder': _ladder(c),
            'epithet': X.EPITHET.get(c.style, ''), 'cash': X.man(X.cash(c)), 'fame': X.fame(c),
            'fame_label': X.fame_label(X.fame(c))}


PROGRAM_ICON = {'contact': 'bat', 'power': 'weight', 'eye': 'eye', 'speed': 'run', 'defense': 'glove', 'balance': 'balance',
                'velocity': 'gauge', 'control': 'target', 'breaking': 'curve', 'stamina': 'heart', 'mental': 'mind'}


def _glue(text: str) -> str:
    """'삼진↑' 의 화살표가 다음 줄로 떨어지지 않게 낱말에 붙인다(WORD JOINER)."""
    return text.replace('↑', '⁠↑').replace('↓', '⁠↓')


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
    label = '익스트림 모드' if _mode(request) == Modes.EXTREME else '라이트 모드'
    return {'section': section, 'current_game_version': Versions.CURRENT, 'env_enabled': Env.enabled(),
            'game_mode': _mode(request), 'game_label': label, 'game_title': '야구선수 키우기 ' + label,
            'extreme_public': Modes.public_enabled(),
            'regions': W.REGIONS, 'teams': [R.TEAM[c] for c, _n, _c in R.TEAMS],
            'styles': X.STYLES, 'bat_positions': L.POSITIONS, 'pit_positions': X.PIT_POSITIONS,
            'roles': R.ROLES}


def _plan_key(c):
    p = c.pending or {}
    raw = [c.pk, c.year, p.get('kind'), p.get('event'), p.get('intl')]
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:24]


def _save_plan_draft(c, data):
    """상점 POST와 함께 온 미완성 선택. 현재 비시즌에만 보관한다."""
    if '_draft_key' not in data:
        return
    if (c.pending or {}).get('kind') != 'plan' or data['_draft_key'] != _plan_key(c):
        raise X.LiteError('이미 처리했거나 바뀐 장면이에요. 현재 화면을 다시 확인해 주세요.')
    allowed = {p[0] for p in X.PROGRAMS[c.role]} - set(X.train_rules(c)['locked'])
    programs = list(dict.fromkeys(p for p in data.getlist('_draft_program') if p in allowed))[:2]
    event = (c.pending or {}).get('event')
    event_choices = {x[0] for x in X.EVENTS[event]['choices']} if event else set()
    draft = {'programs': programs, 'intensity': data.get('_draft_intensity', 'normal'),
             'event_choice': data.get('_draft_event_choice', ''),
             'intl': {k: data.get('_draft_intl_' + k, '') for k in c.pending.get('intl') or []}}
    if draft['intensity'] not in X.INTENSITY:
        draft['intensity'] = 'normal'
    if draft['event_choice'] not in event_choices:
        draft['event_choice'] = ''
    draft['intl'] = {k: v for k, v in draft['intl'].items() if v in ('go', 'skip')}
    if Env.enabled() and data.get('_draft_routine') in Env.ROUTINES:
        draft['routine'] = data['_draft_routine']
    c.pending = dict(c.pending, draft=draft)


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
                   mine=list(mine.filter(retired_at__isnull=False)[:10]), default_name=name, quit_wait=X.quit_wait(mine),
                   quit_wait_text=X.wait_text(X.quit_wait(mine)),
                   hall=X.hall('kbo', limit=5, mode=_mode(request)), school_groups=_school_groups())
        return render(request, 'community/rookie_lite.html', ctx)
    pend = c.pending or {}
    fl = c.flags or {}
    fx, mfx, afx = fl.get('awaken_fx'), fl.get('moment_fx'), fl.get('award_fx')
    if fx or mfx or afx:                                       # 각성·결정적 순간·수상 연출 — 한 번 보여 주고 지운다
        c.flags = {k: v for k, v in c.flags.items() if k not in ('awaken_fx', 'moment_fx', 'award_fx')}
        c.save(update_fields=['flags'])
    ctx.update(mode=pend.get('kind', 'plan'), retire_at=X.Bloom.retirement_limit(c, X.RETIRE_AT),
               retire_text=f'{X.Bloom.retirement_limit(c, X.RETIRE_AT)}세, 이제 유니폼을 벗을 때가 됐어요. 그동안 정말 수고 많았어요.',
               **_identity(c), seasons=_season_rows(c), awaken_fx=fx, moment_fx=mfx,
               award_fx=afx, played=c.seasons.count(), quit_min=X.QUIT_MIN_SEASONS,
               playback=Presentation.receipt(pend.get('playback')), board_from=(pend.get('playback') or {}).get('from', 0))
    ctx['peers'] = Peers.comparisons(c)
    if c.mode == Modes.EXTREME and pend.get('kind') == 'plan':
        event = Extreme.event_view(c)
        if event:
            event['has_contest'] = any(choice['contest'] for choice in event['choices'])
            for choice in event['choices']:
                choice['training_percent'] = round(choice['training'] * 100)
                choice['risk_percent'] = round(choice['risk'] * 100)
                choice['effects'] = Extreme.effect_line(choice['training'], choice['risk'], [
                    ('라이벌 신뢰', choice['trust']), ('존중', choice['respect']), ('경쟁', choice['rivalry'])])
        ctx['extreme_event'] = event
    if pend.get('kind') == 'plan':
        draft = pend.get('draft') or {}
        ctx.update(plan_key=_plan_key(c), plan_draft=draft,
                   draft_programs=draft.get('programs') or [],
                   draft_intl_go=[k for k, v in (draft.get('intl') or {}).items() if v == 'go'],
                   draft_intl_skip=[k for k, v in (draft.get('intl') or {}).items() if v == 'skip'])
        ctx['duty'] = X._duty_now(c)[2]
        ctx.update(shop=X.shop_view(c), coach=X.who_is(c, 'coding'), natl=S.national(X.cal_year(c)))
        rules = X.train_rules(c)
        labels = {p[0]: p[1] for p in X.PROGRAMS[c.role]}
        room = {k: X.room_of(c, k) for k in c.stats}
        ctx.update(programs=[{'code': code, 'label': lab, 'hint': _glue(hint), 'icon': PROGRAM_ICON.get(code, 'balance'),
                              'locked': code in rules['locked'], 'room': room.get(code)} for code, lab, hint, _e in X.PROGRAMS[c.role]],
                   banned=rules['banned'], banned_text=' + '.join(labels[p] for p in rules['banned']),
                   intensity=[{'code': k, 'label': v[0],
                                'risk': round(X.injury_odds(c, k, ((c.flags or {}).get('tired') or {}).get('injury', 0.0), known_only=True) * 100)}
                               for k, v in X.INTENSITY.items()],
                   gear_cut=round((1 - X.gear_cut(c)) * 100),
                   event=X.event_view(c, pend.get('event')), intl=X.intl_view(c, pend.get('intl') or []),
                   offseason=(c.flags or {}).get('press') or [])
        step = 1 + bool(ctx['intl']) + bool(ctx['event'])
        ctx['steps'] = {'intl': 1, 'event': 1 + bool(ctx['intl']), 'train': step, 'power': step + 1, 'routine': step + 2}
        if Env.enabled():                                                   # 경기 전 대비 — 시즌 루틴과 올 시즌 예보
            games = X.GAMES.get(c.league, 120)
            fixtures = Universe.club_fixtures(c.league, games, c.club) if W.is_pro(c.league) else ()
            last = draft.get('routine') or ((c.flags or {}).get('routine') or {}).get('key', '')
            ctx.update(routines=Env.routine_choices(last, c.role), forecast=Env.forecast(c, c.league, games, fixtures))
            for routine in ctx['routines']:
                routine['icon'] = EnvUI.ROUTINE_ICONS[routine['key']]
    elif pend.get('kind') == 'review':
        s = c.seasons.filter(year=pend.get('year')).first()
        ctx.update(_board_ctx(c, s))
        ctx.update(season_line=L.line_view(c.role, s.totals) if s and s.totals else None,
                   deltas=[{'label': lab, 'value': (s.deltas or {}).get(k, 0), 'why': ((s.deltas or {}).get('_why') or {}).get(k, [])}
                           for k, lab, _w in R.ROLES[c.role]['stats']] if s else [],
                   moments=pend.get('moments') or [],
                   drops=[], press=(s.press or []) if s else [], reactions=X.season_reactions(c, s) if s else [],
                   splits=[dict(x, lg=W.league(x['league'])['name'], club_name=W.club_short(x['league'], x['club']))
                           for x in (s.splits or [])] if s and len(s.splits or []) > 1 else [],
                   meet_next=bool((c.flags or {}).get('move')))
        ctx['drops'] = [d for d in ctx.get('deltas') or [] if d['value'] < 0]
        ctx['series_boards'] = list(s.series or []) if s is not None and Series.enabled() else []
        if s is not None and Env.enabled() and s.env:
            ctx['env_rows'] = Env.split_rows(c.role, s.env.get('splits'))
            ctx['env_routine'] = Env.ROUTINES.get(s.env.get('routine'), ('', ''))[0]
            ctx['env_groups'] = EnvUI.split_groups(c.role, ctx['env_rows'])
        ctx['trait_discoveries'] = EnvUI.discoveries(c, s)
    elif pend.get('kind') == 'decision':
        ctx['decision'] = X.decision_view(c)
        if pend.get('what') == 'meeting' and pend.get('phase') == 'mid' and pend.get('half'):
            sp = pend['half']['splits'][0]
            code = sp['league']
            ctx.update(season={'age': c.age, 'duty': sp['duty'], 'months': [
                {'label': X._chunks(code)[j], 'line': X._short(c.role, sp['chunks'][j] or {}),
                 'hot': X._hot(c.role, sp['chunks'][j] or {})} for j in range(3)]},
                season_year=X.cal_year(c), season_league=W.league(code)['name'],
                season_club=W.club_label(code, sp['club']), season_partial=True)
        if pend.get('what') == 'moment':                     # 정규시즌 전광판을 먼저 다 보고 승부처로
            ctx.update(_board_ctx(c, c.seasons.filter(year=pend.get('year')).first()))
    return render(request, 'community/rookie_lite.html', ctx)


def _board_ctx(c, s) -> dict:
    """시즌 전광판(_lite_board.html) 맥락."""
    if not s:
        return {'season': None}
    return {'season': s, 'season_league': W.league(s.league)['name'], 'season_club': W.club_label(s.league, s.club),
            'season_year': X.cal_year(c, s.year),
            'season_rings': [a['label'] for a in (s.awards or []) if a.get('kind') == 'ring']}   # 어느 대회 우승인지


@require_POST
def lite_new(request):
    try:
        number = int(request.POST.get('number') or 0)
    except ValueError:
        number = 0
    role = request.POST.get('role', '')
    from .. import rookie_avatar as Avatar
    try:
        avatar = Avatar.clean(request.POST)
        with transaction.atomic():
            c = X.create(request.user if request.user.is_authenticated else None, name=request.POST.get('name', ''), role=role,
                     position=request.POST.get(f'position_{role}', ''), style=request.POST.get(f'style_{role}', ''),
                     region=request.POST.get('region', ''), team=request.POST.get('team', ''), number=number, rng=_rng(),
                     guest='' if request.user.is_authenticated else _guest(request, make=True),
                     school=request.POST.get('school', ''), mode=_mode(request),
                     throwing=request.POST.get('throwing', 'R'), batting=request.POST.get('batting', 'R'))
            Avatar.save(c, avatar)
    except (X.LiteError, ValueError) as ex:
        messages.warning(request, str(ex))
    return redirect(_route(request, 'home'))


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
            if action == 'extreme_event':
                if c.mode != Modes.EXTREME:
                    raise X.LiteError('익스트림 전용 이벤트예요.')
                result = Extreme.apply_choice(c, request.POST.get('event_id', ''), request.POST.get('choice', ''), rng)
                c.save(update_fields=['flags', 'stats', 'ovr', 'best_ovr', 'updated_at'])
                changes = ' · '.join(f"{item['label']} {signed(item['delta'])}" for item in result.get('stats', []) if signed(item['delta']) != '0')
                outcome = '도전 성공' if result['success'] else '도전 실패' if result['success'] is False else '선택 반영'
                messages.info(request, outcome + (' — ' + changes if changes else '') + '. 이번 시즌의 훈련·부상 보정에도 반영했어요.')
            elif action == 'play':
                if pend.get('kind') != 'plan':
                    raise X.LiteError('지금은 시즌을 시작할 차례가 아니에요.')
                X.check_programs(c, request.POST.getlist('program'))          # 훈련 두 개·잠김·같은 조합부터 알려 준다
                intensity = request.POST.get('intensity', '')
                choice = request.POST.get('event_choice', '')
                if pend.get('event') and choice not in [k for k, _l, _h in X.EVENTS[pend['event']]['choices']]:
                    raise X.LiteError('비시즌 이벤트에 어떻게 할지 먼저 골라 주세요.')
                intl = {k: request.POST.get(f'intl_{k}', '') for k in pend.get('intl') or []}
                if X.run_season(c, request.POST.getlist('program'), intensity, choice, rng, intl=intl,
                                routine=request.POST.get('routine', '')) is None:
                    messages.info(request, '시즌 중 선택할 장면이 있어요. 내용을 확인하고 답해 주세요.')
            elif action == 'next':
                X.next_season(c, rng)
            elif action == 'decide':
                scene = X.decision_view(c) or {}
                selected = next((item for item in scene.get('choices', []) if item['key'] == request.POST.get('choice')), {})
                if pend.get('encounter') or pend.get('what') in ('negotiation', 'contract_optout', 'bloom', 'bloom_result') or (pend.get('what') == 'posting' and pend.get('offers')) or (pend.get('what') == 'meeting' and (X.decision_view(c) or {}).get('contract_scene')):
                    expected = (X.decision_view(c) or {}).get('id')
                    if expected != request.POST.get('event_id', ''):
                        raise X.LiteError('이미 처리했거나 바뀐 장면이에요. 현재 화면을 다시 확인해 주세요.')
                text = X.decide(c, request.POST.get('what', ''), request.POST.get('choice', ''), rng,
                                school=request.POST.get('school', ''))
                if text and c.pending.get('playback'):
                    c.pending['playback'] = dict(c.pending['playback'], selection=selected.get('label', ''),
                                                 selection_hint=selected.get('hint', ''))
                c.save()
                if text:
                    messages.info(request, text)
                if c.retired_at:
                    return redirect(f"{reverse(_route(request, 'card'), args=[c.pk])}?new=1")
            elif action == 'buy':
                _save_plan_draft(c, request.POST)
                messages.info(request, X.buy(c, request.POST.get('item', ''), request.POST.get('code', '')))
                c.save()
                return redirect(reverse(_route(request, 'home')) + '#rl-shop')
            elif action == 'buyplan':
                _save_plan_draft(c, request.POST)
                messages.info(request, X.buy_plan(c, {'bat': request.POST.get('bat', ''), 'guard': request.POST.get('guard', ''),
                                                      'care': request.POST.getlist('care'), 'fan': request.POST.get('fan'),
                                                      'camp': request.POST.get('camp', ''), 'camp_on': request.POST.get('camp_on')}))
                c.save()
                return redirect(reverse(_route(request, 'home')) + '#rl-shop')
            elif action == 'quit':
                X.check_quit(c)                                       # 만든 뒤 5시즌 전에는 못 그만둔다
                if request.POST.get('confirm') != 'yes':
                    raise X.LiteError('은퇴하려면 확인 칸에 체크해 주세요.')
                messages.info(request, X.retire(c, '스스로'))
                c.save()
                return redirect(f"{reverse(_route(request, 'card'), args=[c.pk])}?new=1")
            else:
                raise X.LiteError('다시 시도해 주세요.')
    except (X.LiteError, Extreme.ExtremeError) as ex:
        messages.warning(request, str(ex))
    return redirect(_route(request, 'home'))


def lite_hall(request):
    version = Versions.selected(request.GET.get('version'))
    tab = request.GET.get('lg', '')
    tab = tab if tab in dict(HALL_TABS) else 'kbo'
    role = request.GET.get('role', '')
    role = role if role in dict(HALL_ROLES) else ''
    every = [dict(r, url=reverse(_route(request, 'career'), args=[r['c'].pk])) for r in X.hall(tab, limit=2000, version=version, mode=_mode(request))]
    rows = X.hall(tab, role=role, version=version, mode=_mode(request)) if role else every[:50]
    return render(request, 'community/rookie_lite_hall.html',
                  dict(_base(request, 'hall'), tab=tab, tabs=HALL_TABS, rows=rows, tab_name=dict(HALL_TABS)[tab],
                       role=role, role_tabs=HALL_ROLES, hall_version=version, version_tabs=Versions.CHOICES,
                       lineup=None if role else X.best_lineup(every)))   # 라인업은 투수·타자 '전체'일 때


def lite_today(request):
    """일일 랭킹(2026-10-19 사용자 요청) — 그날 은퇴한 커리어를 명예의 전당과 같은 순서로. 어제 것도 볼 수 있다."""
    version = Versions.selected(request.GET.get('version'))
    tab = request.GET.get('lg', '')
    tab = tab if tab in dict(HALL_TABS) else 'kbo'
    role = request.GET.get('role', '')
    role = role if role in dict(HALL_ROLES) else ''
    ago = 1 if request.GET.get('d') == '1' else 0
    start, end = X.day_bounds(ago)
    rows = X.hall(tab, role=role, since=start, until=end, version=version, mode=_mode(request))
    return render(request, 'community/rookie_lite_today.html',
                  dict(_base(request, 'today'), tab=tab, tabs=HALL_TABS, rows=rows, tab_name=dict(HALL_TABS)[tab],
                       role=role, role_tabs=HALL_ROLES, daily=True, ago=ago, day=start,
                       hall_version=version, version_tabs=Versions.CHOICES,
                       day_tabs=[('', '오늘'), ('1', '어제')]))


def lite_career(request, pk: int):
    c = get_object_or_404(LiteCareer.objects.select_related('user'), pk=pk, mode=_mode(request))
    if is_hidden(c.user) and c.user_id != request.user.id:
        raise Http404
    awards = _award_sum(c)
    return render(request, 'community/rookie_lite_career.html',
                  dict(_base(request, 'hall'), **_identity(c), seasons=_season_rows(c), line=X.career_line(c),
                       awards=awards, is_me=_is_mine(request, c), peak=W.league(c.peak or 'hs')['name'],
                       high=X.career_high(c)))


AWARD_ORDER = {'mvp': 0, 'ace': 1, 'gg': 2, 'title': 3, 'rookie': 4, 'ring': 5, 'national': 6, 'minor': 7, 'allstar': 8}


def _award_sum(c) -> list:
    """수상을 종류별로 묶어 센다 — 'KBO MVP 17회'. 시즌마다 받은 상은 연표에 있다(긴 목록이 화면을 덮지 않게)."""
    groups = {}
    for s in c.seasons.all():
        for a in s.awards:
            lg = W.short(s.league)
            # '퓨처스 MVP'·'고교 최우수선수'처럼 라벨에 리그 이름이 이미 있으면 한 번 더 붙이지 않는다.
            label = a['label'] if a['kind'] in ('national',) or a['label'].startswith(lg) else f"{lg} {a['label']}"
            g = groups.setdefault((a['kind'], label), {'kind': a['kind'], 'label': label, 'n': 0, 'first': s.age})
            g['n'] += 1
    return sorted(groups.values(), key=lambda g: (AWARD_ORDER.get(g['kind'], 9), -g['n'], g['first']))


# ───────────────────────────── 은퇴 카드(2026-10-18 사용자 요청: 캡처해서 자랑, 회원은 보관함에서 다시 보기)
def _card(c) -> dict:
    """은퇴 카드 한 장 — 통산 줄·수상 묶음·거쳐 간 팀·등급(레전드·스타·프로·루키)."""
    seasons = list(c.seasons.all())
    pro = [s for s in seasons if s.games and W.is_pro(s.league)]
    played = [s for s in seasons if s.games]
    line = X.career_line(c)
    total = line['pro'] or line['development'] or (L.line_view(c.role, X._sum_totals(played)) if played else None)
    kinds = [a for s in seasons for a in s.awards]
    gg = sum(1 for a in kinds if a['kind'] == 'gg')
    titles = sum(1 for a in kinds if a['kind'] in ('title', 'ace'))
    gg_by = {}
    for s in seasons:
        for a in s.awards:
            if a['kind'] == 'gg':
                gg_by[s.league] = gg_by.get(s.league, 0) + 1
    gg_label = L.AWARD_STYLE.get(max(gg_by, key=gg_by.get), {}).get('gg', '골든글러브') if gg_by else '골든글러브'
    golds = sum(1 for a in kinds if a['kind'] == 'national' and ('금메달' in a['label'] or a['label'].endswith('우승')))
    clubs = []
    for s in pro:
        name = W.club_short(s.league, s.club)
        if not clubs or clubs[-1] != name:
            clubs.append(name)
    best = X.career_high(c, seasons)                       # 가장 높은 무대에서 제대로 뛴 시즌 가운데
    best_ovr = max([s.ovr_end for s in seasons] or [c.best_ovr])
    if c.mvp >= 2 or best_ovr >= 80 or (c.mvp and golds):
        tier, tier_label = 'legend', '레전드'
    elif c.mvp or best_ovr >= 72 or gg + titles >= 4:
        tier, tier_label = 'star', '스타'
    elif any(s.league in W.TOP_LEAGUES for s in pro):
        tier, tier_label = 'pro', '프로'
    else:
        tier, tier_label = 'rookie', '루키'
    badges = [(c.mvp, 'MVP'), (gg, gg_label), (titles, '타이틀'), (c.rings, '우승'), (golds, '대표팀 우승')]
    t = total or {}

    def n(k):
        return f"{int(t.get(k) or 0):,}"
    if c.role == 'pitcher':
        stats = [('경기', n('g')), ('승', n('w')), ('패', n('l')), ('세이브', n('sv')), ('평균자책점', t.get('era_text') or '-'),
                 ('탈삼진', n('so'))]
    else:
        stats = [('경기', n('g')), ('타율', t.get('avg_text') or '-'), ('안타', n('h')), ('홈런', n('hr')), ('타점', n('rbi')),
                 ('OPS', t.get('ops_text') or '-')]
    first, last = X.cal_year(c, 1), X.cal_year(c, max(1, c.year - 1))
    eok, rest = divmod(int(c.earnings or 0), 10000)
    money = f'{eok:,}억' if eok else X.man(c.earnings)
    team_name = W.club_label(c.league, c.club)
    prefix, _sp, nick = team_name.rpartition(' ')
    return {'palette': _palette(c.league, c.club), 'team_prefix': prefix, 'team_nick': nick or team_name,
            'keys': [('최상위 리그 WAR', X.Balance.totals(c)['war']), ('최고 OVR', round(best_ovr, 1)), ('통산 수입', money)],
            'jersey': _jersey_name(c.name), 'serial': f'{c.pk:04d}',
            'tier': tier, 'tier_label': tier_label, 'line': total, 'war': round(sum(s.war for s in pro), 1), 'money': money,
            'best_ovr': round(best_ovr, 1), 'years': f'{first}–{last}', 'seasons': len(played),
            'clubs': clubs[:5], 'more_clubs': max(0, len(clubs) - 5),
            'badges': [{'n': k, 'label': lab} for k, lab in badges if k],
            'honors': [{'n': k, 'label': lab} for k, lab in badges], 'stats': stats,
            'best': best,
            'peak': W.league(c.peak or 'hs')['name'], 'peak_short': W.short(c.peak or 'hs'), 'epithet': X.EPITHET.get(c.style, ''),
            'headline': X.retire_headline(c, len(played))}


def lite_card(request, pk: int):
    c = get_object_or_404(LiteCareer.objects.select_related('user'), pk=pk, mode=_mode(request))
    if is_hidden(c.user) and c.user_id != request.user.id:
        raise Http404
    if not c.retired_at:
        return redirect(_route(request, 'career'), pk=pk)
    return render(request, 'community/rookie_lite_card.html',
                  dict(_base(request, 'cards'), **_identity(c), card=_card(c), is_me=_is_mine(request, c),
                       fresh=request.GET.get('new') == '1' and _is_mine(request, c)))


def lite_card_png(request, pk: int, kind: str = 'card'):
    """은퇴 카드 PNG — kind 'card'(1080×1350, 저장·SNS 올리기) · 'og'(1200×630, 링크 미리보기) · 'story'(1080×1920, 인스타 스토리)."""
    c = get_object_or_404(LiteCareer.objects.select_related('user'), pk=pk, mode=_mode(request))
    if (is_hidden(c.user) and c.user_id != request.user.id) or not c.retired_at or kind not in K.SHOTS:
        raise Http404
    return K.png_response(c.pk, kind, f'{c.name}-은퇴카드.png', request.GET.get('download') == '1', render_png,
                          lambda: render_to_string('community/games/lite_card_shot.html',
                                                   dict(_identity(c), card=_card(c), kind=kind)))


def lite_cards(request):
    """내 은퇴 카드 보관함 — 회원은 계정의 은퇴 선수 모두, 손님은 이 브라우저에서 은퇴한 선수(로그인하면 보관)."""
    _claim(request)
    rows = [dict(_identity(c), card=_card(c)) for c in _mine(request).filter(retired_at__isnull=False).order_by('-retired_at')[:60]]
    return render(request, 'community/rookie_lite_cards.html', dict(_base(request, 'cards'), rows=rows))
