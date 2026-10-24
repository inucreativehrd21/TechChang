"""투타 유형과 손잡이 특성. 저장 정보가 없는 기존 선수는 항상 우투·우타예요."""
import hashlib
import random
THROWS = (('R', '우투'), ('L', '좌투'))
BATS = (('R', '우타'), ('L', '좌타'))
TRAITS = {
    'left_slayer': ('좌승사자', '좌타자 상대 구속·제구가 3 높아져요.', 'pitcher', None),
    'right_slayer': ('우타 봉쇄', '우타자 상대 변화구·제구가 3 높아져요.', 'pitcher', None),
    'left_fireball': ('좌완 강속구', '좌투수의 구속이 경기에서 2 높아져요.', 'pitcher', 'L'),
    'right_power': ('우완 정면승부', '우투수의 구속·멘탈이 경기에서 2 높아져요.', 'pitcher', 'R'),
    'left_killer': ('좌투 킬러', '좌투수 상대 컨택·선구안이 3 높아져요.', 'batter', None),
    'right_killer': ('우투 킬러', '우투수 상대 컨택·선구안이 3 높아져요.', 'batter', None),
    'right_slugger': ('우타거포', '우타자의 파워가 경기에서 3 높아져요.', 'batter', 'R'),
    'left_contact': ('좌타 정교함', '좌타자의 컨택·주루가 경기에서 2 높아져요.', 'batter', 'L'),
}

def storage(p):
    return p.flags if hasattr(p, 'flags') else p.career

def sides(p):
    data = (storage(p) or {}).get('hands') or {}
    return (data.get('throwing') if data.get('throwing') in dict(THROWS) else 'R',
            data.get('batting') if data.get('batting') in dict(BATS) else 'R')

def label(p):
    throwing, batting = sides(p)
    return dict(THROWS)[throwing] + '·' + dict(BATS)[batting]

def validate(throwing, batting):
    if throwing not in dict(THROWS) or batting not in dict(BATS):
        raise ValueError('우투·좌투와 우타·좌타를 다시 골라 주세요.')

def eligible(p, code):
    if code not in TRAITS:
        return True
    _name, _desc, role, side = TRAITS[code]
    throwing, batting = sides(p)
    return p.role == role and (side is None or side == (throwing if role == 'pitcher' else batting))

def initialize(p, throwing, batting, rng, *, inherited=False):
    validate(throwing, batting)
    data = dict(storage(p) or {}, hands=dict(throwing=throwing, batting=batting))
    if hasattr(p, 'flags'):
        p.flags = data
    else:
        p.career = data
    p.traits = [t for t in (p.traits or []) if eligible(p, t)]
    p.traits_seen = [t for t in (p.traits_seen or []) if t in p.traits]
    # 새 특성 추첨이 기존 시즌·이벤트 난수 순서를 밀지 않게 별도 난수기를 쓴다.
    try:
        seed = hashlib.sha256(repr(rng.getstate()).encode()).hexdigest()
        roller = random.Random(f'{seed}:{p.role}:{throwing}:{batting}')
    except (AttributeError, NotImplementedError):
        roller = random.SystemRandom()
    if not inherited and roller.random() < .35:
        pool = [t for t in TRAITS if eligible(p, t)]
        p.traits = list(p.traits) + [roller.choice(pool)]

def annotate(p, stats):
    throwing, batting = sides(p)
    return dict(stats, _throwing=throwing, _batting=batting,
                _hand_traits=[t for t in (p.traits or []) if t in TRAITS and eligible(p, t)])

def matchup(batter, pitcher):
    # 순수 보정 검사·기존 외부 호출은 메타데이터가 없으면 원래 수식을 쓴다.
    if '_batting' not in batter and '_throwing' not in pitcher:
        return batter, pitcher
    b, p = dict(batter), dict(pitcher)
    bs, ps = b.get('_batting', 'R'), p.get('_throwing', 'R')
    def add(stats, keys, amount):
        for key in keys:
            stats[key] = min(110, float(stats.get(key, 25)) + amount)
    add(b, ('contact',), 1.2 if bs != ps else -.6)
    bt, pt = b.get('_hand_traits', []), p.get('_hand_traits', [])
    if 'left_slayer' in pt and bs == 'L':
        add(p, ('velocity', 'control'), 3)
    if 'right_slayer' in pt and bs == 'R':
        add(p, ('breaking', 'control'), 3)
    if 'left_fireball' in pt:
        add(p, ('velocity',), 2)
    if 'right_power' in pt:
        add(p, ('velocity', 'mental'), 2)
    if 'left_killer' in bt and ps == 'L' or 'right_killer' in bt and ps == 'R':
        add(b, ('contact', 'eye'), 3)
    if 'right_slugger' in bt:
        add(b, ('power',), 3)
    if 'left_contact' in bt:
        add(b, ('contact', 'speed'), 2)
    return b, p

