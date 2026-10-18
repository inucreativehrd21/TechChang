"""야구선수 키우기 코칭스태프 이름 — 학교·대학·프로(나라별)·구단마다 다른 사람(2026-10-18 사용자 요청).

그림(연구실 픽셀 인물)은 역할마다 같고, 이름과 직함만 무대에 따라 바뀐다. 이름은 (무대, 소속, 역할)로 정해져서
같은 팀에 있으면 늘 같은 사람이 나온다. 팀 밖 사람(스카우트·기자·에이전트·해설위원)은 커리어 내내 같은 연구실 사람이다.
실존 인물과 겹치지 않게 흔한 성·이름 조각을 섞고, 이름난 야구인 이름은 걸러 낸다.
"""
from __future__ import annotations

import random

from . import rookie_world as W

# 팀 밖 사람 — 테크창 연구실 사람들(그림은 media/lab/chars/<키>_idle.png)
OUTSIDE = {'data': ('수정', '스카우트'), 'editor': ('승현', '야구 기자'), 'charter': ('재원', '에이전트'),
           'critic': ('예원', '해설위원')}
TEAM_ROLES = ('lead', 'coding', 'hrd', 'checker')

KO_SUR = '김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허유남심노하곽성차주우구민나진지엄채원천방공현함변염여추도석선설마길연위표명기반왕금옥육인맹제탁국'
KO_GIVEN = '병상종동영기광태용진수철경형덕만재봉석창환식규길범국한승명운정춘달성주호학원희근일도'
ABROAD = {
    'mlb': (('마이크', '데이브', '스티브', '짐', '톰', '빌', '론', '게리', '테리', '레이', '척', '돈', '프랭크', '버디', '행크'),
            ('하퍼', '콜린스', '맥과이어', '스튜어트', '로건', '파커', '헤이스', '그레이엄', '레이놀즈', '포스터', '웰스', '플레처',
             '베넷', '오코너', '설리번'), ' '),
    'npb': (('오카다', '모리', '기무라', '하야시', '시미즈', '야마자키', '이케다', '하시모토', '이시카와', '마에다', '후지타', '오가와',
             '곤도', '이노우에', '사카이'),
            ('히로시', '마사오', '데쓰야', '가즈오', '노부유키', '요시아키', '다카시', '오사무', '마코토', '아키라', '시게루', '도시오'), ' '),
    'cpbl': (('천', '린', '황', '장', '왕', '리', '우', '차이', '류', '셰', '쩡', '궈'),
             ('즈창', '원슝', '밍더', '궈량', '자하오', '스창', '젠훙', '야오쭝', '정밍', '진룽'), ''),
}
FAMOUS = {'류현진', '이종범', '이승엽', '선동열', '김성근', '류중일', '이대호', '박찬호', '추신수', '양현종', '김광현', '강정호',
          '이정후', '김하성', '오승환', '최정', '박병호', '김현수', '김태균', '김인식', '김응용', '김경문', '이강철', '김태형',
          '염경엽', '이숭용', '이범호', '박진만', '김원형', '홍원기', '이호준', '장종훈', '한대화', '정민철', '송진우', '구대성'}

# 직함 — 코치는 선수가 투수면 투수 코치, 타자면 타격 코치
TITLE = {
    'little': {'lead': '리틀야구단 감독', 'coding': '{} 코치', 'hrd': '체력 코치', 'checker': '트레이너'},
    'ms': {'lead': '야구부 감독', 'coding': '{} 코치', 'hrd': '체력 코치', 'checker': '트레이너'},
    'hs': {'lead': '야구부 감독', 'coding': '{} 코치', 'hrd': '체력 코치', 'checker': '트레이너'},
    'univ': {'lead': '야구부 감독', 'coding': '{} 코치', 'hrd': '컨디셔닝 코치', 'checker': '트레이너'},
    'pro': {'lead': '감독', 'coding': '{} 코치', 'hrd': '컨디셔닝 코치', 'checker': '트레이너'},
}
SANGMU = '국군체육부대(상무)'


def _stage(league: str) -> str:
    """이름 묶음 — 아마추어는 학교급, 프로는 나라(mlb·npb·cpbl 은 그 나라 이름)."""
    return league if not W.is_pro(league) else W.system_of(league)


def _korean(rng) -> str:
    return rng.choice(KO_SUR) + rng.choice(KO_GIVEN) + rng.choice(KO_GIVEN)


def person(stage: str, club: str, who: str) -> str:
    """(무대, 소속, 역할) → 늘 같은 이름. 무대가 mlb·npb·cpbl 이면 그 나라 이름."""
    rng = random.Random(f'{stage}|{club}|{who}')
    for _ in range(30):
        if stage in ABROAD:
            a, b, sep = ABROAD[stage]
            name = f'{rng.choice(a)}{sep}{rng.choice(b)}'
        else:
            name = _korean(rng)
        if name not in FAMOUS:
            return name
    return name


def staff(league: str, club: str, who: str, role: str = 'batter') -> tuple[str, str]:
    """(이름, 직함). league·club 은 선수가 지금 뛰는 곳, role 은 선수 투타."""
    if who in OUTSIDE:
        return OUTSIDE[who]
    stage = _stage(league)
    title = TITLE.get(league if not W.is_pro(league) else 'pro', TITLE['pro']).get(who, '코치')
    if club == SANGMU:
        title = '상무 ' + title
    return person(stage, club, who), title.format('투수' if role == 'pitcher' else '타격')


def national(year: int) -> tuple[str, str]:
    """국가대표 감독 — 4년마다 바뀐다(year 는 달력 연도)."""
    return person('national', str(year // 4), 'lead'), '국가대표 감독'
