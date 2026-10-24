"""로컬 디자인 미리보기. 실제 선수·세션·결과를 만들거나 변경하지 않는다."""
from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
import random
from types import SimpleNamespace

from community import rookie_story as Story
from community import rookie_world as W
from community import rookie_card as K
from community import rookie_league as L
from community import rookie_pitching as Pitching
from community import rookie_balance_rules as Balance
from community import rookie_contracts as Contracts
from community import rookie_universe as Universe


SCENES = [
    ('opening', '선수 등록', '구장 카메라 진입', '◇'),
    ('season', '시즌 중계', '월별 기록과 시즌 결산', '▤'),
    ('awaken', '각성 성공', '새로운 별과 잠재력', '★'),
    ('awaken_fail', '각성 실패', '다음 도전을 준비해요', '☆'),
    ('homerun', '끝내기 홈런', '마지막 타석과 우승', '◉'),
    ('strikeout', '우승을 지킨 삼진', '투수의 마지막 아웃', 'K'),
    ('loss', '아쉬운 패배', '결과와 다음 시즌', '◌'),
    ('award', '시상식', '트로피와 시즌의 영예', '♜'),
    ('chain', '주요 연출 이어보기', '각성 · 승부 · 수상', '▷'),
    ('manager', '감독실 면담', '출전 기회와 신뢰', '▱'),
    ('interview', '기자 인터뷰', '팬과의 약속과 평판', '◍'),
    ('conduct', '일상과 행실', '회복과 인기 사이의 선택', '◈'),
    ('highlight', '시즌 중 승부처', '자신감이 바뀌는 한 번의 승부', 'K'),
    ('posting', '해외 관심 구단', '세 구단의 조건을 비교해요', '◇'),
    ('negotiation', '해외 계약 협상', '연봉과 역할을 조율해요', '▣'),
    ('cards', '구단별 선수 카드', '58구단 유니폼 컬렉션', '♧'),
    ('assignment', 'MLB 마이너행 통보', '계약 권리와 출전 기회', '▱'),
    ('optout', '선수 옵트아웃', '보장 연봉과 새 계약 사이', '◇'),
    ('rival', '다시 만난 경쟁자', '함께 훈련할지, 정면 승부할지', '◈'),
    ('world', '살아 있는 커리어 리그', '같은 대진표와 이어지는 경쟁자', '▤'),
    ('series', '특별 경기 전광판', '한국시리즈·국제대회를 1차전부터', '▦'),
    ('starter_trial', '선발 전환 제안', '불펜 성적과 선발 시험 등판', 'K'),
    ('starter_course', '선발 수업 평가', '긴 이닝 준비와 최종 평가', 'K'),
    ('bullpen_move', '불펜 전환 면담', '부진한 선발의 다음 기회', 'K'),
    ('career_market', '재계약과 재도전', '역할·무대·연봉의 선택', '▱'),
]


@never_cache
def rookie_preview(request):
    if not settings.DEBUG:
        raise Http404
    edition = 'full' if request.GET.get('edition') == 'full' else 'lite'
    scenes = [s for s in SCENES if edition == 'lite' or s[0] not in ('homerun', 'strikeout', 'loss')]
    scene = request.GET.get('scene', 'opening')
    if scene not in {s[0] for s in scenes}:
        scene = 'opening'
    uniform_preview = None
    if scene == 'cards':
        club = request.GET.get('club', 'kia')
        if club not in W.PRO_TEAM:
            club = 'kia'
        name = request.GET.get('player_name', '문선빈')[:12] or '문선빈'
        try:
            number = max(0, min(99, int(request.GET.get('number', '17'))))
        except ValueError:
            number = 17
        tier = request.GET.get('tier', 'legend')
        tier = tier if tier in ('legend', 'star', 'pro', 'rookie') else 'legend'
        def card_demo(code, index):
            prefix, _, nick = W.PRO_TEAM[code]['name'].rpartition(' ')
            league = W.SYSTEMS[W.PRO_TEAM[code]['system']][-1]
            league_short = W.short(league)
            position_award = L.AWARD_STYLE.get(league, {}).get('gg', '골든글러브')
            c = SimpleNamespace(pk=9000 + index, name=name, number=number)
            card = dict(palette=K._palette(league, code), jersey=K._jersey_name(name), team_prefix=prefix, team_nick=nick,
                        years='2026–2043', seasons=18, serial=f'{index:04d}', tier=tier,
                        tier_label={'legend': '레전드', 'star': '스타', 'pro': '프로', 'rookie': '루키'}[tier],
                        epithet='안타 제조기', peak_short=league_short,
                        stats=[('경기', '1,820'), ('타율', '.312'), ('안타', '2,114'), ('홈런', '368'), ('타점', '1,286'), ('OPS', '.924')],
                        keys=[('프로 WAR', '76.8'), ('최고 OVR', '88.6'), ('통산 수입', '286억')],
                        honors=[dict(n=n, label=l) for n, l in [(3, 'MVP'), (8, position_award), (6, '타이틀'), (4, '우승'), (2, '대표팀 우승')]],
                        best=dict(year=2034, league=league_short, age=24, line='타율 .338 · 42홈런 · 128타점', war=9.4),
                        clubs=[W.PRO_TEAM[code]['short']], more_clubs=0,
                        headline=dict(title=f'{name}, 18시즌의 커리어를 카드 한 장에 담았어요'))
            return dict(c=c, card=card, team=code, team_name=W.PRO_TEAM[code]['name'], pos_label='외야수', style_label='교타자')
        group = W.SYSTEM_TEAMS[W.PRO_TEAM[club]['system']]
        entries = [card_demo(code, i + 1) for i, (code, _name, _color) in enumerate(group)]
        uniform_preview = next(e for e in entries if e['team'] == club)
        if request.GET.get('shot') in K.SHOTS:
            return render(request, 'community/games/lite_card_shot.html', dict(uniform_preview, kind=request.GET['shot']))
    awake = dict(ok=scene != 'awaken_fail', stars=4, n=1, plus=6,
                 ups=[('구속', 2), ('제구', 1.5), ('멘탈', 2)],
                 fail_text='이번에는 벽을 넘지 못했어요. 충분히 회복한 뒤 다음 기회에 다시 도전해요.')
    moment = dict(won=scene != 'loss', ok=scene != 'loss', path='hr', colors=['#4f46e5', '#a5b4fc'],
                  when='2032', stage='한국시리즈 7차전', head='끝내기 홈런', sit='9회 말 · 2아웃',
                  before=[2, 3], after=[4, 3], line='마지막 타석에서 승부를 뒤집었어요.',
                  result='한국시리즈 우승', play='노렸던 직구를 놓치지 않았어요. 담장을 넘긴 타구가 긴 승부를 끝냈어요.')
    if scene == 'strikeout':
        moment.update(path='so', head='헛스윙 삼진', sit='9회 초 · 2아웃', before=[3, 2], after=[3, 2],
                      line='마지막 아웃, 끝까지 지켜 낸 한 점.', play='바깥쪽 변화구에 배트가 헛돌았어요. 마운드에서 우승을 확정했어요.')
    if scene == 'loss':
        moment.update(path='out', head='마지막 아웃', before=[2, 3], after=[2, 3],
                      line='끝까지 쫓았지만 한 점이 모자랐어요.', result='한국시리즈 준우승',
                      play='타구가 야수 정면으로 향했어요. 이 경험을 안고 다음 시즌을 준비해요.')
    award = dict(kicker='2032 KBO 시즌 시상식', hero='최우수선수', count='커리어 두 번째 MVP',
                 line='한 시즌의 노력이 하나의 이름으로 남았어요.', colors=['#4f46e5', '#a5b4fc'],
                 others=['골든글러브', '홈런왕'])
    months = [dict(label=label, line=line, w=w, l=l, hot=hot) for label, line, w, l, hot in [
        ('4월', '타율 .281 · 4홈런 · 15타점', 14, 10, False),
        ('5월', '타율 .310 · 6홈런 · 22타점', 17, 8, True),
        ('6월', '타율 .297 · 5홈런 · 18타점', 13, 11, False),
        ('7월', '타율 .338 · 8홈런 · 26타점', 16, 7, True),
        ('8월', '타율 .305 · 6홈런 · 21타점', 15, 10, False),
        ('9월', '타율 .321 · 7홈런 · 24타점', 14, 9, True),
    ]]
    ctx = dict(edition=edition, scene=scene, lite_stage=edition == 'lite', mode='create',
               scenes=[dict(key=k, label=l, hint='각성 · 수상' if k == 'chain' and edition == 'full' else h, icon=i)
                       for k, l, h, i in scenes],
               awaken_fx=awake if scene in ('awaken', 'awaken_fail', 'chain') else None,
               moment_fx=moment if scene in ('homerun', 'strikeout', 'loss') or (scene == 'chain' and edition == 'lite') else None,
               award_fx=award if scene in ('award', 'chain') else None,
               season=dict(age=26, duty='주전 외야수', months=months, team_of=10, team_w=89, team_l=55, team_rank=1),
               season_year=2032, season_league='KBO', season_club='나의 구단',
               demo_stats=[('컨택', 76, 79), ('파워', 82, 85), ('선구안', 71, 73)])
    if scene == 'series':
        from .. import rookie_series as Series
        ctx['series_boards'] = Series.demo(request.GET.get('role', 'batter'))
    if uniform_preview:
        ctx.update(uniform_preview=uniform_preview, uniform_gallery=entries if request.GET.get('all') == '1' else [],
                   uniform_teams=[dict(code=code, name=label, color=color) for code, label, color in group],
                   uniform_club=club, uniform_name=name, uniform_number=number, uniform_tier=tier)
        ctx.update(uniform_count=len(group), uniform_group=W.SYSTEM_NAME[W.PRO_TEAM[club]['system']])
    if scene in ('manager', 'interview', 'conduct', 'highlight', 'posting', 'negotiation', 'assignment', 'optout', 'rival', 'world', 'starter_trial', 'starter_course', 'bullpen_move', 'career_market'):
        player = SimpleNamespace(flags={'confidence': 58, 'trust': 54, 'fame': 42, 'discipline': 62, 'intl_rep': 12},
                                 role='batter', position='OF', league='kbo1', ovr=74, pk=9999, name='문선빈', age=26,
                                 year=7, club='kia', potential=80,
                                 stats={k: 74 for k in ('contact', 'power', 'eye', 'speed', 'defense')})
        rng = random.Random(81)
        # 미리보기용 보장 계약 사례. 실제 시장 관심도를 우회하는 게임 경로는 만들지 않는다.
        demo_offers = [Contracts.terms(dict(key=club, team=club, system='mlb', entry_league='mlb',
                       years=years, annual=annual, budget=int(annual * 1.12), interest=.57, role='주전 경쟁'))
                       for club, years, annual in [('nyy', 3, 500000), ('lad', 2, 550000), ('bos', 2, 450000)]]
        if scene == 'world':
            Universe.advance(player, 7, 'kbo1', 144, 72)
            event = None
        elif scene == 'posting':
            event = dict(kind='posting', title='해외 구단 세 곳에서 관심을 보였어요', background='negotiation-room',
                         offers=[dict(o, team_name=W.PRO_TEAM[o['team']]['name']) for o in demo_offers])
        elif scene == 'negotiation':
            offers = demo_offers
            picked = request.GET.get('deal_key') or request.GET.get('choice')
            deal = dict(next((o for o in offers if o['key'] == picked), offers[0]), round=0)
            event = dict(Story.deal_view(player, deal), kind='negotiation')
            actions = tuple(ch['key'] for ch in event['choices'])
            trail = [a for a in request.GET.get('trail', '').split(',') if a in actions][:2]
            if request.GET.get('choice') in actions:
                trail.append(request.GET['choice'])
            for action in trail:
                status, deal = Story.negotiate(player, deal, action, rng)
                ctx['preview_result'] = {'signed': '계약에 성공했어요!', 'counter': '구단이 수정 조건을 제시했어요.', 'failed': '이번 협상이 결렬됐어요.'}[status]
                event = dict(Story.deal_view(player, deal), kind='negotiation')
                if status != 'counter':
                    event['choices'] = []
                    Story.change(player, ctx['preview_result'], confidence=8 if status == 'signed' else -6)
                    break
            ctx['preview_trail'] = ','.join(trail)
        elif scene in ('starter_trial', 'starter_course', 'bullpen_move'):
            player.role, player.position = 'pitcher', 'SP' if scene == 'bullpen_move' else 'RP'
            player.stats = {k: 72 for k in ('velocity', 'control', 'breaking', 'stamina', 'mental')}
            if scene == 'starter_course':
                player.flags['starter_course'] = dict(token=6, stamina=70, day='')
            total = dict(g=12, gs=12, outs=180, er=42, r=42) if scene == 'bullpen_move' else dict(outs=90, er=5, r=5, so=35)
            event = Pitching.offer(player, total, 7)
            selected = request.GET.get('choice')
            if event and selected in {ch['key'] for ch in event['choices']}:
                ctx['preview_result'] = Pitching.resolve(player, event, selected, rng)
                event = dict(event, choices=[])
        elif scene == 'career_market':
            event = Balance.market_event(player, .35)
            selected = request.GET.get('choice')
            if selected == 'rebuild':
                ctx['preview_result'] = Balance.market_reply(player, event, selected, rng)
                event = dict(event, choices=[])
        elif scene in ('assignment', 'optout'):
            player.league, player.club = 'mlb', 'nyy'
            player.flags['contract'] = Contracts.signed(dict(system='mlb', team='nyy', years=3, annual=600000,
                role='주전 경쟁', minor_veto=request.GET.get('veto') != '0', split=request.GET.get('split') == '1',
                player_opt_out=True), 1)
            player.flags['contract']['elapsed'] = 1
            event = Contracts.assignment_view(player) if scene == 'assignment' else Contracts.optout_view(player)
            choice = request.GET.get('choice')
            if choice in {ch['key'] for ch in event['choices']}:
                ctx['preview_result'] = (Contracts.assignment_reply(player, choice, rng, 2) if scene == 'assignment'
                                         else Contracts.optout_reply(player, choice))
                event = dict(event, choices=[])
        else:
            event = Story.encounter(player, scene, rng)
            if request.GET.get('choice') in {ch['key'] for ch in event['choices']}:
                ctx['preview_result'] = Story.resolve(player, event, request.GET['choice'], rng)
        ctx.update(story_scene=event, mind=Story.view(player), scene_preview=True)
    response = render(request, 'community/rookie_preview.html', ctx)
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
