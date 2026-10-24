"""공개된 실제 회원 기록의 동나이·투타 유형 비교. 가상 이름을 실제 회원으로 표시하지 않아요."""
from django.db.models import F, IntegerField
from django.db.models.functions import Abs, Cast
from django.urls import reverse

from . import rookie_league as L
from . import rookie_world as W
from .game_visibility import rookie_visible


def _values(role, totals):
    v = L.line_view(role, totals or {})
    if role == 'pitcher':
        return [('이닝', v['ip_text']), ('ERA', v['era_text']), ('탈삼진', str(v.get('so', 0)))]
    return [('타율', v['avg_text']), ('OPS', v['ops_text']), ('홈런', str(v.get('hr', 0)))]


def comparisons(p, limit=3):
    from .models import LiteCareer, LiteSeason, RookiePlayer, RookieSeasonStat
    if not isinstance(p, (LiteCareer, RookiePlayer)):
        return []
    lite = isinstance(p, LiteCareer)
    if not p.pk:
        return []
    own = (p.seasons.only('age', 'ovr_end', 'league', 'totals', 'war').order_by('-year').first() if lite
           else p.season_stats.only('age', 'best_ovr', 'league', 'totals', 'war').order_by('-season__number', '-pk').first())
    age, ovr = (own.age, own.ovr_end if lite else own.best_ovr) if own else (p.age, p.ovr)
    league = own.league if own else p.league
    totals = own.totals if own else {}
    # MySQL의 나이는 UNSIGNED라 어린 선수와 뺄셈하기 전에 SIGNED로 바꿔야 해요.
    age_gap = Abs(Cast('age', IntegerField()) - age)
    if lite:
        qs = rookie_visible(LiteSeason.objects.filter(career__mode=p.mode, career__role=p.role,
                             career__user__isnull=False, career__user__is_active=True, games__gt=0,
                             age__gte=max(0, age - 2), age__lte=age + 2).exclude(career=p), 'career__user')
        if p.user_id:
            qs = qs.exclude(career__user_id=p.user_id)
        qs = qs.annotate(age_gap=age_gap, skill_gap=Abs(F('ovr_end') - ovr)).select_related('career').only(
            'age', 'ovr_end', 'league', 'totals', 'war', 'year', 'club', 'career__name', 'career__user_id')
    else:
        qs = rookie_visible(RookieSeasonStat.objects.filter(role=p.role, player__isnull=False, user__is_active=True,
                             age__gte=max(0, age - 2), age__lte=age + 2).exclude(user_id=p.user_id), 'user')
        qs = qs.annotate(age_gap=age_gap, skill_gap=Abs(F('best_ovr') - ovr)).select_related('player', 'season').only(
            'age', 'best_ovr', 'league', 'totals', 'war', 'name', 'team', 'season__number', 'player__user_id')
    candidates = list(qs.order_by('age_gap', 'skill_gap', '-pk')[:120])
    candidates.sort(key=lambda row: (abs(row.age - age), row.league != league,
                                     abs((row.ovr_end if lite else row.best_ovr) - ovr), -row.pk))
    out, seen = [], set()
    for row in candidates:
        peer = row.career if lite else row.player
        if peer.user_id in seen or not (row.totals or {}).get('g'):
            continue
        seen.add(peer.user_id)
        route = ('extreme_career' if p.mode == 'extreme' else 'lite_career') if lite else 'rookie_player'
        mine, theirs = _values(p.role, totals), _values(p.role, row.totals)
        out.append(dict(id=f'{"lite" if lite else "daily"}:{row.pk}', player_id=peer.pk,
                        name=peer.name if lite else row.name, age=row.age, own_age=age, same_age=row.age == age,
                        league=row.league, league_label=W.short(row.league), club=row.club if lite else row.team,
                        club_label=W.club_label(row.league, row.club if lite else row.team),
                        ovr=row.ovr_end if lite else row.best_ovr, war=row.war, own_war=own.war if own else 0,
                        line=L.pit_summary(row.totals) if p.role == 'pitcher' else L.bat_summary(row.totals),
                        role=p.role, url=reverse('community:' + route, args=[peer.pk]), source='회원 커리어',
                        season=row.year if lite else row.season.number,
                        metrics=[dict(label=a[0], mine=a[1] if own else '—', peer=b[1]) for a, b in zip(mine, theirs)]))
        if len(out) >= limit:
            break
    return out
