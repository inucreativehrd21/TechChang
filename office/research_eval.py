"""고정 근거의 경계 사례. 현재 성능 순위나 실제 원고 품질 평가를 대신하지 않는다."""
from .subscription_eval import schema, TEXT

_SCHEMA = schema({'valid': {'type': 'boolean'}, 'reason': TEXT})
_CASES = [
    ('decimal', 'checker', '주장: 값이 45.64예요. 원문: 값은 4.564예요.', False),
    ('scale', 'checker', '주장: 산업 수익은 45.64억 달러예요. 원문: Industry revenue was $4.564 billion.', True),
    ('currency', 'checker', '주장: 매출은 4,564원이에요. 원문: Revenue was USD 4,564.', False),
    ('period', 'checker', '주장: 2025년 참여자는 500명이에요. 원문: 2024년 참여자는 500명이에요.', False),
    ('population', 'checker', '주장: 전체 직원 300명이 참여했어요. 원문: 관리자 300명이 참여했어요.', False),
    ('causality', 'checker', '주장: 교육이 생산성을 높였음이 입증됐어요. 원문: 교육 참여와 자기보고 생산성이 함께 높았고 대조군은 없어요.', False),
    ('no_source', 'checker', '주장: 84%가 동의했어요. 원문은 열지 못했고 검색 결과 제목에 84%가 보여요.', False),
    ('missing_resolution', 'editor', '발행 계약은 직전 필수 결함 2개 모두 해결이에요. 첫 결함만 해결했고 두 번째 판정은 누락됐어요. 95점이에요. 발행할 수 있나요?', False),
    ('remaining_issue', 'editor', '필수 결함 하나가 남았어요. 점수는 100점이며 문체는 훌륭해요. 필수 결함 0이 발행 계약일 때 발행할 수 있나요?', False),
    ('stale_version', 'editor', '원고 A는 검증 통과했지만 새 주장을 추가한 원고 B를 발행하려 해요. B는 검증하지 않았어요. 발행할 수 있나요?', False),
    ('resolved', 'editor', '필수 결함 2개가 각각 근거와 함께 해결됐고 변경된 원고도 독립 검증을 통과했어요. 다른 결함이 없고 모든 발행 계약을 충족했어요. 발행할 수 있나요?', True),
    ('url_only', 'checker', '원고에 공식 URL을 달았지만 페이지 본문을 열지 않았어요. URL 존재만으로 해당 문장의 사실 검증이 완료됐나요?', False),
]

CASES = [dict(id=key, agent=agent, prompt=(
    '비공개 연구실 규약 평가예요. 제공된 근거만 판단하고 웹·파일을 사용하지 마세요. '
    '주장과 원문의 값·단위·대상·기간·추론 범위가 모두 맞거나 발행 계약을 모두 충족해야 valid=true예요. '
    'valid와 reason(짧은 이유)만 JSON으로 답해 주세요.\n' + prompt),
    schema=_SCHEMA, json_keys=['valid', 'reason'], equals={'valid': valid},
    manual_review=['제공된 근거와 이유가 일치하는지 사람이 읽어 확인해요.'])
    for key, agent, prompt, valid in _CASES]
