"""판 나란히 비교 — 재작성본이 앞선 판보다 정말 나은지 순서를 바꿔 두 번 물어요. (2026-11-23)

왜: 100점 점수는 같은 원고도 회차마다 ±5점씩 흔들려요(원고 #8: 78→75). 점수만 보고 '내려가지 않았으면 채택'하면
초안보다 나빠진 판이 이어지고, 점수가 조금 오른 판이 실제로는 초안의 좋은 대목을 잃었을 수 있어요.
LLM 심사는 점수보다 두 판의 직접 비교에 강하지만 먼저 보여 준 쪽을 고르는 순서 편향이 있어요
(Judging the Judges, arXiv 2406.07791). 그래서 A·B 순서를 바꿔 두 번 묻고, 두 번 같은 판을 고를 때만 판정으로 써요.
엇갈리면 '동률'로 보고 기존 점수 규칙에 맡겨요.
"""
from __future__ import annotations

PAIR_PROMPT = (
    '같은 주제를 다룬 칼럼 원고 두 판을 비교합니다. 편집장으로서 독자에게 더 나은 판을 고르세요.\n\n'
    '기준(중요한 순서): 1) 사실·근거가 정확하고 출처가 분명한가 2) 독자의 질문에 답하는 깊이와 구체성 '
    '3) 도입·흐름·문장이 읽히는가 4) 한쪽에만 있는 좋은 대목이 있는가.\n'
    '분량이 길다는 이유만으로 고르지 마세요. 차이가 미미하거나 판단할 수 없으면 "same" 입니다.\n\n'
    '[원고 1]\nTITLE: {s1}\n{c1}\n\n[원고 2]\nTITLE: {s2}\n{c2}\n\n'
    '출력 JSON: {{"better": "1" 또는 "2" 또는 "same", "reason": "판정 이유 한두 문장", '
    '"only_in_1": ["원고 1에만 있는 좋은 대목(본문 인용)"], "only_in_2": ["원고 2에만 있는 좋은 대목(본문 인용)"]}}'
)


def _verdict(raw) -> str:
    value = str((raw or {}).get('better', '')).strip().lower() if isinstance(raw, dict) else ''
    return value if value in ('1', '2') else 'same'


def compare(a: tuple, b: tuple, *, ask_json=None, agent: str = 'editor') -> dict:
    """a·b = (제목, 본문). 반환: winner 'a'|'b'|'tie', consistent(두 순서 판정 일치), runs.

    ask_json 이 실패하면 예외를 그대로 올려요 — 비교를 못 했는데 '동률'로 꾸미지 않아요(호출부가 기록하고 건너뛰어요)."""
    from common.services.claude import call_tags
    from .pipeline import strip_visual_block
    if ask_json is None:
        from .services import ask_agent_json as ask_json
    runs, votes = [], []
    for order, (first, second) in (('ab', (a, b)), ('ba', (b, a))):
        with call_tags(stage='pairwise', order=order):
            raw = ask_json(agent, PAIR_PROMPT.format(s1=first[0], c1=strip_visual_block(first[1]),
                                                     s2=second[0], c2=strip_visual_block(second[1])),
                           max_tokens=1500)
        pick = _verdict(raw)
        vote = 'tie' if pick == 'same' else (('a' if pick == '1' else 'b') if order == 'ab' else ('b' if pick == '1' else 'a'))
        votes.append(vote)
        runs.append({'order': order, 'better': pick, 'vote': vote,
                     'reason': str((raw or {}).get('reason', ''))[:300] if isinstance(raw, dict) else ''})
    consistent = votes[0] == votes[1]
    winner = votes[0] if consistent else 'tie'
    return {'winner': winner, 'consistent': consistent, 'runs': runs}


def enabled() -> bool:
    from . import switches as SW
    return bool(SW.get('pairwise_guard'))
