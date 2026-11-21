"""테크창 삼국지 — 카탈로그(장수·도시·특기·세력·군벌). DB 가 아니라 코드에 둔다(docs/samguk-design.md 9장).

판을 만들 때 필요한 값은 SamgukDay.board 에 스냅숏으로 박아 두므로, 여기를 고쳐도 지난 판은 바뀌지 않는다.
장수 명단 자체는 samguk_roster.py, 등급·능력치 규칙 검사는 validate().

수치를 바꾸면 test_samguk_data 가 규칙(등급별 능력 문턱, 지도 대칭·연결)을 다시 확인한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import samguk_roster as roster

# ── 세력 ────────────────────────────────────────────────────────────────
# 플레이어가 고르는 세력은 넷. 이민족(yi)은 도감 묶음일 뿐 플레이어 세력이 아니다.
FACTIONS = {
    'wei': '위',
    'shu': '촉',
    'wu': '오',
    'qun': '군웅',
}
GROUPS = {**FACTIONS, 'yi': '이민족'}

# 세력 보정(설계 6.4) — 하네스로 세력별 최고점 차가 5% 안인지 확인한다
FACTION_BONUS = {
    'wei': {'start_gold': 0.15},
    'shu': {'persuade': 5},
    'wu': {'water_power': 0.08},
    'qun': {'start_troops': 0.10},
}

# ── 등급 ────────────────────────────────────────────────────────────────
TIERS = {4: '전설', 3: '영웅', 2: '명장', 1: '장수'}
TIER_STARS = {4: '★★★★', 3: '★★★', 2: '★★', 1: '★'}
# 등급은 이름값이라 능력 합계로만 가르지 않는다(여포는 지력·정치가 낮아도 전설).
# 그래서 "가장 높은 능력" 또는 "합계" 둘 중 하나만 문턱을 넘으면 된다.
TIER_FLOOR = {4: (92, 320), 3: (82, 290), 2: (72, 260)}   # (최고 능력 하한, 합계 하한)
TIER1_CEIL = (90, 300)                                    # ★1 은 최고 능력 90 이하, 합계 300 이하
STAT_SUM_MAX = 350

# 등용 필요치(설계 4.3) — 포로면 −15
RECRUIT_NEED = {1: 60, 2: 80, 3: 100, 4: 125}
RECRUIT_SCORE = {1: 20, 2: 35, 3: 55, 4: 90}      # 하네스 1차: 10/20/35/60 이면 등용이 점수의 7%뿐이었다

# ── 특기 ────────────────────────────────────────────────────────────────
# 효과 수치는 samguk_rules 가 쓰고, 여기는 이름·설명(화면용)만 둔다.
SKILLS = {
    'charge': ('돌격', '공격할 때 전력이 오른다'),
    'cavalry': ('기병', '평지 도시를 칠 때 전력이 오른다'),
    'archery': ('궁술', '성을 지킬 때 전력이 오른다'),
    'navy': ('수군', '물가 도시 전투에서 전력이 크게 오른다'),
    'fire': ('화계', '계략 피해가 커진다'),
    'divine': ('신산', '계략 판정에서 지력을 더 받는다'),
    'fortify': ('축성', '지키는 성의 성벽이 단단해진다'),
    'supply': ('보급', '내정 수입이 늘고 출정 손실이 준다'),
    'virtue': ('인덕', '등용 설득력이 크게 오른다'),
    'fame': ('명성', '등용 설득력과 징병이 오른다'),
    'ambush': ('매복', '적이 쳐들어올 때 적의 전력을 깎는다'),
    'guard': ('경계', '적의 계략을 막아 낸다'),
}

ERAS = {'early': '후한 말(184~200)', 'mid': '삼국 정립(200~234)', 'late': '삼국 후기(234~280)'}


@dataclass(frozen=True)
class General:
    code: str
    name: str
    hanja: str
    group: str        # wei/shu/wu/qun/yi
    tier: int
    lead: int         # 통솔
    war: int          # 무력
    intl: int         # 지력
    pol: int          # 정치
    skill: str
    era: str
    source: str
    note: str
    female: bool = False
    no: int = 0       # 도감 번호(1부터, GROUPS 순서 → 명단 순서)

    @property
    def total(self) -> int:
        return self.lead + self.war + self.intl + self.pol

    @property
    def stats(self) -> tuple:
        return (self.lead, self.war, self.intl, self.pol)


def _build() -> tuple:
    out, no = [], 0
    for group, rows in roster.GROUPS:
        for row in rows:
            no += 1
            code, name, hanja, tier, lead, war, intl, pol, skill, era, source, note = row
            out.append(General(code, name, hanja, group, tier, lead, war, intl, pol, skill, era, source, note,
                               female=code in roster.FEMALE, no=no))
    return tuple(out)


GENERALS: tuple = _build()
GENERAL: dict = {g.code: g for g in GENERALS}


def by_group(group: str) -> list:
    return [g for g in GENERALS if g.group == group]


def by_tier(tier: int) -> list:
    return [g for g in GENERALS if g.tier == tier]


# ── 도시(설계 5장) ───────────────────────────────────────────────────────
# 좌표는 지도 그림용(0~1000, 서→동 x, 북→남 y). Codex 는 이 좌표에 맞춰 지도를 그린다.
# grade: normal 60 / key 100 / capital 150. terrain: plain 은 기병 보정, water 는 수군·오 보정.
CITY_VALUE = {'normal': 60, 'key': 100, 'capital': 150}


@dataclass(frozen=True)
class City:
    code: str
    name: str
    hanja: str
    grade: str
    terrain: str      # plain / hill / mountain / water
    x: int
    y: int
    links: tuple

    @property
    def value(self) -> int:
        return CITY_VALUE[self.grade]


CITIES: tuple = (
    City('beiping', '북평', '北平', 'normal', 'plain', 770, 110, ('ye',)),
    City('ye', '업', '鄴', 'capital', 'plain', 690, 250, ('beiping', 'luoyang', 'chenliu')),
    City('luoyang', '낙양', '洛陽', 'capital', 'plain', 560, 380, ('ye', 'changan', 'chenliu', 'xuchang', 'wan')),
    City('chenliu', '진류', '陳留', 'key', 'plain', 690, 370, ('ye', 'luoyang', 'xuchang', 'xiapi')),
    City('xuchang', '허창', '許昌', 'capital', 'plain', 640, 450, ('luoyang', 'chenliu', 'wan', 'shouchun')),
    City('xiapi', '하비', '下邳', 'key', 'plain', 830, 420, ('chenliu', 'shouchun', 'jianye')),
    City('shouchun', '수춘', '壽春', 'key', 'water', 750, 520, ('xuchang', 'xiapi', 'jianye', 'jiangxia')),
    City('jianye', '건업', '建業', 'capital', 'water', 860, 580, ('xiapi', 'shouchun', 'kuaiji')),
    City('kuaiji', '회계', '會稽', 'normal', 'water', 910, 700, ('jianye', 'changsha')),
    City('wan', '완', '宛', 'key', 'plain', 560, 490, ('luoyang', 'xuchang', 'xiangyang')),
    City('xiangyang', '양양', '襄陽', 'key', 'hill', 540, 580, ('wan', 'jiangling', 'jiangxia')),
    City('jiangxia', '강하', '江夏', 'normal', 'water', 660, 640, ('xiangyang', 'jiangling', 'shouchun')),
    City('jiangling', '강릉', '江陵', 'key', 'water', 510, 660, ('xiangyang', 'jiangxia', 'changsha', 'chengdu')),
    City('changsha', '장사', '長沙', 'normal', 'hill', 580, 790, ('jiangling', 'kuaiji')),
    City('changan', '장안', '長安', 'capital', 'plain', 400, 380, ('luoyang', 'tianshui', 'hanzhong')),
    City('tianshui', '천수', '天水', 'normal', 'hill', 240, 350, ('changan', 'hanzhong')),
    City('hanzhong', '한중', '漢中', 'key', 'mountain', 330, 480, ('changan', 'tianshui', 'chengdu')),
    City('chengdu', '성도', '成都', 'capital', 'mountain', 220, 650, ('hanzhong', 'jiangling')),
)
CITY: dict = {c.code: c for c in CITIES}

# 큰 강(지도 그림용 선) — 황하·장강이 지나는 도시 순서
RIVERS = {
    'huanghe': ('황하', ('tianshui', 'changan', 'luoyang', 'chenliu', 'ye')),
    'changjiang': ('장강', ('chengdu', 'jiangling', 'jiangxia', 'shouchun', 'jianye')),
}

# ── NPC 군벌 후보(판 생성기가 그날 6~9명을 고른다) ────────────────────────
# home: 우선 차지하는 도시, pool: 수비 장수를 뽑는 묶음, retainers: 있으면 먼저 쓰는 휘하 장수
LORDS = {
    'caocao': {'home': ('xuchang', 'chenliu', 'luoyang'), 'pool': 'wei', 'retainers': ()},
    'liubei': {'home': ('chengdu', 'hanzhong', 'jiangling'), 'pool': 'shu', 'retainers': ()},
    'sunquan': {'home': ('jianye', 'kuaiji', 'jiangxia'), 'pool': 'wu', 'retainers': ()},
    'yuanshao': {'home': ('ye', 'beiping'), 'pool': 'qun',
                 'retainers': ('yanliang', 'wenchou', 'tianfeng', 'jushou', 'shenpei', 'quyi', 'gaolan', 'fengji',
                               'guotu', 'xunchen', 'yuantan', 'yuanshang', 'yuanxi', 'chenlin', 'xuyou')},
    'yuanshu': {'home': ('shouchun',), 'pool': 'qun', 'retainers': ('jiling', 'zhangxun', 'yanbaihu')},
    'liubiao': {'home': ('xiangyang', 'jiangxia', 'changsha'), 'pool': 'qun',
                'retainers': ('caimao', 'kuaiyue', 'huangzu', 'liuqi', 'wenpin', 'huangzhong', 'wangcan')},
    'liuzhang': {'home': ('chengdu',), 'pool': 'qun',
                 'retainers': ('zhangren', 'yanyan', 'huangquan', 'zhangsong', 'fazheng', 'liyan', 'wuyi', 'wuban',
                               'mengda', 'donghe', 'yanghong')},
    'mateng': {'home': ('tianshui',), 'pool': 'qun', 'retainers': ('machao', 'madai', 'pangde', 'hansui', 'yanxing')},
    'gongsunzan': {'home': ('beiping',), 'pool': 'qun', 'retainers': ('liuyu', 'tadun')},
    'dongzhuo': {'home': ('changan', 'luoyang'), 'pool': 'qun',
                 'retainers': ('lubu', 'huaxiong', 'lijue', 'guosi', 'liru', 'xurong', 'zhangji', 'lisu', 'diaochan')},
    'lubu': {'home': ('xiapi',), 'pool': 'qun', 'retainers': ('chengong', 'gaoshun', 'zhangliao', 'zangba', 'diaochan')},
    'zhangjiao': {'home': ('chenliu', 'wan'), 'pool': 'qun',
                  'retainers': ('zhangbao_yt', 'zhangliang', 'bocai', 'zhangyan', 'liaohua', 'zhoucang')},
    'zhanglu': {'home': ('hanzhong',), 'pool': 'qun', 'retainers': ('pangde', 'yangfu')},
}


# ── 검사 ────────────────────────────────────────────────────────────────
def validate() -> list:
    """규칙 위반 목록. 비어 있으면 정상(test_samguk_data 가 확인한다)."""
    errs = []
    seen = set()
    for g in GENERALS:
        where = f'{g.code}({g.name})'
        if g.code in seen:
            errs.append(f'{where}: 코드 중복')
        seen.add(g.code)
        if not g.code.replace('_', '').isalnum() or g.code != g.code.lower():
            errs.append(f'{where}: 코드는 소문자 로마자·밑줄만')
        if g.group not in GROUPS:
            errs.append(f'{where}: 알 수 없는 세력 {g.group}')
        if g.tier not in TIERS:
            errs.append(f'{where}: 알 수 없는 등급 {g.tier}')
            continue
        if g.skill not in SKILLS:
            errs.append(f'{where}: 알 수 없는 특기 {g.skill}')
        if g.era not in ERAS:
            errs.append(f'{where}: 알 수 없는 시기 {g.era}')
        if not all(1 <= s <= 100 for s in g.stats):
            errs.append(f'{where}: 능력은 1~100')
        if g.total > STAT_SUM_MAX:
            errs.append(f'{where}: 합계 {g.total} > {STAT_SUM_MAX}')
        top = max(g.stats)
        if g.tier in TIER_FLOOR:
            need_top, need_sum = TIER_FLOOR[g.tier]
            if top < need_top and g.total < need_sum:
                errs.append(f'{where}: ★{g.tier} 문턱 미달(최고 {top} < {need_top}, 합계 {g.total} < {need_sum})')
        else:
            ceil_top, ceil_sum = TIER1_CEIL
            if top > ceil_top or g.total > ceil_sum:
                errs.append(f'{where}: ★1 상한 초과(최고 {top}, 합계 {g.total}) — 등급을 올릴 것')
        if not g.source or not g.note:
            errs.append(f'{where}: 출처·근거 한 줄이 비었음')
    for c in CITIES:
        for other in c.links:
            if other not in CITY:
                errs.append(f'{c.code}: 없는 도시 {other} 와 이어짐')
            elif c.code not in CITY[other].links:
                errs.append(f'{c.code}↔{other}: 인접이 한쪽만 있음')
    # 지도 전체가 이어져 있는가
    start = CITIES[0].code
    stack, reach = [start], {start}
    while stack:
        for nxt in CITY[stack.pop()].links:
            if nxt in CITY and nxt not in reach:
                reach.add(nxt)
                stack.append(nxt)
    if len(reach) != len(CITIES):
        errs.append(f'지도가 끊김: {sorted(set(CITY) - reach)}')
    for lord, info in LORDS.items():
        if lord not in GENERAL:
            errs.append(f'군벌 {lord}: 장수 명단에 없음')
        for h in info['home']:
            if h not in CITY:
                errs.append(f'군벌 {lord}: 없는 도시 {h}')
        for r in info['retainers']:
            if r not in GENERAL:
                errs.append(f'군벌 {lord}: 없는 휘하 {r}')
        if info['pool'] not in GROUPS:
            errs.append(f'군벌 {lord}: 알 수 없는 묶음 {info["pool"]}')
    return errs


def summary() -> dict:
    """묶음·등급별 인원(문서·하네스 보고용)."""
    out = {'total': len(GENERALS), 'group': {}, 'tier': {}}
    for g in GENERALS:
        out['group'][g.group] = out['group'].get(g.group, 0) + 1
        out['tier'][g.tier] = out['tier'].get(g.tier, 0) + 1
    return out
