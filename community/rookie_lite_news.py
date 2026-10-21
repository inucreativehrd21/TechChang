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
    """실제 시즌 내용에 맞춘 가상 커뮤니티. 화면을 다시 열어도 같은 반응을 보여 준다."""
    rng = _rng(c, s)
    team, t = W.club_short(s.league, s.club), s.totals or {}
    if s.champion:
        fan = rng.choice([f'{team} 우승이라니! 이번 시즌 끝까지 본 보람이 있어요.',
                          f'{c.name} 선수도 우승 멤버네요. 오늘은 이 이야기만 할래요.'])
    elif s.team_of and s.team_rank == s.team_of:
        fan = f'{team} 팬이라 아쉬워요. 개인 기록과 별개로 팀이 함께 올라왔으면 해요.'
    else:
        fan = rng.choice([f'{c.name} 선수의 다음 시즌도 지켜볼게요. 어떤 역할을 맡게 될까요?',
                          f'{team}에서 보낸 한 시즌, 잘한 날도 힘든 날도 기억에 남아요.'])
    if c.role == 'pitcher' and t.get('outs'):
        record = f"{t.get('so', 0)}탈삼진에 {t.get('bb', 0)}볼넷이네요. 승수 말고 투구 내용도 같이 봐야 해요."
    elif c.role == 'batter' and t.get('pa'):
        record = f"OPS {L.batting(t)['ops']:.3f}네요. 타율뿐 아니라 출루와 장타도 같이 보고 싶어요."
    else:
        record = '출전 기회가 적었네요. 기록만으로 단정하기보다 맡은 역할부터 봐야겠어요.'
    if len(s.splits or []) > 1:
        outlook = '시즌 중에 역할이 달라졌네요. 전반기와 후반기를 나눠 봐야겠어요.'
    elif s.age >= 34:
        outlook = '이제는 어떤 자리에서 오래 뛸 수 있을지가 궁금해요. 다음 선택을 응원해요.'
    elif not W.is_pro(s.league):
        outlook = '아직 배우는 선수잖아요. 다음 대회에서 얼마나 성장했는지 보고 싶어요.'
    else:
        outlook = rng.choice(['겨울 준비가 궁금하네요. 다음 시즌에는 어떤 모습을 보여 줄까요?',
                              '좋은 날만 있는 건 아니죠. 다음 시즌에는 꾸준히 기회를 잡았으면 해요.'])
    # 10개 표시 슬롯마다 해요체 3 : 커뮤니티 말투 7. 게임 진행 난수와는 별개다.
    if s.champion:
        fan_memes = [f'{team} 우승ㅋㅋㅋ 오늘부터 이 시즌 무한복습 간다',
                     f'{c.name} 우승반지 실화냐 이 맛에 야구 본다',
                     f'{team} 팬들 지금 잠이 오겠냐고ㅋㅋ', '야구 끊는다던 사람들 전원 복귀한 날']
    elif s.team_of and s.team_rank == s.team_of:
        fan_memes = ['내일부터 야구 안 봄. 근데 개막전 언제냐',
                     f'{team} 순위표는 접어두고 개인 기록부터 보자…',
                     '올해도 내가 야구에 진심이었던 걸로ㅋㅋ', '순위표 봤다가 조용히 창 닫음']
    else:
        fan_memes = [f'{team} 야구를 또 끝까지 봤네 내년에도 속아준다ㅋㅋ',
                     f'{c.name} 다음 시즌 떡상각이냐 설레발 금지냐',
                     '시즌 끝나니까 심심하네 볼 때는 그렇게 화났는데ㅋㅋ',
                     '내년 야구 안 본다 특: 벌써 새 시즌 라인업 짜는 중']
    if c.role == 'pitcher' and t.get('outs'):
        era = L.pitching(t)['era']
        if era <= 3:
            record_memes = [f"ERA {era:.2f}에 {t.get('so', 0)}K면 일단 박수부터 쳐야지ㅋㅋ",
                            f"{t.get('so', 0)}탈삼진 뭐냐 타자들 배트에 선풍기 달았네"]
        elif era >= 5:
            record_memes = [f'ERA {era:.2f}…다음 시즌에는 진짜 제발',
                            f"{t.get('so', 0)}K는 좋은데 ERA {era:.2f} 보고 다시 앉음"]
        else:
            record_memes = [f"{t.get('so', 0)}K {t.get('bb', 0)}볼넷. 승수만 보고 싸우지 말자ㅋㅋ",
                            f'ERA {era:.2f}면 못 쓸 정도는 아닌데 기대한 맛이 또 있잖아']
    elif c.role == 'batter' and t.get('pa'):
        ops = L.batting(t)['ops']
        if ops >= .850:
            record_memes = [f'OPS {ops:.3f}인데 더 치라고 하는 팬들 양심 어디ㅋㅋ',
                            f'OPS {ops:.3f}면 타석 들어올 때 휴대폰 내려놔야지']
        elif ops < .650:
            record_memes = [f'OPS {ops:.3f}…눈 감았다 뜨면 올라가 있겠지?',
                            f'OPS {ops:.3f} 보고 겨울 훈련 영상 기다리는 중. 이번엔 안 속는다']
        else:
            record_memes = [f'OPS {ops:.3f}. 애매해서 더 미련 남는 그 성적ㅋㅋ',
                            f'OPS {ops:.3f}면 라인업에서 빼자니 아쉽고 믿자니 고민됨']
    else:
        record_memes = ['기록 보고 판단하라는데 일단 좀 나와야 기록이 생기지ㅋㅋ',
                        '벤치 화면에서만 보다가 시즌 끝났네 다음엔 경기장에서 보자']
    if len(s.splits or []) > 1:
        outlook_memes = ['전반기랑 후반기 역할 다른데 합계로만 싸우면 어떡하냐ㅋㅋ',
                         '시즌 중 이사까지 했네 다음엔 자리부터 잡아보자']
    elif s.age >= 34:
        outlook_memes = ['나이는 내가 대신 먹을 테니까 한 시즌만 더 해보자',
                         '낭만으로 재계약하자는 마음이랑 기록표 보는 눈이랑 싸우는 중']
    elif not W.is_pro(s.league):
        outlook_memes = ['일단 이름 메모함. 나중에 잘되면 내가 먼저 봤다고 해야지ㅋㅋ',
                         '벌써 완성형 취급하지 말자 아직 교복 입는다']
    else:
        outlook_memes = ['겨울 훈련 기사 뜨면 또 기대할 예정ㅋㅋ 사람 안 변함',
                         '내년 예상 라인업에 일단 넣어봄. 반박은 성적으로 받는다',
                         '이쯤 되면 선수가 내년을 준비하는 건지 내가 준비하는 건지ㅋㅋ']
    polite = [dict(name='직관하는 팬', text=fan), dict(name='기록 보는 팬', text=record),
              dict(name='다음 시즌도', text=outlook)]
    pools = [fan_memes, record_memes, outlook_memes]
    pattern = ('standard', 'community', 'community', 'standard', 'community',
               'community', 'standard', 'community', 'community', 'community')
    comments = []
    for i in range(3):
        style = pattern[((s.year - 1) * 3 + i) % 10]
        item = polite[i] if style == 'standard' else dict(
            name=rng.choice(['ㅇㅇ', '야구보는중', '내일도직관', '라인업고민중', '기록표켜라']), text=rng.choice(pools[i]))
        comments.append(dict(item, style=style))
    return comments
