"""저장된 과거 문구의 표시만 교정한다. 리그 코드·원본 기록·선택 키는 바꾸지 않는다."""

DISPLAY_ALIASES = (
    ('KBO 1군', 'KBO'), ('NPB 1군', 'NPB'), ('KBO리그', 'KBO 리그'),
    ('KBO 육성군', '육성군'),
    ('MLB 싱글A', '마이너리그 싱글A'), ('MLB 더블A', '마이너리그 더블A'),
    ('MLB 트리플A', '마이너리그 트리플A'),
    ('주전 선발', '일반 선발'), ('백업 선발', '대체 선발'),
    ('상위타선', '상위 타선'), ('중심타선', '중심 타선'), ('하위타선', '하위 타선'),
    ('승격 심사', '콜업 테스트'), ('블론세이브', '블론 세이브'),
    ('MLB 추격조 대기', 'MLB 롱릴리프'),
    ('승리조', '중간계투'), ('오클랜드 애슬레틱스', '애슬레틱스'),
)


def display(value):
    if value is None:
        return ''
    result = str(value)
    for before, after in (('KBO 1군', 'KBO'), ('NPB 1군', 'NPB')):
        # '군'의 받침에 맞춰 저장했던 조사도 새 약칭에 맞춘다.
        for old, new in (('이에요', '예요'), ('이었', '였'), ('이지만', '지만'),
                         ('이고', '고'), ('이라', '라'), ('으로', '로'),
                         ('은', '는'), ('을', '를'), ('과', '와'), ('이', '가')):
            result = result.replace(before + old, after + new)
    for before, after in DISPLAY_ALIASES:
        result = result.replace(before, after)
    return result


# ───────────────────────────── 조사(받침에 따라)
_LETTER_BATCHIM = set('LMNRlmnr')
_DIGIT_BATCHIM = {'0': 'ㅇ', '1': 'ㄹ', '3': 'ㅁ', '6': 'ㄱ', '7': 'ㄹ', '8': 'ㄹ'}


def josa(word: str, pair: str) -> str:
    """받침에 맞는 조사 — pair '이/가'·'을/를'·'은/는'·'와/과'·'으로/로'. 괄호 안 글자는 빼고 본다."""
    w = (word or '').split('(')[0].rstrip(' ‘’\'"')
    ch = w[-1:] if w else ''
    batchim, rieul = False, False
    if '가' <= ch <= '힣':
        jong = (ord(ch) - 0xAC00) % 28
        batchim, rieul = jong != 0, jong == 8
    elif ch in _DIGIT_BATCHIM:
        batchim, rieul = True, _DIGIT_BATCHIM[ch] == 'ㄹ'
    elif ch in _LETTER_BATCHIM:
        batchim, rieul = True, ch in 'LRlr'
    first, second = pair.split('/')
    if pair == '으로/로':
        return '로' if (not batchim or rieul) else '으로'
    if pair in ('이/가', '을/를', '은/는', '과/와'):
        return first if batchim else second
    return second if batchim else first          # '와/과' 처럼 받침 없는 쪽을 앞에 쓴 경우


# ───────────────────────────── 가상 인물 이름 안전망(실존 정치인·이름난 야구인과 겹치지 않게)
def is_real_person(name: str) -> bool:
    """가상 경쟁자·로스터 이름이 막아 둔 실존 인물(정치인·역대 대통령, 이름난 야구인)과 겹치는지."""
    from . import rookie_names as N          # 지연 import — 이 모듈은 다른 모듈에 기대지 않게 둔다
    from . import rookie_staff as S
    name = (name or '').strip()
    return bool(name) and (N.blocked(name) or name in S.FAMOUS)
