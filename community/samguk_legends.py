"""테크창 삼국지 — 외전·기연 장수와 전설 시리즈(설계 8장).

- 외전 8명(삼국지 이야기 속 숨은 인물)과 기연 19명(동이 7: 같은 시대 한반도·왜 인물 / 시공 12: 다른 시대의 한국·일본 전설)은
  본편 명단(samguk_roster)에 없고, 시리즈를 끝내야만 영입을 시도할 수 있다. 장원 층에만 있으므로 매일 판의 힘과는 상관없다.
- 시리즈는 단계 목록(데이터)이다. 단계 종류는 STEP_KINDS 몇 가지로 묶었다 — 시리즈마다 코드를 따로 짜지 않는다.
- 판 이벤트(event)는 그날 판의 board['legends'] 에 뜨고 모두에게 같다. 이벤트를 진행하면 군령이 들지만 점수는 없다.
- 한 시리즈의 이벤트 단계는 하루에 한 칸만 나아간다(서로 다른 날). 누적 단계(일기토 n승 등)는 판이 닫힐 때 그날 기록으로 센다.
- 소문은 지나가는 거지(동냥)·객잔 나그네에게서 듣는다. 소문이 없어도 흐릿한 이벤트는 직접 진행할 수 있다(모바일만 써도 막히지 않게).
- 한반도 침략에 앞장선 인물은 넣지 않는다. 실존 위인은 존중하는 어조로 쓴다(설계 8.5).
"""
from __future__ import annotations

import hashlib
from datetime import date

from django.db import transaction

from . import samguk_data as D

# ── 숨은 장수(도감 외전·기연 칸) ────────────────────────────────────────────
# (코드, 이름, 한자, 묶음, 등급, 통솔, 무력, 지력, 정치, 특기, 나라·시대, 출처, 근거, 여성)
_HIDDEN_ROWS = [
    ('menghuo', '맹획', '孟獲', 'gaiden', 3, 80, 86, 40, 55, 'charge', '남만', '정사 제갈량전 주석 · 연의', '일곱 번 잡혔다 풀려나 끝내 마음으로 따른 남만의 왕', False),
    ('zhurong', '축융', '祝融', 'gaiden', 3, 70, 88, 40, 40, 'archery', '남만', '연의', '날아가는 칼을 쓴 맹획의 아내', True),
    ('huatuo', '화타', '華佗', 'gaiden', 3, 10, 10, 90, 70, 'supply', '후한 말', '정사 위서 방기전', '마비산으로 수술을 한 신의', False),
    ('simahui', '사마휘', '司馬徽', 'gaiden', 3, 30, 10, 95, 80, 'virtue', '후한 말', '정사 방통전 주석', '와룡과 봉추를 알아본 수경 선생', False),
    ('huangyueying', '황월영', '黃月英', 'gaiden', 3, 40, 20, 92, 78, 'fortify', '후한 말', '정사 제갈량전 주석 · 후대 이야기', '제갈량의 아내, 재주 많은 발명가로 전해짐', True),
    ('zuoci', '좌자', '左慈', 'gaiden', 3, 20, 30, 95, 40, 'divine', '후한 말', '후한서 방술전 · 연의', '조조를 골탕 먹인 도사', False),
    ('guanlu', '관로', '管輅', 'gaiden', 3, 10, 10, 96, 50, 'divine', '삼국', '정사 위서 방기전', '점술로 이름난 술사', False),
    ('yuji', '우길', '于吉', 'gaiden', 3, 20, 10, 90, 60, 'virtue', '후한 말', '정사 손책전 주석', '손책과 악연이 얽힌 강동의 도사', False),
    # 동이 기연 — 같은 시대(정사 동이전·삼국사기)
    ('dongcheon', '동천왕', '東川王', 'giyeon', 4, 86, 80, 70, 76, 'cavalry', '고구려 · 3세기', '삼국사기 고구려본기 · 정사 관구검전', '관구검의 침공을 버텨 낸 고구려의 왕', False),
    ('milu', '밀우', '密友', 'giyeon', 3, 74, 82, 50, 40, 'guard', '고구려 · 3세기', '삼국사기 고구려본기', '결사대로 동천왕의 퇴로를 지킨 충신', False),
    ('yuyu', '유유', '紐由', 'giyeon', 3, 60, 70, 72, 40, 'ambush', '고구려 · 3세기', '삼국사기 고구려본기', '거짓 항복으로 위 장수를 쓰러뜨린 충신', False),
    ('eulpaso', '을파소', '乙巴素', 'giyeon', 3, 40, 20, 88, 96, 'supply', '고구려 · 2세기 말', '삼국사기 고구려본기', '진대법으로 굶주린 백성을 살린 재상', False),
    ('seokuro', '석우로', '昔于老', 'giyeon', 3, 82, 80, 64, 60, 'navy', '신라 · 3세기', '삼국사기 석우로 열전', '바다 건너 적을 막은 신라의 장군', False),
    ('goi', '고이왕', '古爾王', 'giyeon', 3, 72, 60, 74, 88, 'virtue', '백제 · 3세기', '삼국사기 백제본기', '관등과 율령을 정비한 백제의 왕', False),
    ('himiko', '히미코', '卑彌呼', 'giyeon', 3, 50, 20, 88, 84, 'fame', '왜 · 3세기', '정사 위서 동이전 왜인조', '위에 사신을 보내 친위왜왕의 칭호를 받은 여왕', True),
    # 시공 기연 — 다른 시대의 전설(판타지 이벤트임을 화면에서 밝힌다)
    ('eulji', '을지문덕', '乙支文德', 'giyeon', 4, 92, 70, 96, 80, 'divine', '고구려 · 7세기', '삼국사기 을지문덕 열전', '살수에서 수나라 대군을 꺾은 명장'),
    ('yangmanchun', '양만춘', '楊萬春', 'giyeon', 3, 88, 78, 80, 70, 'fortify', '고구려 · 7세기', '후대 기록 · 안시성 전투', '안시성을 끝까지 지켜 낸 성주로 전해짐'),
    ('gyebaek', '계백', '階伯', 'giyeon', 3, 86, 90, 64, 56, 'guard', '백제 · 7세기', '삼국사기 계백 열전', '황산벌에서 오천 결사대로 맞선 장군'),
    ('kimyusin', '김유신', '金庾信', 'giyeon', 4, 94, 88, 86, 82, 'fame', '신라 · 7세기', '삼국사기 김유신 열전', '삼국 통일의 주역'),
    ('gwanggaeto', '광개토대왕', '廣開土大王', 'giyeon', 4, 97, 90, 80, 86, 'cavalry', '고구려 · 4~5세기', '광개토대왕릉비', '사방으로 영토를 넓힌 고구려의 왕'),
    ('gangamchan', '강감찬', '姜邯贊', 'giyeon', 4, 92, 60, 92, 86, 'ambush', '고려 · 11세기', '고려사 강감찬 열전', '귀주에서 거란군을 크게 무찌른 명장'),
    ('yisunsin', '이순신', '李舜臣', 'giyeon', 4, 98, 80, 92, 84, 'navy', '조선 · 16세기', '난중일기 · 선조실록', '바다를 지켜 낸 수군의 영웅'),
    ('musashi', '미야모토 무사시', '宮本武蔵', 'giyeon', 4, 60, 98, 74, 30, 'charge', '일본 · 17세기', '오륜서', '두 자루 칼로 이름난 검객'),
    ('yoshitsune', '미나모토노 요시쓰네', '源義経', 'giyeon', 4, 92, 92, 80, 40, 'cavalry', '일본 · 12세기', '헤이케 이야기', '절벽을 내달리는 기습으로 이름난 무장'),
    ('kenshin', '우에스기 겐신', '上杉謙信', 'giyeon', 4, 95, 92, 78, 70, 'charge', '일본 · 16세기', '전국 시대 기록', '군신이라 불린 에치고의 무장'),
    ('shingen', '다케다 신겐', '武田信玄', 'giyeon', 4, 95, 82, 88, 84, 'cavalry', '일본 · 16세기', '전국 시대 기록', '풍림화산의 깃발을 든 가이의 무장'),
    ('yukimura', '사나다 유키무라', '真田幸村', 'giyeon', 4, 90, 92, 78, 50, 'charge', '일본 · 17세기', '오사카 전투 기록', '마지막 돌격으로 이름을 남긴 무장'),
]


def _hidden():
    out = {}
    for row in _HIDDEN_ROWS:
        code, name, hanja, group, tier, lead, war, intl, pol, skill, nation, source, note = row[:13]
        female = row[13] if len(row) > 13 else False
        out[code] = D.General(code, name, hanja, group, tier, lead, war, intl, pol, skill, 'mid', source, note,
                              female=female, no=0)
    return out


HIDDEN = _hidden()
NATION = {row[0]: row[10] for row in _HIDDEN_ROWS}
HIDDEN_GROUPS = {'gaiden': '외전', 'giyeon': '기연'}

# ── 판 이벤트 ───────────────────────────────────────────────────────────
# code: (이름, 흐릿한 표시, 뜨는 도시 후보, 며칠마다, 조건 정세)
EVENTS = {
    'nanman': ('남만 반란', '남쪽 산속이 소란스러워요', ('chengdu', 'jiangling', 'changsha'), 3, None),
    'plague_doctor': ('떠돌이 의원', '역병 도는 도시에 낯선 의원이 머물고 있어요', None, 1, 'plague'),
    'hermit': ('양양의 은사', '양양 근처에 수상한 노인이 머물고 있어요', ('xiangyang',), 4, None),
    'taoist': ('강동의 도사', '강동에 기이한 도사가 나타났다는 말이 돌아요', ('jianye', 'kuaiji'), 4, None),
    'liaodong': ('요동 원정', '북쪽 국경에 낯선 군사가 보여요', ('beiping', 'ye'), 5, None),
    'relief': ('흉년의 백성', '굶주린 백성들이 성문 앞에 모였어요', None, 1, 'harvest'),
    'envoy': ('바다 건너 사신', '낙양에 먼 나라 사신이 왔다는 소문이에요', ('luoyang',), 5, None),
    'coast': ('바닷가의 적', '바닷가 고을이 소란스러워요', ('kuaiji', 'jianye', 'xiapi'), 5, None),
    'rift': ('시공의 틈', '하늘 한쪽이 기이하게 일렁여요', None, 7, None),
}

# ── 단계 종류 ───────────────────────────────────────────────────────────
# event      : 그날 판의 그 이벤트를 진행(군령 1). cond = {'stat': 'war', 'min': 75} / {'skill': 'navy'}
# recruit    : 판에서 codes 중 하나를 등용          recruit_all: codes 를 모두(여러 날 합산) 등용
# win_with   : code 가 낀 출정에서 이김             hold: 그날 판에서 city 를 차지
# manor      : 장원 building 이 level 이상          rumor: 이 시리즈 소문을 n 개 들음
# after      : 다른 시리즈를 마침                   progress_of: 다른 시리즈가 step 칸 이상
# 누적(판이 닫힐 때 센다): duel n · naval n · underdog n · defend_days n · scheme_days n(hold) · develop_days n(per)
#                         · wins n · destroy n(한 판에서) · four_dirs · counter · terrain_win · beat_strongest
#                         · no_attack_with code(그 장수를 등용한 날 출정시키지 않음)
SERIES = {
    # 외전
    'menghuo': {'name': '칠종칠금', 'grants': ['menghuo'], 'kind': 'gaiden', 'steps': [
        {'kind': 'event', 'event': 'nanman', 'cond': {'stat': 'war', 'min': 75}, 'times': 7,
         'text': '남만군을 이기고 맹획을 풀어 주기'}],
        'attempt': {'fame': 30},
        'rumors': ['남쪽 오랑캐 왕이 잡혀도 잡혀도 다시 일어난다더군.',
                   '그 왕은 일곱 번을 잡아 풀어 줘야 마음으로 따른다는 말이 있어.',
                   '남만 반란이 일면 무력 75 넘는 장수를 그 성 곁에 두게. 이기고 풀어 주는 거야.']},
    'zhurong': {'name': '불의 여장', 'grants': ['zhurong'], 'kind': 'gaiden', 'steps': [
        {'kind': 'progress_of', 'series': 'menghuo', 'step': 4, 'text': '칠종칠금을 네 번 넘기기'},
        {'kind': 'event', 'event': 'nanman', 'cond': {'stat': 'war', 'min': 85}, 'text': '남만 이벤트에서 무력 85 장수로 맞서기'},
        {'kind': 'after', 'series': 'menghuo', 'text': '맹획을 영입하기'}],
        'attempt': {'fame': 30},
        'rumors': ['남만 왕 곁에 칼을 날리는 여장부가 있다더군.',
                   '그 여장부는 남편이 마음을 연 뒤에야 따라온다네.']},
    'huatuo': {'name': '청낭서', 'grants': ['huatuo'], 'kind': 'gaiden', 'steps': [
        {'kind': 'event', 'event': 'plague_doctor', 'text': '역병 도는 날, 떠돌이 의원을 맞기'},
        {'kind': 'win_with', 'code': 'guanyu', 'text': '관우를 등용해 출정에서 이기기(독화살 치료)'},
        {'kind': 'manor', 'building': 'library', 'level': 2, 'text': '서고 2단계'}],
        'attempt': {'fame': 30},
        'rumors': ['역병이 도는 날이면 이름 없는 의원이 나타난다더군.',
                   '그 의원은 팔에 독화살을 맞은 장수를 고쳐 보고 싶어 한다네.',
                   '의술 책을 맡길 서고가 있어야 마음을 놓을 거야.']},
    'simahui': {'name': '수경의 문하', 'grants': ['simahui'], 'kind': 'gaiden', 'steps': [
        {'kind': 'event', 'event': 'hermit', 'cond': {'stat': 'pol', 'min': 80}, 'own': True,
         'text': '양양을 차지하고 정치 80 장수로 은사를 찾아가기'},
        {'kind': 'recruit', 'codes': ['zhugeliang', 'pangtong'], 'text': '판에서 제갈량이나 방통을 등용'},
        {'kind': 'recruit_all', 'codes': ['zhugeliang', 'pangtong'], 'text': '나머지 한 사람도 등용'}],
        'attempt': {'fame': 30},
        'rumors': ['양양 근처에 사람 보는 눈이 남다른 노인이 산다더군.',
                   '그 노인은 와룡과 봉추를 모두 얻은 사람을 보고 싶어 한대.']},
    'huangyueying': {'name': '기계의 명인', 'grants': ['huangyueying'], 'kind': 'gaiden', 'steps': [
        {'kind': 'after', 'series': 'simahui', 'text': '수경의 문하를 마치기'},
        {'kind': 'manor', 'building': 'library', 'level': 3, 'text': '서고 3단계'},
        {'kind': 'recruit', 'codes': ['zhugeliang'], 'text': '판에서 제갈량을 등용'}],
        'attempt': {'fame': 40},
        'rumors': ['수경 선생 문하에 기계를 잘 만드는 처자가 있다더군.']},
    'zuoci': {'name': '도사의 장난', 'grants': ['zuoci'], 'kind': 'gaiden', 'steps': [
        {'kind': 'rumor', 'n': 1, 'text': '좌자의 소문 듣기'},
        {'kind': 'scheme_days', 'n': 3, 'city': 'xuchang', 'text': '허창을 가진 날 계략 성공, 서로 다른 세 날'}],
        'attempt': {'fame': 30},
        'rumors': ['허창에서 귤 껍질 속을 비워 놓는 도사가 있었다지. 계략에 밝은 사람을 좋아한대.']},
    'guanlu': {'name': '점술가의 예언', 'grants': ['guanlu'], 'kind': 'gaiden', 'steps': [
        {'kind': 'rumor', 'n': 5, 'text': '관로의 소문 다섯 개 모으기'},
        {'kind': 'hold', 'city': '@prophecy', 'text': '예언한 도시를 판에서 차지'}],
        'attempt': {'fame': 30},
        'rumors': ['점을 기막히게 치는 술사가 있다더군.', '그 술사는 별자리로 사람의 앞날을 본대.',
                   '술사가 어느 도시 이름을 자꾸 중얼거린다던데.', '예언을 믿는 사람에게만 모습을 보인다네.',
                   '그 도시를 손에 넣으면 술사가 찾아올 거래.']},
    'yuji': {'name': '강동의 신선', 'grants': ['yuji'], 'kind': 'gaiden', 'steps': [
        {'kind': 'event', 'event': 'taoist', 'text': '강동의 도사를 만나기'},
        {'kind': 'no_attack_with', 'code': 'sunce', 'text': '손책을 등용한 날, 손책을 출정시키지 않기'}],
        'attempt': {'fame': 30},
        'rumors': ['강동 도사는 소패왕과 사이가 아주 나빴다지.', '그 도사는 소패왕이 칼을 들지 않는 날을 기다린대.']},
    # 동이 기연
    'dongcheon': {'name': '요동의 바람', 'grants': ['dongcheon'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'liaodong', 'cond': {'stat': 'lead', 'min': 80}, 'own': True, 'times': 2,
         'text': '요동 원정 이벤트를 통솔 80 장수로 버텨 내기(두 번)'}],
        'attempt': {'fame': 60},
        'rumors': ['북쪽 국경 너머에 위나라 군사와 맞선 왕이 있다더군.',
                   '그 왕은 성을 직접 지키는 사람에게 손을 내민대.']},
    'milu': {'name': '두 충신', 'grants': ['milu', 'yuyu'], 'kind': 'giyeon', 'steps': [
        {'kind': 'progress_of', 'series': 'dongcheon', 'step': 1, 'text': '요동의 바람을 한 번 넘기기'},
        {'kind': 'duel', 'n': 1, 'text': '일기토에서 이기기'},
        {'kind': 'scheme_days', 'n': 1, 'text': '계략을 성공시키기'}],
        'attempt': {'fame': 60},
        'rumors': ['고구려 왕 곁에는 목숨을 내건 두 충신이 있었다지.']},
    'eulpaso': {'name': '진대법', 'grants': ['eulpaso'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'relief', 'cond': {'stat': 'pol', 'min': 85}, 'text': '흉년의 백성을 정치 85 장수로 구하기'}],
        'attempt': {'fame': 60},
        'rumors': ['굶주린 백성에게 곡식을 빌려준 재상 이야기를 들었나?']},
    'seokuro': {'name': '우로의 출정', 'grants': ['seokuro'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'coast', 'cond': {'skill': 'navy'}, 'text': '바닷가의 적에 수군 장수로 맞서기'},
        {'kind': 'naval', 'n': 1, 'text': '수군 장수로 물가 도시를 차지'}],
        'attempt': {'fame': 60},
        'rumors': ['바다 건너 신라에 물 위에서 강한 장군이 있다더군.']},
    'goi': {'name': '한강의 왕', 'grants': ['goi'], 'kind': 'giyeon', 'steps': [
        {'kind': 'develop_days', 'n': 3, 'per': 3, 'text': '한 판에 내정 세 번, 서로 다른 세 날'}],
        'attempt': {'fame': 60},
        'rumors': ['한강 가의 왕은 나라 살림을 반듯하게 세운 사람을 좋아한대.']},
    'himiko': {'name': '친위왜왕', 'grants': ['himiko'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'envoy', 'cond': {'stat': 'pol', 'min': 80}, 'own': True,
         'text': '낙양을 차지한 날, 정치 80 장수로 사신을 맞기'}],
        'attempt': {'fame': 60},
        'rumors': ['바다 건너 여왕이 위나라에 사신을 보냈다더군. 낙양 주인이 맞이해야 한대.']},
    # 시공 기연 — 모두 '시공의 틈'을 한 번 지나야 시작된다
    'eulji': {'name': '살수의 계', 'grants': ['eulji'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'underdog', 'n': 1, 'ratio': 2.0, 'text': '내 병력 두 배가 넘는 적을 이기기'}],
        'attempt': {'fame': 100},
        'rumors': ['물을 건너는 대군을 지략으로 꺾은 장수가 틈 너머에 있다더군.']},
    'yangmanchun': {'name': '안시성', 'grants': ['yangmanchun'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'defend_days', 'n': 3, 'text': '쳐들어온 적을 막아 내기, 서로 다른 세 날'}],
        'attempt': {'fame': 100},
        'rumors': ['끝까지 성을 내주지 않은 성주가 있었다더군.']},
    'gyebaek': {'name': '황산벌', 'grants': ['gyebaek'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'underdog', 'n': 1, 'ratio': 1.0, 'text': '병력이 적은 쪽으로 출정해 이기기'}],
        'attempt': {'fame': 100},
        'rumors': ['적은 병사로 큰 군대에 맞선 장군 이야기를 아나?']},
    'kimyusin': {'name': '삼국의 꿈', 'grants': ['kimyusin'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'destroy', 'n': 3, 'text': '한 판에서 군벌 셋을 멸망시키기'}],
        'attempt': {'fame': 120},
        'rumors': ['셋으로 나뉜 땅을 하나로 묶은 장군이 틈 너머에 있대.']},
    'gwanggaeto': {'name': '사방의 정복', 'grants': ['gwanggaeto'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'four_dirs', 'text': '시작 도시의 동서남북 네 방향에 도시를 하나씩 차지'}],
        'attempt': {'fame': 120},
        'rumors': ['사방으로 땅을 넓힌 대왕이 있었다지.']},
    'gangamchan': {'name': '귀주의 바람', 'grants': ['gangamchan'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'counter', 'text': '쳐들어온 적을 막은 날, 출정에서도 이기기'}],
        'attempt': {'fame': 120},
        'rumors': ['물러나는 적을 끝까지 쫓아 무찌른 명장이 있대.']},
    'yisunsin': {'name': '바다의 수호자', 'grants': ['yisunsin'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'naval', 'n': 5, 'text': '수군 장수로 물가 도시 전투에서 다섯 번 이기기(여러 날 합산)'}],
        'attempt': {'fame': 150},
        'rumors': ['틈 너머 바다를 끝까지 지켜 낸 장군이 있다더군.',
                   '그분은 물 위에서 지는 법이 없었대. 수군을 아끼는 사람에게 오실 거야.']},
    'musashi': {'name': '두 자루의 검', 'grants': ['musashi'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'duel', 'n': 5, 'text': '일기토 다섯 번 이기기(여러 날 합산)'}],
        'attempt': {'fame': 120},
        'rumors': ['두 자루 칼을 쓰는 검객이 맞수를 찾는다더군.']},
    'yoshitsune': {'name': '절벽의 기습', 'grants': ['yoshitsune'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'terrain_win', 'text': '기병 장수로 구릉·산지 도시를 차지'}],
        'attempt': {'fame': 120},
        'rumors': ['말을 몰아 절벽을 내달린 무장 이야기를 들었나?']},
    'kenshin': {'name': '숙명의 맞수(겐신)', 'grants': ['kenshin'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'wins', 'n': 10, 'text': '출정에서 열 번 이기기(여러 날 합산)'}],
        'attempt': {'fame': 120},
        'rumors': ['군신이라 불린 무장이 강한 사람을 찾고 있대.']},
    'shingen': {'name': '숙명의 맞수(신겐)', 'grants': ['shingen'], 'kind': 'giyeon', 'steps': [
        {'kind': 'after', 'series': 'kenshin', 'text': '겐신을 먼저 영입'},
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'destroy', 'n': 2, 'text': '한 판에서 군벌 둘을 멸망시키기'}],
        'attempt': {'fame': 120},
        'rumors': ['군신의 맞수였던 무장이 그의 소식을 기다린대.']},
    'yukimura': {'name': '최후의 돌격', 'grants': ['yukimura'], 'kind': 'giyeon', 'steps': [
        {'kind': 'event', 'event': 'rift', 'text': '시공의 틈을 지나기'},
        {'kind': 'beat_strongest', 'text': '그날 가장 강한 군벌의 성을 차지'}],
        'attempt': {'fame': 120},
        'rumors': ['가장 강한 적에게 마지막까지 돌격한 무장이 있었다지.']},
}
SPACE_SERIES = frozenset(k for k, v in SERIES.items() if v['steps'] and any(s.get('event') == 'rift' for s in v['steps']))
COUNTER_KINDS = frozenset({'duel', 'naval', 'underdog', 'defend_days', 'scheme_days', 'develop_days', 'wins', 'destroy',
                           'four_dirs', 'counter', 'terrain_win', 'beat_strongest', 'no_attack_with'})


def series_of_event(event: str) -> list:
    return [k for k, v in SERIES.items() if any(s.get('event') == event for s in v['steps'])]


# ── 판 이벤트 배치(samguk_board 가 부른다) ──────────────────────────────────
def board_events(day: date, board: dict) -> list:
    """그날 판에 뜨는 전설 이벤트. 모두에게 같다. [{'event', 'city'}]"""
    idx = (day - date(2026, 11, 16)).days
    out, used = [], set()
    for code, (_name, _vague, cities, every, need_event) in EVENTS.items():
        if need_event and board.get('event') != need_event:
            continue
        offset = int(hashlib.sha256(f'sg-ev:{code}'.encode()).hexdigest(), 16) % every
        if (idx - offset) % every:
            continue
        pool = [c for c in (cities or sorted(board['cities'])) if c in board['cities'] and c not in used]
        if not pool:
            continue
        pick = pool[int(hashlib.sha256(f'sg-ev:{code}:{day.isoformat()}'.encode()).hexdigest(), 16) % len(pool)]
        used.add(pick)
        out.append({'event': code, 'city': pick})
    return out


# ── 진행 판정 ────────────────────────────────────────────────────────────
def _row(user, series: str):
    from .models import SamgukLegend
    return SamgukLegend.objects.get_or_create(user=user, series=series)[0]


def _prophecy(user) -> str:
    cities = [c.code for c in D.CITIES]
    return cities[int(hashlib.sha256(f'sg-guanlu:{user.pk}'.encode()).hexdigest(), 16) % len(cities)]


def current_step(row) -> dict | None:
    steps = SERIES[row.series]['steps']
    return steps[row.step] if row.step < len(steps) else None


def cond_ok(cond: dict | None, g: D.General) -> bool:
    if not cond:
        return True
    if 'skill' in cond and g.skill != cond['skill']:
        return False
    if 'stat' in cond and getattr(g, cond['stat']) < cond['min']:
        return False
    return True


def check_event_action(user, run, action: dict) -> None:
    """legend 행동을 받기 전에(군령을 쓰기 전에) 그 사람의 지금 단계로 검사한다."""
    from . import samguk as S
    series = action.get('series')
    if series not in SERIES:
        raise S.GameError('알 수 없는 전설이에요.')
    row = _row(user, series)
    if row.completed_at:
        raise S.GameError('이미 마친 전설이에요.')
    step = current_step(row)
    if not step or step['kind'] != 'event':
        raise S.GameError('이 전설은 지금 다른 조건을 기다리고 있어요.')
    today = run.day.date.isoformat()
    if row.progress.get('last_event_day') == today:
        raise S.GameError('이 전설은 하루에 한 걸음씩만 나아가요. 내일 다시 찾아오세요.')
    board_ev = [e for e in run.day.board.get('legends', []) if e['event'] == step['event']]
    if not any(e['city'] == action.get('city') for e in board_ev):
        raise S.GameError('오늘 그 도시에는 이 전설의 흔적이 없어요.')
    by = action.get('by')
    if by not in D.GENERAL or not cond_ok(step.get('cond'), D.GENERAL[by]):
        raise S.GameError(f'조건에 맞는 장수가 필요해요: {step["text"]}')
    if step.get('own') and run.state['cities'][action['city']]['owner'] != 'me':
        raise S.GameError('그 도시를 먼저 차지해야 해요.')


def _advance(row, today: str, note: str | None = None) -> bool:
    row.step += 1
    row.progress = {k: v for k, v in row.progress.items() if k in ('last_event_day', 'days_done')}
    if row.step >= len(SERIES[row.series]['steps']):
        row.completed_at = date.fromisoformat(today)
    row.save()
    return True


def _state_step_done(user, row, step: dict, run) -> bool:
    """판 상태만 보고 알 수 있는 단계(즉시 판정)."""
    from .models import SamgukCodex
    kind = step['kind']
    st = run.state if run else None
    if kind == 'manor':
        from . import samguk as S
        from . import samguk_manor as M
        return M.manor_state(S.member(user))['buildings'][step['building']] >= step['level']
    if kind == 'rumor':
        from .models import SamgukRumor
        return SamgukRumor.objects.filter(user=user, series=row.series).count() >= step['n']
    if kind == 'after':
        other = _row(user, step['series'])
        return bool(other.recruited_at)
    if kind == 'progress_of':
        return _row(user, step['series']).step >= step['step']
    if st is None:
        return False
    if kind == 'recruit':
        return any(c in st['recruited'] for c in step['codes'])
    if kind == 'recruit_all':
        got = set(SamgukCodex.objects.filter(user=user, general__in=step['codes'], first_recruited__isnull=False)
                  .values_list('general', flat=True))
        return set(step['codes']) <= (got | set(st['recruited']))
    if kind == 'hold':
        city = _prophecy(user) if step['city'] == '@prophecy' else step['city']
        return st['cities'].get(city, {}).get('owner') == 'me'
    if kind == 'win_with':
        return any(a.result.get('kind') == 'attack' and a.result.get('win') and step['code'] in a.result.get('officers', [])
                   for a in run.actions.all())
    return False


def _day_counts(run, step: dict) -> int:
    """누적 단계 — 그날 판 기록으로 센다(판이 닫힐 때 한 번)."""
    kind = step['kind']
    results = [a.result for a in run.actions.all()]
    attacks = [r for r in results if r.get('kind') == 'attack']
    wins = [r for r in attacks if r.get('win')]
    npc = [e for r in results for e in r.get('npc', []) if e.get('defender') == 'me']
    st = run.state
    if kind == 'duel':
        return sum(1 for r in attacks if r.get('duel') and r['duel']['winner'] in r.get('officers', []))
    if kind == 'naval':
        return sum(1 for r in wins if D.CITY[r['to']].terrain == 'water'
                   and any(D.GENERAL[o].skill == 'navy' for o in r.get('officers', [])))
    if kind == 'underdog':
        return sum(1 for r in wins if r.get('def_troops', 0) >= r.get('troops', 0) * step['ratio'])
    if kind == 'defend_days':
        return 1 if any(not e.get('win') for e in npc) else 0
    if kind == 'scheme_days':
        if step.get('city') and st['cities'].get(step['city'], {}).get('owner') != 'me':
            return 0
        return 1 if any(r.get('kind') == 'scheme' and r.get('ok') for r in results) else 0
    if kind == 'develop_days':
        return 1 if sum(1 for r in results if r.get('kind') == 'develop') >= step.get('per', 1) else 0
    if kind == 'wins':
        return len(wins)
    if kind == 'destroy':
        return 1 if len(st.get('destroyed', [])) >= step['n'] else 0
    if kind == 'four_dirs':
        sx, sy = D.CITY[st['start']].x, D.CITY[st['start']].y
        owned = [D.CITY[c] for c, v in st['cities'].items() if v['owner'] == 'me']
        dirs = (any(c.x < sx - 80 for c in owned), any(c.x > sx + 80 for c in owned),
                any(c.y < sy - 80 for c in owned), any(c.y > sy + 80 for c in owned))
        return 1 if all(dirs) else 0
    if kind == 'counter':
        repelled = [i for i, r in enumerate(results) if any(e.get('defender') == 'me' and not e.get('win')
                                                            for e in r.get('npc', []))]
        return 1 if repelled and any(r.get('kind') == 'attack' and r.get('win') for r in results[repelled[0] + 1:]) else 0
    if kind == 'terrain_win':
        return 1 if any(D.CITY[r['to']].terrain in ('hill', 'mountain')
                        and any(D.GENERAL[o].skill == 'cavalry' for o in r.get('officers', [])) for r in wins) else 0
    if kind == 'beat_strongest':
        board = run.day.board
        totals = {}
        for c, v in board['cities'].items():
            if v['owner'] in board['lords']:
                totals[v['owner']] = totals.get(v['owner'], 0) + v['troops']
        if not totals:
            return 0
        strongest = max(totals, key=lambda k: (totals[k], k))
        return 1 if any(r.get('defender') == strongest for r in wins) else 0
    if kind == 'no_attack_with':
        code = step['code']
        if code not in st['recruited']:
            return 0
        return 0 if any(code in r.get('officers', []) for r in attacks) else 1
    return 0


def _needs_count(step: dict) -> int:
    if step['kind'] in ('destroy', 'four_dirs', 'counter', 'terrain_win', 'beat_strongest', 'no_attack_with'):
        return 1
    return step.get('n', 1)


def after_action(user, run, result: dict) -> list:
    """행동 하나 뒤 — 이벤트 단계와 즉시 판정 단계를 넘긴다. 넘어간 시리즈 이름 목록."""
    today = run.day.date.isoformat()
    moved = []
    with transaction.atomic():
        if result.get('kind') == 'legend':
            row = _row(user, result['series'])
            step = current_step(row)
            if step and step['kind'] == 'event':
                times = step.get('times', 1)
                row.progress['last_event_day'] = today
                row.progress['count'] = row.progress.get('count', 0) + 1
                if row.progress['count'] >= times:
                    _advance(row, today)
                else:
                    row.save()
                moved.append(result['series'])
        moved += _sweep_state(user, run, today)
    return moved


def _sweep_state(user, run, today: str) -> list:
    from .models import SamgukLegend
    moved = []
    for series in SERIES:
        row = SamgukLegend.objects.filter(user=user, series=series).first()
        if row is None:
            if SERIES[series]['steps'][0]['kind'] in ('event',) or not _started_ok(user, series):
                continue
            row = _row(user, series)
        for _ in range(len(SERIES[series]['steps'])):
            step = current_step(row)
            if not step or step['kind'] == 'event' or step['kind'] in COUNTER_KINDS:
                break
            if not _state_step_done(user, row, step, run):
                break
            _advance(row, today)
            moved.append(series)
    return moved


def _started_ok(user, series: str) -> bool:
    """첫 단계가 이벤트가 아닌 시리즈(after·progress_of·rumor 등)는 조건이 처음 맞을 때 줄을 만든다."""
    first = SERIES[series]['steps'][0]
    if first['kind'] in COUNTER_KINDS:
        return True
    if first['kind'] in ('manor', 'rumor', 'after', 'progress_of'):
        from types import SimpleNamespace
        return _state_step_done(user, SimpleNamespace(series=series), first, None)
    return True


def on_close(user, run) -> list:
    """판이 닫힐 때 — 누적 단계를 그날 기록으로 센다."""
    today = run.day.date.isoformat()
    moved = []
    from .models import SamgukLegend
    with transaction.atomic():
        for series, spec in SERIES.items():
            row = SamgukLegend.objects.filter(user=user, series=series).first()
            first = spec['steps'][0]
            if row is None and first['kind'] not in COUNTER_KINDS:
                continue
            row = row or _row(user, series)
            step = current_step(row)
            if not step or step['kind'] not in COUNTER_KINDS:
                continue
            if today in row.progress.get('closed', []):
                continue
            got = _day_counts(run, step)
            row.progress.setdefault('closed', []).append(today)
            row.progress['closed'] = row.progress['closed'][-30:]
            row.progress['count'] = row.progress.get('count', 0) + got
            if row.progress['count'] >= _needs_count(step):
                _advance(row, today)
                moved.append(series)
            else:
                row.save()
        moved += _sweep_state(user, run, today)
    return moved


# ── 영입 시도(PC 장원 화면) ────────────────────────────────────────────────
def attempt(user, series: str) -> dict:
    from . import samguk as S
    from .models import SamgukCodex
    if series not in SERIES:
        raise S.GameError('알 수 없는 전설이에요.')
    spec = SERIES[series]
    with transaction.atomic():
        row = _row(user, series)
        if row.recruited_at:
            raise S.GameError('이미 영입했어요.')
        if not row.completed_at:
            step = current_step(row)
            raise S.GameError(f'아직 단계가 남았어요: {step["text"] if step else ""}')
        m = S.member(user)
        need = spec.get('attempt', {}).get('fame', 0)
        if m.fame < need:
            raise S.GameError(f'영입하려면 명성이 {need} 있어야 해요(지금 {m.fame}). 실패해도 진행은 남아요.')
        today = S.game_day()
        for code in spec['grants']:
            c, _ = SamgukCodex.objects.get_or_create(user=user, general=code, defaults={'first_seen': today})
            c.first_recruited = c.first_recruited or today
            c.times_recruited += 1
            c.save(update_fields=['first_recruited', 'times_recruited'])
        row.recruited_at = today
        row.save(update_fields=['recruited_at', 'updated_at'])
    names = '·'.join(HIDDEN[c].name for c in spec['grants'])
    return {'text': f'{spec["name"]}을(를) 마치고 {names}을(를) 영입했어요.'}


# ── 소문 ───────────────────────────────────────────────────────────────
def rumor_for(user, source: str = 'beggar') -> str | None:
    """아직 마치지 않은 시리즈 가운데, 다음 소문이 남은 것 하나를 들려주고 기록한다. 없으면 None."""
    from . import samguk as S
    from .models import SamgukLegend, SamgukRumor
    done = set(SamgukLegend.objects.filter(user=user, recruited_at__isnull=False).values_list('series', flat=True))
    heard: dict = {}
    for series, level in SamgukRumor.objects.filter(user=user).values_list('series', 'level'):
        heard[series] = max(heard.get(series, 0), level)
    order = sorted(SERIES, key=lambda k: (heard.get(k, 0), int(hashlib.sha256(f'{k}:{user.pk}'.encode()).hexdigest(), 16)))
    for series in order:
        if series in done:
            continue
        lines = SERIES[series]['rumors']
        level = heard.get(series, 0) + 1
        if level > len(lines):
            continue
        text = lines[level - 1]
        if series == 'guanlu' and level == len(lines):
            text = f'{text} 술사가 중얼거린 도시는 {D.CITY[_prophecy(user)].name}이래.'
        SamgukRumor.objects.get_or_create(user=user, series=series, level=level,
                                          defaults={'text': text[:200], 'source': source, 'heard_on': S.game_day()})
        return text
    return None


def known(user) -> set:
    from .models import SamgukRumor
    return set(SamgukRumor.objects.filter(user=user).values_list('series', flat=True))


# ── 화면 묶음 ────────────────────────────────────────────────────────────
def board_legends(user, run) -> list:
    """판 화면에 보일 전설 이벤트 — 소문을 들었으면 정체와 지금 단계, 아니면 흐릿하게."""
    if run is None:
        return []
    have = known(user)
    out = []
    for ev in run.day.board.get('legends', []):
        name, vague, *_ = EVENTS[ev['event']]
        series_here = series_of_event(ev['event'])
        cand = []
        for s in series_here:
            row = _row(user, s) if s in have else None
            step = current_step(row) if row else None
            if row and not row.completed_at and step and step['kind'] == 'event' and step['event'] == ev['event']:
                cand.append({'series': s, 'name': SERIES[s]['name'], 'step': step['text'], 'cond': step.get('cond'),
                             'count': row.progress.get('count', 0), 'times': step.get('times', 1)})
        clear = any(s in have for s in series_here)
        out.append({'event': ev['event'], 'city': ev['city'], 'city_name': D.CITY[ev['city']].name,
                    'title': name if clear else '???', 'text': vague, 'series': cand,
                    'open_series': [s for s in series_here if s not in have][:3] if not clear else []})
    return out


def legends_view(user) -> list:
    from .models import SamgukLegend
    rows = {r.series: r for r in SamgukLegend.objects.filter(user=user)}
    have = known(user)
    out = []
    for series, spec in SERIES.items():
        row = rows.get(series)
        if row is None and series not in have:
            continue
        step = current_step(row) if row else spec['steps'][0]
        out.append({'series': series, 'name': spec['name'], 'kind': HIDDEN_GROUPS[spec['kind']],
                    'step_no': row.step if row else 0, 'steps': len(spec['steps']),
                    'now': step['text'] if step else '모든 단계를 마쳤어요', 'count': (row.progress.get('count', 0) if row else 0),
                    'completed': bool(row and row.completed_at), 'recruited': bool(row and row.recruited_at),
                    'fame': spec.get('attempt', {}).get('fame', 0),
                    'grants': [HIDDEN[c].name for c in spec['grants']]})
    return out
