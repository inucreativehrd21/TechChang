"""검증은 통과했지만 평론·편집 판정이 충돌할 때만 독립 모델이 한 번 중재한다."""
import json
from common.services.claude import call_tags
from .model_router import profile


def resolve(subject, content, qa, check, critique, *, ask_json, score):
    if profile() != 'b' or check.get('verdict') != 'pass' or score < 80:
        return critique
    if not critique or critique.get('verdict') != 'reject' or qa.get('fatal'):
        return critique
    prompt = (
        '독립 중재예요. 원문 사실 검증은 통과했지만 평론가는 reject, 편집장은 높은 점수를 줬어요. '
        '새 점수·새 수정 지시를 만들지 말고 평론의 거절 사유가 발행을 막을 정도로 타당한지만 판단해요. '
        '취향 차이와 논리·독자 효용의 결함을 구분하세요. 원고 문장을 그대로 인용해야 해요. '
        'JSON: {"uphold": true/false, "quote": "원고에 실제로 있는 문장", "reason": "판정 이유"}\n'
        f'제목: {subject}\n[평론]\n{json.dumps(critique, ensure_ascii=False)}\n[원고]\n{content}')
    with call_tags(stage='adjudicate'):
        decision = ask_json('editor', prompt, max_tokens=2000)
    qa['adjudication'] = decision
    quote = str(decision.get('quote') or '').strip()
    # 인용이나 판정이 누락되면 기존 차단을 유지한다. 독립 사실 검증 결함은 중재하지 않는다.
    if decision.get('uphold') is False and len(quote) >= 8 and quote in content and decision.get('reason'):
        return {**critique, 'verdict': 'revise', 'adjudicated': True}
    return critique
