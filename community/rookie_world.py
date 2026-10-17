"""야구선수 키우기 — 세계: 리그·구단·학교 데이터와 진로 사다리(2026-10-17 '선수 일생' 개편).

선수는 리틀야구(초6, 12세)에서 시작해 중학교(13~15)·고등학교(16~18) 야구부를 거쳐 드래프트를 맞는다.
지명되면 KBO 에 입단하거나, 거절하고 대학(19~22, 졸업 때 다시 드래프트)이나 해외로 갈 수 있다.
해외: 미국(싱글A → 더블A → 트리플A → 메이저리그), 일본(NPB 2군 → 1군), 대만(CPBL 1군).

리그 수준(level)은 경기 모형에서 '상대의 평균 능력'이다(rookie_sim). 능력치 척도는 25(신인 바닥)~99.
학교 이름은 공개 자료에서 모았다(2026-10-17): 고교·대학 = 나무위키 '고교야구'·'한국대학야구/구단' 문서의
지역별 목록(클럽 팀 BC·SC 등은 뺐다), 중학교 = 대한야구소프트볼협회 15세 이하부 등록 팀 목록 일부 + 대회 기사.
중학교 목록은 일부만 확인됐다 — 운영자가 MIDDLE_SCHOOLS 에 덧붙이면 된다(협회 사이트는 robots.txt 로 자동 수집을
막고 있어 스크립트로 긁지 않았다). 구단·학교 이름은 소속 표시용이며 실제 학교·구단과 관계없다.
"""
from __future__ import annotations

REGIONS = ('서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남',
           '전북', '전남', '경북', '경남', '제주')

# ───────────────────────────── 리그
# system: 같은 사다리(승격·강등이 오가는 묶음). step: 사다리 안 순서(0 이 아래). kind: amateur / pro
LEAGUES = {
    'little':  {'name': '리틀야구', 'short': '리틀', 'country': 'KR', 'system': 'amateur', 'step': 0, 'level': 24.0},
    'ms':      {'name': '중학야구', 'short': '중학', 'country': 'KR', 'system': 'amateur', 'step': 1, 'level': 30.0},
    'hs':      {'name': '고교야구', 'short': '고교', 'country': 'KR', 'system': 'amateur', 'step': 2, 'level': 38.0},
    'univ':    {'name': '대학야구', 'short': '대학', 'country': 'KR', 'system': 'amateur', 'step': 3, 'level': 45.0},
    'kbo3':    {'name': 'KBO 육성군', 'short': '육성군', 'country': 'KR', 'system': 'kbo', 'step': 0, 'level': 42.0},
    'kbo2':    {'name': 'KBO 퓨처스리그', 'short': '퓨처스', 'country': 'KR', 'system': 'kbo', 'step': 1, 'level': 50.0},
    'kbo1':    {'name': 'KBO리그', 'short': 'KBO 1군', 'country': 'KR', 'system': 'kbo', 'step': 2, 'level': 64.0},
    'mlb_a':   {'name': 'MLB 싱글A', 'short': '싱글A', 'country': 'US', 'system': 'mlb', 'step': 0, 'level': 50.0},
    'mlb_aa':  {'name': 'MLB 더블A', 'short': '더블A', 'country': 'US', 'system': 'mlb', 'step': 1, 'level': 57.0},
    'mlb_aaa': {'name': 'MLB 트리플A', 'short': '트리플A', 'country': 'US', 'system': 'mlb', 'step': 2, 'level': 63.0},
    'mlb':     {'name': '메이저리그', 'short': 'MLB', 'country': 'US', 'system': 'mlb', 'step': 3, 'level': 72.0},
    'npb2':    {'name': 'NPB 2군', 'short': 'NPB 2군', 'country': 'JP', 'system': 'npb', 'step': 0, 'level': 55.0},
    'npb1':    {'name': '일본프로야구(NPB)', 'short': 'NPB 1군', 'country': 'JP', 'system': 'npb', 'step': 1, 'level': 67.0},
    'cpbl':    {'name': '대만프로야구(CPBL)', 'short': 'CPBL', 'country': 'TW', 'system': 'cpbl', 'step': 0, 'level': 58.0},
}
SYSTEMS = {
    'amateur': ('little', 'ms', 'hs', 'univ'),
    'kbo': ('kbo3', 'kbo2', 'kbo1'),
    'mlb': ('mlb_a', 'mlb_aa', 'mlb_aaa', 'mlb'),
    'npb': ('npb2', 'npb1'),
    'cpbl': ('cpbl',),
}
SYSTEM_NAME = {'amateur': '아마추어', 'kbo': 'KBO', 'mlb': '미국', 'npb': '일본', 'cpbl': '대만'}
PRO_SYSTEMS = ('kbo', 'mlb', 'npb', 'cpbl')
TOP_LEAGUES = ('kbo1', 'mlb', 'npb1', 'cpbl')                 # 시상·명예의 전당의 기준이 되는 각 나라 최상위 리그
DEMOTE_GAP = 6.0                                              # 리그 수준보다 이만큼 낮아지면 한 단계 아래로


def league(code: str) -> dict:
    return LEAGUES.get(code) or LEAGUES['kbo3']


def level(code: str) -> float:
    return league(code)['level']


def short(code: str) -> str:
    return league(code)['short']


def is_pro(code: str) -> bool:
    return league(code)['system'] in PRO_SYSTEMS


def system_of(code: str) -> str:
    return league(code)['system']


def next_league(code: str) -> str | None:
    """같은 프로 사다리의 한 단계 위(아마추어는 학년으로 올라가므로 None)."""
    sysname = system_of(code)
    if sysname not in PRO_SYSTEMS:
        return None
    ladder = SYSTEMS[sysname]
    i = ladder.index(code)
    return ladder[i + 1] if i + 1 < len(ladder) else None


def prev_league(code: str) -> str | None:
    sysname = system_of(code)
    if sysname not in PRO_SYSTEMS:
        return None
    ladder = SYSTEMS[sysname]
    i = ladder.index(code)
    return ladder[i - 1] if i > 0 else None


def promote_at(code: str) -> float | None:
    """이 리그에서 위로 올라가는 승격 심사를 받을 수 있는 OVR(위 리그 수준 − 1)."""
    up = next_league(code)
    return level(up) - 1 if up else None


def demote_below(code: str) -> float | None:
    return level(code) - DEMOTE_GAP if prev_league(code) else None


def league_rank(code: str) -> float:
    """순위표 정렬용 — 리그 수준이 높을수록 위."""
    return level(code)


# ───────────────────────────── 프로 구단(이름은 소속 표시용, 로고 없음)
KBO_TEAMS = [
    ('kia', 'KIA 타이거즈', '#EA0029'), ('kt', 'KT 위즈', '#231F20'), ('lg', 'LG 트윈스', '#C30452'),
    ('nc', 'NC 다이노스', '#315288'), ('ssg', 'SSG 랜더스', '#CE0E2D'), ('doosan', '두산 베어스', '#131230'),
    ('lotte', '롯데 자이언츠', '#041E42'), ('samsung', '삼성 라이온즈', '#074CA1'),
    ('kiwoom', '키움 히어로즈', '#820024'), ('hanwha', '한화 이글스', '#FF6600'),
]
MLB_TEAMS = [
    ('nyy', '뉴욕 양키스', '#0C2340'), ('bos', '보스턴 레드삭스', '#BD3039'), ('tor', '토론토 블루제이스', '#134A8E'),
    ('tb', '탬파베이 레이스', '#092C5C'), ('bal', '볼티모어 오리올스', '#DF4601'), ('cle', '클리블랜드 가디언스', '#00385D'),
    ('min', '미네소타 트윈스', '#002B5C'), ('det', '디트로이트 타이거스', '#0C2340'), ('kc', '캔자스시티 로열스', '#004687'),
    ('cws', '시카고 화이트삭스', '#27251F'), ('hou', '휴스턴 애스트로스', '#EB6E1F'), ('tex', '텍사스 레인저스', '#003278'),
    ('sea', '시애틀 매리너스', '#0C2C56'), ('laa', 'LA 에인절스', '#BA0021'), ('ath', '애슬레틱스', '#003831'),
    ('atl', '애틀랜타 브레이브스', '#CE1141'), ('phi', '필라델피아 필리스', '#E81828'), ('nym', '뉴욕 메츠', '#002D72'),
    ('mia', '마이애미 말린스', '#00A3E0'), ('wsh', '워싱턴 내셔널스', '#AB0003'), ('mil', '밀워키 브루어스', '#12284B'),
    ('chc', '시카고 컵스', '#0E3386'), ('stl', '세인트루이스 카디널스', '#C41E3A'), ('cin', '신시내티 레즈', '#C6011F'),
    ('pit', '피츠버그 파이리츠', '#27251F'), ('lad', 'LA 다저스', '#005A9C'), ('sd', '샌디에이고 파드리스', '#2F241D'),
    ('sf', '샌프란시스코 자이언츠', '#FD5A1E'), ('ari', '애리조나 다이아몬드백스', '#A71930'), ('col', '콜로라도 로키스', '#33006F'),
]
NPB_TEAMS = [
    ('yomiuri', '요미우리 자이언츠', '#F97709'), ('hanshin', '한신 타이거스', '#FFE201'), ('chunichi', '주니치 드래건스', '#002569'),
    ('hiroshima', '히로시마 도요 카프', '#E60012'), ('yokohama', '요코하마 DeNA 베이스타스', '#0055A5'),
    ('yakult', '도쿄 야쿠르트 스왈로스', '#98C145'), ('softbank', '후쿠오카 소프트뱅크 호크스', '#F8B500'),
    ('nipponham', '홋카이도 닛폰햄 파이터스', '#006298'), ('chibalotte', '지바 롯데 마린스', '#221815'),
    ('rakuten', '도호쿠 라쿠텐 골든이글스', '#85010F'), ('orix', '오릭스 버펄로스', '#000019'),
    ('seibu', '사이타마 세이부 라이온스', '#1F366A'),
]
CPBL_TEAMS = [
    ('brothers', '중신 브라더스', '#F9D10B'), ('lions', '퉁이 라이온스', '#F26C24'), ('monkeys', '라쿠텐 몽키스', '#85010F'),
    ('guardians', '푸방 가디언스', '#004B97'), ('dragons', '웨이취안 드래곤스', '#C8102E'), ('hawks', 'TSG 호크스', '#00594F'),
]
SYSTEM_TEAMS = {'kbo': KBO_TEAMS, 'mlb': MLB_TEAMS, 'npb': NPB_TEAMS, 'cpbl': CPBL_TEAMS}
PRO_TEAM = {code: {'code': code, 'name': name, 'short': name.split()[-1] if len(name.split()) > 1 else name,
                   'color': color, 'system': sysname}
            for sysname, teams in SYSTEM_TEAMS.items() for code, name, color in teams}
for _c, _n, _col in KBO_TEAMS:                 # KBO 는 '두산', 'LG' 처럼 앞 단어로 줄여 부른다
    PRO_TEAM[_c]['short'] = _n.split()[0]

# ───────────────────────────── 학교(아마추어 소속)
HIGH_SCHOOLS = {
    '서울': ('경기고', '경기상업고', '경동고', '덕수고', '배명고', '배재고', '서울고', '서울동산고', '서울디자인고',
           '서울아이티고', '서울자동차고', '서울컨벤션고', '선린인터넷고', '성남고', '세명컴퓨터고', '신일고', '우신고',
           '장충고', '중앙고', '청원고', '충암고', '휘문고'),
    '부산': ('개성고', '경남고', '부경고', '부산고', '부산공업고'),
    '대구': ('경북고', '대구고', '대구상원고'),
    '인천': ('덕적고', '동산고', '인천고', '제물포고'),
    '광주': ('광주동성고', '광주제일고', '광주진흥고'),
    '대전': ('대전고', '대전제일고'),
    '경기': ('경기항공고', '경민IT고', '김포과학기술고', '라온고', '백송고', '부원고', '비봉고', '상우고', '세원고',
           '소래고', '신흥고', '안산공업고', '야탑고', '유신고', '율곡고', '인창고', '장안고', '진영고', '평택청담고',
           '충훈고'),
    '강원': ('강릉고', '강원고', '상동고', '설악고', '원주고'),
    '충북': ('세광고', '청주고'),
    '충남': ('공주고', '북일고'),
    '전북': ('군산상일고', '인상고', '전북인공지능고', '전주고'),
    '전남': ('나주광남고', '순천효천고', '화순고'),
    '경북': ('경주고', '도개고', '예일메디텍고', '의성고', '포항제철고'),
    '경남': ('금남고', '김해고', '마산고', '물금고', '창원공업고'),
    '제주': ('제주고',),
}
# 전통 강호 — 지원자가 몰려 들어가기 어렵고, 스카우트가 더 자주 온다(게임 설정)
HS_POWERHOUSE = {'덕수고', '서울고', '장충고', '충암고', '휘문고', '신일고', '선린인터넷고', '배명고', '경남고', '부산고',
                 '경북고', '대구고', '대구상원고', '인천고', '동산고', '광주제일고', '광주동성고', '유신고', '야탑고',
                 '북일고', '세광고', '청주고', '군산상일고', '마산고', '강릉고'}
MIDDLE_SCHOOLS = {
    '서울': ('배명중', '홍은중', '건대부중', '자양중', '성남중', '영남중'),
    '경기': ('개군중', '경민중', '금릉중', '단월중', '대원중', '라온중', '매송중', '매향중', '모가중', '부천중',
           '성일중', '소래중', '송전중', '신일중', '신흥중', '원당중', '율곡중', '이평중', '인창중', '중앙중'),
    '강원': ('경포중', '설악중', '원주중', '춘천중'),
    '대구': ('경상중', '대구중', '경운중', '경복중'),
    '경북': ('경주중', '포항제철중', '포항중', '구미중', '도개중'),
    '광주': ('충장중',),
    '제주': ('제일중',),
}
UNIVERSITIES = {
    '서울': ('건국대', '고려대', '동국대', '사이버한국외국어대', '서울대', '연세대'),
    '부산': ('경성대', '동아대', '동의과학대', '동의대', '부산과학기술대'),
    '대구': ('계명대', '수성대'),
    '인천': ('인하대',),
    '광주': ('동강대', '송원대'),
    '전남': ('목포과학대',),
    '대전': ('대덕대',),
    '세종': ('홍익대',),
    '경기': ('경민대', '경희대', '김포대', '동원대', '디지털서울문화예술대', '성균관대', '신안산대', '여주대',
           '용인예술과학대', '장안대', '중앙대', '한국관광대', '한양대'),
    '강원': ('강릉영동대', '한국골프과학기술대'),
    '충북': ('우석대', '유원대', '충북보건과학대'),
    '충남': ('단국대', '신성대', '청운대'),
    '전북': ('원광대', '전주기전대', '한일장신대', '호원대'),
    '경북': ('경일대', '구미대', '영남대'),
    '경남': ('경남대', '동원과학기술대'),
    '제주': ('제주관광대',),
}
UNIV_POWERHOUSE = {'고려대', '연세대', '성균관대', '한양대', '중앙대', '동국대', '건국대', '경희대', '인하대', '단국대',
                   '동아대', '영남대', '원광대'}
SCHOOLS_BY_LEAGUE = {'ms': MIDDLE_SCHOOLS, 'hs': HIGH_SCHOOLS, 'univ': UNIVERSITIES}


def little_club(region: str) -> str:
    """리틀야구 소속 — 지역 리틀야구단(실제 단체 이름을 흉내 내지 않는 일반 명칭)."""
    return f'{region} 리틀야구단'


def schools(league_code: str) -> list:
    """[(지역, 학교)] — 진학 화면 선택지."""
    return [(r, s) for r, names in SCHOOLS_BY_LEAGUE.get(league_code, {}).items() for s in names]


def school_region(league_code: str, name: str) -> str:
    for r, names in SCHOOLS_BY_LEAGUE.get(league_code, {}).items():
        if name in names:
            return r
    return ''


def powerhouse(league_code: str, name: str) -> bool:
    return name in (HS_POWERHOUSE if league_code == 'hs' else UNIV_POWERHOUSE if league_code == 'univ' else set())


def club_label(league_code: str, club: str) -> str:
    """화면에 보일 소속 이름 — 프로는 구단명, 아마추어는 학교·리틀야구단."""
    if is_pro(league_code):
        return PRO_TEAM.get(club, {}).get('name', club)
    return club


def club_color(league_code: str, club: str) -> str:
    if is_pro(league_code):
        return PRO_TEAM.get(club, {}).get('color', '#4f46e5')
    return '#4f46e5'


def club_short(league_code: str, club: str) -> str:
    """전광판·순위표용 짧은 이름 — 'KIA', '양키스', '덕수고', '서울 리틀'."""
    if club in PRO_TEAM:
        return PRO_TEAM[club]['short']
    return club.replace('리틀야구단', '리틀')


def opponents(league_code: str, club: str) -> list:
    """그날 붙을 상대 후보 — 프로는 같은 리그 구단, 학교는 같은 급 다른 학교, 리틀은 다른 지역 리틀야구단."""
    sysname = system_of(league_code)
    if sysname in PRO_SYSTEMS:
        pool = [c for c, _n, _col in SYSTEM_TEAMS[sysname]]
    elif league_code == 'little':
        pool = [little_club(r) for r in REGIONS]
    else:
        pool = [s for _r, s in schools(league_code)]
    return [c for c in pool if c != club] or pool


def team_label(code: str) -> str:
    """기록 행에 남은 소속(프로 구단 코드 또는 학교 이름) → 화면 이름."""
    return PRO_TEAM.get(code, {}).get('name', code)


def team_color(code: str) -> str:
    return PRO_TEAM.get(code, {}).get('color', '#4f46e5')


# ───────────────────────────── 학년·나이
SCHOOL_PATH = [('little', 6, 12)] + [('ms', g, 12 + g) for g in (1, 2, 3)] + [('hs', g, 15 + g) for g in (1, 2, 3)]
UNIV_YEARS = 4
SCHOOL_AGE = {'little': 6, 'ms': 12, 'hs': 15, 'univ': 18}      # 나이 = 기준 + 학년(리틀은 초6 = 12세)
NEXT_SCHOOL = {'little': 'ms', 'ms': 'hs'}                       # 고교·대학 졸업은 드래프트


def age_of(league_code: str, grade: int) -> int:
    return SCHOOL_AGE.get(league_code, 0) + grade


def last_grade(league_code: str) -> int:
    return {'little': 6, 'ms': 3, 'hs': 3, 'univ': UNIV_YEARS}.get(league_code, 0)


def grade_label(league_code: str, grade: int) -> str:
    return {'little': f'초등 {grade}학년', 'ms': f'중학교 {grade}학년', 'hs': f'고등학교 {grade}학년',
            'univ': f'대학교 {grade}학년'}.get(league_code, '')


def is_final_grade(league_code: str, grade: int) -> bool:
    """졸업(진학·드래프트)을 앞둔 학년."""
    return league_code in SCHOOL_AGE and grade >= last_grade(league_code)
