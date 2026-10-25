"""정식 모드 표시용 날짜·이미지·순위·시상 정보. 경기 계산과 저장값은 바꾸지 않아요."""
from datetime import datetime, time, timedelta
from django.utils import timezone
from . import rookie_clock as Clock, rookie_league as L

SKIES = ((time(11), 'morning', '오전 경기'), (time(13), 'noon', '한낮 경기'),
         (time(15, 30), 'afternoon', '오후 경기'), (time(18), 'dusk', '노을 경기'),
         (time(20), 'night', '야간 경기'), (time(22), 'main', '메인 경기'),
         (time(23), 'dawn', '다음 경기를 준비하는 구장'))


def sky_key(now):
    local = timezone.localtime(now)
    return next((key for at, key, _label in reversed(SKIES) if local.time() >= at), 'dawn')


def calendar(now):
    day = timezone.localdate(now)
    if not Clock.split_on(day):
        return None
    season = L.season_no(day)
    start, end = L.season_bounds(season)
    n = min(L.CYCLE, max(1, (day - start).days + 1))
    phase = 'post' if n > L.SEASON_DAYS else 'stretch' if n >= 22 else 'second' if n > Clock.HALF_DAYS else 'first'
    stop = Clock.HALF_DAYS if n <= Clock.HALF_DAYS else L.SEASON_DAYS if n <= L.SEASON_DAYS else L.CYCLE
    remaining = max(0, stop - n)
    label = {'first': '전기리그', 'second': '후기리그', 'stretch': '막판 주간', 'post': '가을야구'}[phase]
    nodes = ((1, '개막 · 전기리그'), (14, '전기 종료 · 올스타'), (15, '후기리그'),
             (22, '막판 주간'), (29, '가을야구'), (31, '다음 시즌 개막'))
    current = max(at for at, _ in nodes if at <= n)
    return dict(season=season, day=n, phase=phase, label=label, remaining=remaining,
                half_day=n if n <= 14 else min(14, n - 14), half_pct=min(100, (n if n <= 14 else n-14) / 14 * 100),
                next_open=L.season_bounds(season+1)[0],
                nodes=[dict(day=at, label=text, current=at == current, done=at < current,
                            date=start+timedelta(days=at-1)) for at, text in nodes])


def sky(now, cal):
    today = timezone.localdate(now)
    timeline = []
    for offset in (0, 1):
        for at, key, label in SKIES:
            stamp = timezone.make_aware(datetime.combine(today+timedelta(days=offset), at))
            if stamp > now:
                timeline.append(dict(at=int(stamp.timestamp()*1000), key=key, label=label, lit=key in ('dusk', 'night', 'main')))
    key = sky_key(now)
    ornament = None
    if cal:
        ornament = 'opening' if cal['day'] == 1 else 'postseason' if cal['phase'] == 'post' else 'stretch' if cal['phase'] == 'stretch' else None
    return dict(key=key, time=timezone.localtime(now).strftime('%H:%M'), label=next((label for _at, k, label in SKIES if k == key), ''),
                lit=key in ('dusk', 'night', 'main'), ornament=ornament, timeline=timeline)


def post(post, now):
    if not post:
        return None
    result = dict(post)
    rnd = post['doc']['rounds'][0]
    day = timezone.localdate(now)
    start, end = L.season_bounds(post['season'])
    nxt = post['next']
    result.update(live=not post['done'], featured=end < day < L.season_bounds(post['season']+1)[0],
                  wins=rnd['wins'], need=rnd['need'], team=post['doc']['team'], opponent=rnd['opponent'],
                  headline=f"{post['shown']}차전 종료" if post['shown'] else '첫 경기를 기다려요',
                  next_label=('오늘 ' if timezone.localdate(nxt['at']) == day else f"{timezone.localtime(nxt['at']).day}일 ") + timezone.localtime(nxt['at']).strftime('%H:%M') if nxt else '',
                  won=rnd['result'] == 'won')
    return result


def race_views(halves, whole):
    """엔진에서 만든 표를 복사해 표시용 게임차·남은 경기만 붙여요."""
    if not halves:
        return []
    views = []
    for key, label, table, games in [('first', '전기', halves['first'], halves['per']),
                                     ('second', '후기', halves['second'], halves['per']),
                                     ('whole', '시즌', whole, whole['games'] if whole else 0)]:
        if not table or not table['rows']:
            continue
        rows = [dict(r) for r in table['rows']]
        top = rows[0]
        for row in rows:
            gb = ((top['w']-row['w'])+(row['l']-top['l']))/2
            row.update(gb='—' if gb <= 0 else f'{gb:g}', left=max(0, games-row['g']),
                       first_champ=bool(halves['first_champ'] and row['club'] == halves['first_champ']['club']))
        views.append(dict(key=key, label=label, rows=rows, games=games))
    return views


def half_awards(awards):
    return [dict(half=n, label=Clock.HALF_LABEL[n], award=next((a for a in awards if a.order == 60+n), None),
                 motto='개막부터 쌓은 14일' if n == 1 else '마지막까지 달린 14일') for n in (1, 2)]


def award_fx(fx, awards):
    """반기 MVP를 시즌 주요상 다음, 부문 타이틀 앞에 표시해요. 수상/기록/확인 처리는 기존 함수 그대로예요."""
    priority = {'mvp': 0, 'ace': 1, 'rookie': 2, 'half': 3, 'gg': 4, 'title': 5, 'minor': 6}
    awards = list(awards)
    hero = min(awards, key=lambda a: priority.get(a.kind, 9), default=None)
    if not hero or hero.kind != 'half':
        return fx
    from . import rookie_world as W
    out = dict(fx, hero=hero.label, kind='half', half=True, count='14일의 주인공', line=hero.value,
               kicker=f"시즌 {hero.season.number} · {W.league(hero.league)['name']}",
               others=[a.label if a.league == hero.league else f'{W.short(a.league)} {a.label}' for a in awards if a.pk != hero.pk])
    return out
