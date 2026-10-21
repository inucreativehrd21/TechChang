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
