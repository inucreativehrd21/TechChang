"""테크창 삼국지 화면(규칙 community/samguk_rules.py, DB community/samguk.py).

오늘의 천하(본 게임)는 PC·모바일 모두. 장원·객잔·도감·방명록·친구는 PC 전용(6단계부터, 설계 1.1).
공개 전(SAMGUK_ENABLED 꺼짐)에는 운영진만 들어간다. 행동은 POST 한 번 = 군령 사용 한 번이고, 서버가 판정한다.
화면 골격은 기능 확인용이다 — 디자인은 Codex 가 sg- 클래스에 입힌다.
"""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_GET, require_POST

from .. import samguk as S
from .. import samguk_board as B
from .. import samguk_data as D
from .. import samguk_rules as R
from ..models import SamgukDay

TUTORIAL_KEY = 'samguk_tutorial'
TUTORIAL_RESULT_KEY = 'samguk_tutorial_result'
TUTORIAL_HINTS = (
    '먼저 허창을 다스려 금과 군량을 모아요. [내정]을 눌러 보세요.',
    '병사가 있어야 싸울 수 있어요. [징병]으로 병력을 늘려 보세요.',
    '허창에 순욱이 머물고 있어요. 조조로 [등용]해 보세요. 모자란 설득력은 금으로 채워요.',
    '맞닿은 낙양을 [정찰]해서 지키는 장수와 병력을 확인해 보세요.',
    '이제 [출정]으로 진류나 낙양을 쳐 보세요. 출정은 군령이 2 들어요.',
    '군령을 다 쓰면 판이 끝나요. 점수는 차지한 도시·멸망시킨 군벌·등용한 장수로 매겨요.',
)


def _gate(request):
    if not S.allowed(request.user):
        raise Http404


def _render_game(request, screen, context):
    # 공통 로더는 마지막 경로 앞에 mobile/을 넣어요. 삼국지는 중첩 폴더라
    # 실제 모바일 wrapper 경로를 명시하고, 본문 조각은 계속 공용으로 써요.
    if request.headers.get('X-Samguk-Partial') == '1':
        titles = {'home': '오늘의 천하', 'tutorial': '튜토리얼', 'ranking': '순위',
                  'replay': '천하인 기보', 'manor': '장원', 'codex': '장수 도감',
                  'inn': '객잔', 'pc_only': 'PC 이용 안내'}
        response = JsonResponse({
            'version': 1, 'screen': screen, 'url': request.get_full_path(),
            'title': f'테크창 삼국지 - {titles[screen]}',
            'html': render_to_string(f'community/samguk/_{screen}_body.html', context, request=request),
            'messages': [{'text': str(m), 'level': m.tags} for m in messages.get_messages(request)],
        })
        response['Cache-Control'] = 'no-store'
    else:
        prefix = 'community/mobile/samguk' if getattr(request, 'is_mobile', False) else 'community/samguk'
        response = render(request, f'{prefix}/{screen}.html', context)
    patch_vary_headers(response, ('X-Samguk-Partial',))
    return response


# ── 화면에 넘길 판 모양 ───────────────────────────────────────────────────
def _officer(code: str) -> dict:
    g = D.GENERAL[code]
    return {'code': code, 'name': g.name, 'tier': g.tier, 'stars': D.TIER_STARS[g.tier], 'group': D.GROUPS[g.group],
            'lead': g.lead, 'war': g.war, 'intl': g.intl, 'pol': g.pol, 'skill': D.SKILLS[g.skill][0]}


def _owner_label(state: dict, who: str) -> str:
    if who == R.ME:
        return '내 땅'
    if who == R.NONE:
        return '빈 성'
    if who == R.YELLOW:
        return '황건적'
    return state['lords'].get(who, {}).get('name', who)


def board_view(state: dict) -> dict:
    mine = set(R.mine(state))
    near = {n for c in mine for n in R.links(state, c)}
    cities = []
    for code, v in state['cities'].items():
        city = D.CITY[code]
        visible = code in mine or code in state['scouted']
        cities.append({
            'code': code, 'name': city.name, 'x': city.x, 'y': city.y, 'grade': city.grade, 'value': city.value,
            'owner': v['owner'], 'owner_label': _owner_label(state, v['owner']), 'mine': code in mine,
            'near': code in near and code not in mine, 'visible': visible,
            'troops': v['troops'] if visible else None,
            'officers': [_officer(o) for o in v['officers']] if visible else [],
            'links': R.links(state, code),
            'targets': [{'code': n, 'name': D.CITY[n].name, 'owner': _owner_label(state, state['cities'][n]['owner']),
                         'cost': R.action_cost(state, {'kind': 'attack', 'from': code, 'to': n})}
                        for n in R.links(state, code) if state['cities'][n]['owner'] != R.ME],
        })
    cities.sort(key=lambda c: (not c['mine'], not c['near'], c['name']))
    recruits = []
    for code in sorted(mine):
        here = [D.GENERAL[o] for o in state['cities'][code]['officers']]
        for cap, pool in ((False, state['free'].get(code, [])), (True, state['captives'].get(code, []))):
            for t in pool:
                target = D.GENERAL[t]
                options = []
                for by in here:
                    gold = R.recruit_gold_needed(state, by, target, cap)
                    options.append({'by': by.code, 'name': by.name, 'persuade': R.persuade(state, by, target, 0),
                                    'gold': gold})
                recruits.append({'city': code, 'city_name': D.CITY[code].name, 'target': _officer(t), 'captive': cap,
                                 'need': R.recruit_need(target, cap), 'options': options})
    return {
        'cities': cities, 'recruits': recruits, 'ap_left': R.ap_left(state),
        'ap_total': state['ap_base'] + state['ap_bonus'], 'ap_bonus': state['ap_bonus'],
        'gold': state['gold'], 'food': state['food'], 'over': state['over'], 'score': R.score(state),
        'conscript_gold': R.CONSCRIPT_COST,
        'faction': D.FACTIONS.get(state['faction'], ''), 'event': B.EVENTS.get(state.get('event') or '', ('', '')),
        'lords': [{'code': k, 'name': v['name'], 'alive': v['alive'], 'ally': v.get('ally'), 'feud': v.get('feud'),
                   'boss': v.get('boss')} for k, v in sorted(state['lords'].items())],
    }


def _action_from_post(post) -> dict:
    kind = post.get('kind', '')
    a = {'kind': kind}
    for key in ('city', 'from', 'to', 'target', 'by', 'mode', 'other'):
        if post.get(key):
            a[key] = post.get(key)
    if kind == 'attack':
        a['officers'] = post.getlist('officers')
        a['troops'] = _int(post.get('troops'))
    if kind == 'recruit':
        a['gold'] = _int(post.get('gold'))
    return a


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


# ── 본 게임 ─────────────────────────────────────────────────────────────
@require_GET
def home(request):
    _gate(request)
    S.catch_up()
    day = S.get_day()
    ctx = {'day': day, 'event': B.EVENTS.get(day.board.get('event'), ('', '')),
           'factions': D.FACTIONS, 'ranking': S.ranking(day, 10), 'faction_board': S.faction_board(day)}
    if not request.user.is_authenticated:
        ctx['step'] = 'guest'
        return _render_game(request, 'home', ctx)
    m = S.member(request.user)
    ctx['member'] = m
    ctx['faction_ready'] = S.faction_change_ready(m)
    if not m.faction:
        ctx['step'] = 'faction'
    elif m.tutorial == 'none':
        ctx['step'] = 'tutorial_prompt'
    else:
        run = S.today_run(request.user, day)
        if run is None:
            ctx['step'] = 'start'
            ctx['starts'] = [{'index': i, 'city': D.CITY[s['city']].name, 'code': s['city'],
                              'officers': [_officer(o) for o in s['officers']],
                              'free': [_officer(o) for o in day.board['free'].get(s['city'], [])],
                              'near': [D.CITY[n].name for n in D.CITY[s['city']].links]}
                             for i, s in enumerate(day.board['starts'])]
            ctx['bonus_ready'] = S.bonus_total(request.user, day.date)
        else:
            ctx['step'] = 'play'
            ctx['run'] = run
            ctx['view'] = board_view(run.state)
            ctx['legends'] = _legend_events(request.user, run)
            ctx['seq'] = run.actions.count()
            ctx['last'] = list(run.actions.order_by('-seq')[:6])
    return _render_game(request, 'home', ctx)


def _legend_events(user, run) -> list:
    """판 위 전설 이벤트 + 보낼 수 있는 내 장수(그 도시나 맞닿은 내 도시에 있는 장수)."""
    from .. import samguk_legends as L
    st = run.state
    out = []
    for ev in L.board_legends(user, run):
        near = [c for c in R.mine(st) if c == ev['city'] or R.adjacent(c, ev['city'])]
        ev['officers'] = [_officer(o) for c in near for o in st['cities'][c]['officers']]
        out.append(ev)
    return out


@login_required
@require_POST
def choose_faction(request):
    _gate(request)
    try:
        S.set_faction(request.user, request.POST.get('faction', ''))
    except S.GameError as e:
        messages.error(request, str(e))
    return redirect('community:samguk_home')


@login_required
@require_POST
def start(request):
    _gate(request)
    try:
        S.start(request.user, _int(request.POST.get('start')))
    except S.GameError as e:
        messages.error(request, str(e))
    return redirect('community:samguk_home')


@login_required
@require_POST
def act(request):
    _gate(request)
    try:
        _run, result = S.act(request.user, _action_from_post(request.POST), seq=request.POST.get('seq'))
    except S.GameError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, result.get('text', ''))
        for ev in result.get('npc', []):
            messages.info(request, ev.get('text', ''))
        if result.get('legends'):
            from .. import samguk_legends as L
            names = ', '.join(dict.fromkeys(L.SERIES[s]['name'] for s in result['legends']))
            messages.info(request, f'전설이 한 걸음 나아갔어요: {names}')
    return redirect(reverse('community:samguk_home') + '#sg-board')


# ── 튜토리얼(설계 2.1) — 기록을 남기지 않는다. 판은 세션에만 둔다 ─────────────────
@require_POST
def tutorial_choice(request):
    _gate(request)
    choice = request.POST.get('choice')
    if choice == 'skip':
        if request.user.is_authenticated:
            S.set_tutorial(request.user, 'skipped')
        return redirect('community:samguk_home')
    request.session.pop(TUTORIAL_KEY, None)
    request.session.pop(TUTORIAL_RESULT_KEY, None)
    return redirect('community:samguk_tutorial')


@require_GET
def tutorial(request):
    _gate(request)
    board = B.tutorial()
    state = request.session.get(TUTORIAL_KEY)
    if not state:
        state = R.new_run(board, 'wei', 0, seed=0)
        request.session[TUTORIAL_KEY] = state
        request.session.pop(TUTORIAL_RESULT_KEY, None)
    step = min(state['turn'], len(TUTORIAL_HINTS) - 1)
    if state['over'] and request.user.is_authenticated:
        S.set_tutorial(request.user, 'done')
    return _render_game(request, 'tutorial', {
        'view': board_view(state), 'seq': state['turn'], 'hint': TUTORIAL_HINTS[step], 'tutorial': True,
        'last': [{'result': request.session[TUTORIAL_RESULT_KEY]}] if request.session.get(TUTORIAL_RESULT_KEY) else [],
    })


@require_POST
def tutorial_act(request):
    _gate(request)
    board = B.tutorial()
    state = request.session.get(TUTORIAL_KEY) or R.new_run(board, 'wei', 0, seed=0)
    try:
        state, result = R.apply(board, state, _action_from_post(request.POST))
    except R.RuleError as e:
        messages.error(request, str(e))
    else:
        request.session[TUTORIAL_KEY] = state
        request.session[TUTORIAL_RESULT_KEY] = result
        messages.success(request, result.get('text', ''))
        for ev in result.get('npc', []):
            messages.info(request, ev.get('text', ''))
    return redirect(reverse('community:samguk_tutorial') + '#sg-board')


# ── 순위·기보 ────────────────────────────────────────────────────────────
@require_GET
def ranking(request):
    _gate(request)
    S.catch_up()
    when = request.GET.get('date')
    day = None
    if when:
        try:
            day = SamgukDay.objects.filter(date=date.fromisoformat(when)).first()
        except ValueError:
            day = None
    day = day or S.get_day()
    return _render_game(request, 'ranking', {
        'day': day, 'rows': S.ranking(day, 100), 'faction_board': S.faction_board(day), 'factions': D.FACTIONS,
        'recent': SamgukDay.objects.filter(status='closed').order_by('-date')[:14],
    })


@require_GET
def replay(request, day: str):
    """닫힌 날의 1위 기보 — 판이 끝난 뒤에만 공개한다(같은 판 공략이 새지 않게)."""
    _gate(request)
    try:
        d = SamgukDay.objects.get(date=date.fromisoformat(day), status='closed')
    except (ValueError, SamgukDay.DoesNotExist):
        raise Http404 from None
    run = d.runs.filter(rank=1).select_related('user', 'user__profile').first()
    if run is None:
        raise Http404
    return _render_game(request, 'replay', {
        'day': d, 'run': run, 'name': S.display_name(run.user), 'actions': run.actions.all(),
        'start_city': D.CITY[run.start_city].name, 'score': R.score(run.state),
    })


# ── 장원 층(PC 전용, 설계 1.1) — 도감·객잔 ─────────────────────────────────────
def _pc_only(request):
    """모바일이면 기능 대신 안내 카드. PC 버전을 직접 고른 사람은 막지 않는다(force_version 쿠키 → is_mobile False)."""
    if getattr(request, 'is_mobile', False):
        return _render_game(request, 'pc_only', {})
    return None


@login_required
@require_GET
def codex(request):
    _gate(request)
    blocked = _pc_only(request)
    if blocked:
        return blocked
    from .. import samguk_manor as M
    return _render_game(request, 'codex', {'codex': M.codex_view(request.user)})


@login_required
@require_GET
def inn(request):
    _gate(request)
    blocked = _pc_only(request)
    if blocked:
        return blocked
    from .. import samguk_manor as M
    today = M.inn_today(request.user)
    rumor = M.inn_traveler(request.user, today)
    have = M.recruited_codes(request.user)
    guests = [{**_officer(c), 'known': c in have, 'era': D.ERAS[D.GENERAL[c].era], 'note': D.GENERAL[c].note}
              for c in today.offers]
    return _render_game(request, 'inn', {'inn': today, 'guests': guests, 'rumor': rumor})


@login_required
@require_POST
def inn_pick(request):
    _gate(request)
    if getattr(request, 'is_mobile', False):
        return redirect('community:samguk_inn')
    from .. import samguk_manor as M
    try:
        res = M.inn_pick(request.user, request.POST.get('code', ''))
    except S.GameError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, res['text'])
    return redirect('community:samguk_inn')


# ── 장원(PC 전용, 설계 7.1·7.2·7.4) ──────────────────────────────────────────
def _manor_ctx(request, owner):
    from .. import samguk_manor as M
    from .. import samguk_social as SO
    me = request.user
    ctx = {'owner': owner, 'owner_name': S.display_name(owner), 'is_mine': owner == me,
           'manor': M.manor_view(owner), 'guestbook': SO.guestbook_list(owner, me)}
    if owner == me:
        ctx['friends'] = [{'user': u, 'name': S.display_name(u)} for u in SO.friends(me)]
        ctx['incoming'] = [{'user': u, 'name': S.display_name(u)} for u in SO.incoming(me)]
        ctx['recruited'] = sorted((g for c in M.recruited_codes(me) if (g := M.display_general(c))),
                                  key=lambda g: (-g.tier, g.no, g.code))
        b = (S.member(me).beggar or {})
        ctx['beggar_left'] = M.BEGGAR_LINES - (b.get('count', 0) if b.get('day') == S.game_day().isoformat() else 0)
        ctx['visit'] = _visit_list(me)
        from .. import samguk_legends as L
        ctx['legends'] = L.legends_view(me)
    else:
        ctx['relation'] = SO.relation(me, owner)
    return ctx


def _visit_list(me, limit: int = 12) -> list:
    """방문 목록 — 친구 → 같은 세력 → 오늘 상위권 → 최근 활동(설계 7.2)."""
    from .. import samguk_social as SO
    from ..models import SamgukMember, SamgukRun
    out, seen = [], {me.pk}

    def add(user, why):
        if user.pk not in seen and len(out) < limit:
            seen.add(user.pk)
            out.append({'user': user, 'name': S.display_name(user), 'why': why})
    for u in SO.friends(me):
        add(u, '친구')
    mine = S.member(me)
    if mine.faction:
        for m in SamgukMember.objects.filter(faction=mine.faction).exclude(user=me).select_related('user', 'user__profile')[:20]:
            add(m.user, '같은 세력')
    for run in S.ranking(S.get_day(), 10):
        add(run.user, '오늘 상위권')
    for run in SamgukRun.objects.order_by('-updated_at').select_related('user', 'user__profile')[:30]:
        add(run.user, '최근 활동')
    return out


@login_required
@require_GET
def manor(request, pk: int | None = None):
    _gate(request)
    blocked = _pc_only(request)
    if blocked:
        return blocked
    from django.contrib.auth.models import User
    from django.shortcuts import get_object_or_404
    owner = request.user if pk is None else get_object_or_404(User, pk=pk, is_active=True)
    return _render_game(request, 'manor', _manor_ctx(request, owner))


@login_required
@require_POST
def manor_post(request):
    """장원 행동 하나: upgrade / decor / place / guestbook / gb_mod / friend / beggar / privacy."""
    _gate(request)
    if getattr(request, 'is_mobile', False):
        return redirect('community:samguk_manor')
    from django.contrib.auth.models import User
    from .. import samguk_manor as M
    from .. import samguk_social as SO
    what = request.POST.get('what', '')
    back = request.POST.get('back') or reverse('community:samguk_manor')
    if not back.startswith('/samguk/'):
        back = reverse('community:samguk_manor')
    me = request.user
    try:
        if what == 'upgrade':
            messages.success(request, M.upgrade(me, request.POST.get('building', ''))['text'])
        elif what == 'decor':
            messages.success(request, M.set_decor(me, request.POST.get('slot', ''), request.POST.get('decor', ''))['text'])
        elif what == 'place':
            messages.success(request, M.place(me, request.POST.get('slot', ''), request.POST.get('code', ''))['text'])
        elif what == 'beggar':
            res = M.beggar_talk(me, alms=request.POST.get('alms') == '1')
            messages.info(request, f'지나가는 거지: “{res["text"]}”')
        elif what == 'attempt':
            from .. import samguk_legends as L
            messages.success(request, L.attempt(me, request.POST.get('series', ''))['text'])
        elif what == 'privacy':
            from ..models import SamgukMember
            S.member(me)
            SamgukMember.objects.filter(user=me).update(hide_from_beggar=request.POST.get('hide') == '1')
            messages.success(request, '설정을 바꿨어요.')
        elif what in ('guestbook', 'friend'):
            other = User.objects.filter(pk=_int(request.POST.get('user')), is_active=True).first()
            if other is None:
                raise S.GameError('없는 사용자예요.')
            if what == 'guestbook':
                SO.guestbook_write(other, me, request.POST.get('text', ''))
                messages.success(request, '방명록에 인사를 남겼어요.')
            else:
                how = request.POST.get('how')
                if how == 'request':
                    rel = SO.friend_request(me, other)
                    messages.success(request, '친구가 되었어요.' if rel == 'friend' else '친구 신청을 보냈어요.')
                elif how == 'accept':
                    SO.friend_accept(me, other)
                    messages.success(request, '친구가 되었어요.')
                elif how == 'remove':
                    SO.friend_remove(me, other)
                    messages.success(request, '정리했어요.')
                elif how == 'block':
                    SO.block(me, other)
                    messages.success(request, '차단했어요.')
                elif how == 'unblock':
                    SO.unblock(me, other)
                    messages.success(request, '차단을 풀었어요.')
                else:
                    raise S.GameError('알 수 없는 요청이에요.')
        elif what == 'gb_mod':
            SO.guestbook_moderate(_int(request.POST.get('entry')), me, request.POST.get('how', ''))
            messages.success(request, '처리했어요.')
        else:
            raise S.GameError('알 수 없는 요청이에요.')
    except S.GameError as e:
        messages.error(request, str(e))
    return redirect(back)
