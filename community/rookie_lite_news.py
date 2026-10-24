"""저장된 시즌 기록으로 만드는 기사·가상 팬 반응. 경기 난수와 능력치는 건드리지 않는다."""
import random

from . import rookie_league as L
from . import rookie_world as W


def _rng(c, s):
    return random.Random(f'lite-news:{c.pk}:{s.year}:{s.league}:{c.role}')


def season_features(c, s, rows):
    rng = _rng(c, s)
    nm, team = c.name, W.club_short(s.league, s.club)
    t = s.totals or {}
    def article(tag, title, sub):
        return dict(tag=f'[{tag}]', title=title, sub=sub)

    if c.role == 'pitcher' and t.get('outs'):
        p = L.pitching(t)
        detail = f"{t.get('so', 0)}탈삼진 · {t.get('bb', 0)}볼넷 · 평균자책점 {p['era']:.2f}"
        analysis = rng.choice([f'{nm}의 시즌을 가른 승부, 삼진과 볼넷 사이',
                               f'승패 너머의 {nm}…투구 내용을 다시 읽다',
                               f'{nm}의 마운드 성적표, 결과와 과정은 같았을까'])
    elif c.role == 'batter' and t.get('pa'):
        b = L.batting(t)
        detail = f"타율 {L.rate(b['avg'])} · OPS {b['ops']:.3f} · {t.get('hr', 0)}홈런 · {t.get('sb', 0)}도루"
        analysis = rng.choice([f'{nm}, 안타 숫자 뒤에 숨은 타석의 가치',
                               f'장타와 출루로 읽는 {nm}의 한 시즌',
                               f'{nm}의 타격 성적표…타율만으로 설명할 수 있을까'])
    else:
        detail = f'이번 시즌 역할: {s.duty}'
        analysis = f'{nm}, 출전 기회와 역할로 돌아본 한 시즌'
    out = [article('기록 분석', analysis, detail)]

    if len(rows) > 1:
        route = ' → '.join(W.short(r['league']) for r in rows)
        field = article('현장', f'유니폼 속 역할이 달라졌다…{nm}의 이동 경로', route)
    elif s.age >= 34:
        field = article('베테랑', rng.choice([f'{nm}, 다음 시즌에도 유니폼을 입을 수 있을까',
                                            f'경험과 경쟁 사이…{nm}의 겨울 과제']),
                        f'{s.age}세 시즌을 마쳤어요. 다음 역할과 계약은 앞으로의 선택에 달렸어요.')
    elif not W.is_pro(s.league):
        field = article('유망주', rng.choice([f'{team} {nm}, 성적 너머 성장 과제는',
                                            f'다음 무대를 꿈꾸는 {nm}, 올해 남긴 발자취']),
                        f'{s.age}세 · {s.duty}. 다음 시즌에는 어떤 모습을 보여 줄까요?')
    else:
        field = article('현장', rng.choice([f'{team} {nm}, 숫자로 남은 역할과 겨울의 숙제',
                                          f'스포트라이트 밖의 {nm}…한 시즌을 돌아보다',
                                          f'{nm}의 다음 페이지, {team}에서 무엇을 보여 줄까']),
                        f'올해 맡은 역할은 {s.duty}였어요. 다음 기회는 아직 정해지지 않았어요.')
    out.append(field)
    if s.team_of:
        out.append(article('팀 결산', f'{team}, {s.team_of}팀 중 {s.team_rank}위…개인 성적과 함께 본 팀의 한 해',
                           f'정규시즌 {s.team_w}승 {s.team_l}패. 개인의 활약과 팀 순위를 함께 돌아봐요.'))
    else:
        labels = [a['label'] for a in s.awards if a['kind'] in ('ring', 'national')]
        out.append(article('대회 결산', f'{team} {nm}, 대회에서 남긴 한 시즌의 기록',
                           ' · '.join(labels) if labels else '이번 시즌 대회를 마쳤어요. 다음 도전은 새로운 시즌에 이어져요.'))
    return out


def season_reactions(c, s):
    """별도 상황별 반응 은행을 쓰며 경기 난수는 소비하지 않아요."""
    from .rookie_fan_reactions import season
    return season(c, s)
