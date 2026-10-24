"""구단 일일 리포트: 저장된 경기 기록만 분석하며 경기·AI API를 실행하지 않아요."""
from datetime import timedelta

from django.utils import timezone

from . import rookie_league as L
from . import rookie_world as W
from . import rookie_matchups as Matchups


def _total(games):
    total = {}
    for game in games:
        total = L.add(total, game.line or {})
    return total


def daily(player, day=None):
    day = day or timezone.localdate() - timedelta(days=1)
    yesterday = timezone.localdate() - timedelta(days=1)
    if day > yesterday:
        day = yesterday
    games = list(player.games.filter(day=day).order_by('no'))
    recent = list(player.games.filter(day__gte=day - timedelta(days=6), day__lte=day).order_by('day', 'no'))
    t, week = _total(games), _total(recent)
    report = dict(day=day, player=player, games=len(games), totals=t, metrics=[], strengths=[], tasks=[],
                  team=W.club_label(games[0].league, games[0].line.get('club', player.club)) if games else W.club_label(player.league, player.club),
                  previous=day - timedelta(days=1) if day > L.EPOCH else None,
                  next=day + timedelta(days=1) if day < yesterday else None,
                  weekly_games=len(recent), evidence='저장된 경기 박스스코어 · 최근 7일 기록',
                  result_rows=[L.game_view(game, player.club, player.role) for game in games],
                  member_history=Matchups.history(player, games))
    if not games:
        report.update(summary=f'{player.name} 선수는 이날 공식 경기 출장 기록이 없어요.',
                      strengths=['당일 경기 표본이 없어 경기력 평가는 보류해요.'],
                      tasks=['출전·휴식 여부는 일정과 엔트리를 함께 확인해야 해요. 저장된 기록만으로 결장 원인을 단정하지 않아요.'])
        return report
    if player.role == 'batter':
        b, w = L.batting(t), L.batting(week)
        report['summary'] = (f"{player.name} 선수는 {len(games)}경기 {t.get('pa', 0)}타석에 나서 "
                             f"{t.get('ab', 0)}타수 {t.get('h', 0)}안타, {t.get('hr', 0)}홈런, "
                             f"{t.get('rbi', 0)}타점, {t.get('bb', 0)}볼넷을 기록했어요.")
        report['metrics'] = [('타율', L.rate(b['avg']) if t.get('ab') else '—'),
                             ('출루율', L.rate(b['obp']) if t.get('pa') else '—'),
                             ('OPS', L.rate(b['ops']) if t.get('pa') else '—'), ('삼진', str(t.get('so', 0)))]
        if t.get('h', 0):
            report['strengths'].append(f"안타 {t['h']}개로 출루 기회를 만들었어요. 당일 타율은 {L.rate(b['avg'])}이에요.")
        if t.get('hr', 0) or t.get('d', 0) or t.get('t', 0):
            report['strengths'].append(f"장타 {t.get('d', 0) + t.get('t', 0) + t.get('hr', 0)}개를 생산했어요. 장타율은 {L.rate(b['slg'])}이에요.")
        if t.get('bb', 0):
            report['strengths'].append(f"볼넷 {t['bb']}개를 얻어 타격 이외의 출루 경로도 확보했어요.")
        if t.get('pa', 0) and b['k_pct'] >= .25:
            report['tasks'].append(f"삼진 비율이 {b['k_pct']:.0%}로 높았어요. 다음 출전에서는 타석 접근과 컨택 유지가 우선 과제예요.")
        if t.get('pa', 0) and b['obp'] < .300:
            report['tasks'].append(f"당일 출루율이 {L.rate(b['obp'])}에 그쳤어요. 불리한 카운트를 줄이고 출루 기회를 늘릴 필요가 있어요.")
        report['trend'] = f"최근 7일 {len(recent)}경기에서 타율 {L.rate(w['avg'])}, OPS {L.rate(w['ops'])}, {week.get('hr', 0)}홈런을 기록했어요."
    else:
        p, w = L.pitching(t), L.pitching(week)
        report['summary'] = (f"{player.name} 선수는 {len(games)}경기에 등판해 {p['ip_text']}이닝 "
                             f"{t.get('h', 0)}피안타, {t.get('er', 0)}자책점, "
                             f"{t.get('bb', 0)}볼넷, {t.get('so', 0)}탈삼진을 기록했어요.")
        report['metrics'] = [('이닝', p['ip_text']), ('평균자책점', f"{p['era']:.2f}" if t.get('outs') else '—'),
                             ('WHIP', f"{p['whip']:.2f}" if t.get('outs') else '—'), ('투구수', str(t.get('np', 0)))]
        if t.get('so', 0):
            report['strengths'].append(f"탈삼진 {t['so']}개로 타자의 인플레이 타구를 줄였어요.")
        if not t.get('bb', 0) and t.get('bf', 0):
            report['strengths'].append('볼넷 없이 승부해 불필요한 주자 누적을 억제했어요.')
        if not t.get('er', 0) and t.get('outs', 0):
            report['strengths'].append('자책점 없이 등판을 마쳤어요.')
        if t.get('bb', 0):
            report['tasks'].append(f"볼넷 {t['bb']}개를 허용했어요. 최근 7일 9이닝당 볼넷은 {w['bb9']:.2f}개로, 제구 안정성을 계속 점검해야 해요.")
        if t.get('hr', 0):
            report['tasks'].append(f"피홈런 {t['hr']}개로 실점 부담이 커졌어요. 장타 억제와 실투 관리가 다음 과제예요.")
        report['trend'] = f"최근 7일 {w['ip_text']}이닝, 평균자책점 {w['era']:.2f}, WHIP {w['whip']:.2f}의 기록을 남겼어요."
    # 실제 저장된 상대 등급별 타수로만 강·약점을 비교해요. 구종·코스는 추측하지 않아요.
    samples = [row for row in L.splits(player.role, week) if row.get('ab', 0) >= 5]
    if len(samples) >= 2:
        samples.sort(key=lambda row: row['h'] / row['ab'], reverse=player.role == 'batter')
        good, bad = samples[0], samples[-1]
        label = '타율' if player.role == 'batter' else '피안타율'
        report['strengths'].append(f"최근 7일 {good['label']} 상대 {good['ab']}타수 {good['h']}안타, {label} {good['avg_text']}, 상대적으로 좋은 결과를 냈어요.")
        report['tasks'].append(f"{bad['label']} 상대는 {bad['ab']}타수 {bad['h']}안타, {label} {bad['avg_text']}예요. 다음 관찰에서 이 구간을 우선 확인해요.")
    report['strengths'] = report['strengths'][:3] or ['당일 기록에서 뚜렷한 강점을 단정할 표본은 부족해요. 다음 출전과 함께 관찰해요.']
    report['tasks'] = report['tasks'][:3] or ['당일 기록의 흐름을 유지하되, 단일 경기 결과를 장기 기량으로 단정하지 않아요.']
    report['sample_note'] = '상대 등급별 평가는 최근 7일 각 5타수 이상인 표본만 비교해요. 구종·코스별 자료는 저장하지 않아 분석에 포함하지 않아요.'
    return report
