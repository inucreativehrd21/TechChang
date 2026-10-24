"""실데이터·발행 없이 비교하는 고정 입력. 자동 점검 통과가 편집 품질 동등성을 뜻하지는 않는다."""
import json
import re


def schema(properties):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties)}


TEXT = {'type': 'string'}
CASES = [
    {'id': 'meeting', 'agent': 'lead', 'prompt':
     '다음은 비공개 평가용 운영 지표예요. 방문은 전주 1,000회→이번 주 1,200회, 검색 CTR은 2.0%→1.5%예요. '
     '방문과 CTR을 구분해 250자 이상 브리핑하고 다음 조사 2가지를 제안해 주세요. 인과관계를 단정하지 마세요.',
     'min_chars': 250, 'contains': ['1,200', '1.5'], 'forbidden': ['CTR이 개선됐']},
    {'id': 'decision', 'agent': 'lead', 'prompt':
     '비공개 평가용 편집회의예요. 주제는 Django 조회 최적화이며 선택지는 N+1 측정과 캐시 도입이에요. '
     '측정이 선행되어야 하는 이유와 두 선택지를 JSON으로 정리해 주세요. summary와 options(문자열 배열)만 출력해 주세요.',
     'schema': schema({'summary': TEXT, 'options': {'type': 'array', 'items': TEXT}}),
     'json_keys': ['summary', 'options'], 'lengths': {'options': 2}, 'contains': ['N+1', '캐시']},
    {'id': 'outline', 'agent': 'coding', 'prompt':
     'Django N+1 문제를 다룰 칼럼의 집필 설계도를 400자 이상 써 주세요. '
     '왜 지금인가, 숫자로 보는 현황, 현장의 변화, 시사점, 맺음말, 참고 자료의 여섯 섹션을 넣고, '
     '아직 확보하지 않은 측정값은 미확인이라고 적어 주세요. 출처나 통계를 만들지 마세요.',
     'min_chars': 400, 'contains': ['왜 지금인가', '숫자로 보는 현황', '현장의 변화', '시사점', '맺음말', '참고 자료']},
    {'id': 'writing', 'agent': 'data', 'prompt':
     '비공개 평가용 글 일부를 800자 이상 써 주세요. 주제는 평균만 보고 지표를 판단할 때의 함정이에요. '
     '제공된 내부 실험 기록은 두 집단의 평균 처리 시간 12초와 18초뿐이에요. '
     '전체 분포·표본수·인과관계를 알 수 없음을 분명히 하고 해요체로 설명해 주세요. '
     '추가 숫자나 외부 출처를 지어내지 마세요. 제목, 해석, 한계, 다음 확인 순서로 작성해 주세요.',
     'min_chars': 800, 'contains': ['12', '18', '표본'], 'forbidden': ['통계청 조사에 따르면']},
    {'id': 'revision', 'agent': 'hrd', 'prompt':
     '다음 원고를 근거에 맞게 200자 이상 고쳐 주세요. 확인된 값은 교육 참여 200명→240명이에요. '
     '원고: 참여가 40% 늘어 교육이 생산성을 높였음이 입증됐다. '
     '증가율 계산을 바로잡고 생산성에 관한 인과 추론을 제거해 주세요. 해요체로 출력해 주세요.',
     'min_chars': 200, 'contains': ['20%'], 'manual_review': ['증가율 정정과 인과 추론 제거를 원문으로 확인해요.']},
    {'id': 'factcheck', 'agent': 'checker', 'prompt':
     '제공 자료의 10건→20건을 두고 원고가 증가율 200%라고 했어요. '
     '수치만 검증해 valid(false)와 correction(정정 이유) 두 필드를 가진 JSON으로 답해 주세요. 웹은 사용하지 마세요.',
     'schema': schema({'valid': {'type': 'boolean'}, 'correction': TEXT}),
     'json_keys': ['valid', 'correction'], 'equals': {'valid': False}, 'contains': ['100%']},
    {'id': 'critique', 'agent': 'critic', 'prompt':
     '두 서두를 비교해 250자 이상 평론해 주세요. A: AI는 미래를 바꿔요. 모두 준비해야 해요. '
     'B: 교육 보고서에 수료율만 남기면 현장에서 무엇을 적용했는지 놓쳐요. 이번 글은 현업 적용 확인 질문을 다뤄요. '
     '본문을 직접 인용하고 독자가 얻을 구체적 차이와 개선안을 설명해 주세요.',
     'min_chars': 250, 'contains': ['수료율', '현업']},
    {'id': 'visual', 'agent': 'charter', 'prompt':
     '제공된 비공개 평가 자료는 처리 시간 A 12초, B 18초 두 항목뿐이에요. '
     '두 항목은 그래프 대신 표로 보여 주는 규칙을 따라 mode와 caption을 JSON으로 출력해 주세요. '
     'mode는 table, caption에는 제공 수치만 써 주세요.',
     'schema': schema({'mode': {'type': 'string', 'enum': ['table']}, 'caption': TEXT}),
     'json_keys': ['mode', 'caption'], 'equals': {'mode': 'table'}, 'contains': ['12', '18']},
    {'id': 'review', 'agent': 'editor', 'prompt':
     '비공개 심사 규칙 검사예요. 모든 루브릭 항목이 4/5이고 가중치 합은 100이에요. '
     '점수를 계산하되 치명 결함 unverified_data가 있으므로 점수와 관계없이 major로 판정해 주세요. '
     'score(정수), verdict(문자열), reason(문자열)만 JSON으로 출력해 주세요.',
     'schema': schema({'score': {'type': 'integer'}, 'verdict': TEXT, 'reason': TEXT}),
     'json_keys': ['score', 'verdict', 'reason'], 'equals': {'score': 80, 'verdict': 'major'},
     'contains': ['unverified_data']},
    {'id': 'newsletter', 'agent': 'lead', 'prompt':
     '비공개 뉴스레터 초안 350자 이상을 써 주세요. 소개할 글은 수료율을 넘는 교육평가, Django N+1 측정 두 편이에요. '
     '각 글에서 독자가 얻을 점과 읽기 전 질문을 적어 주세요. 제작 고생담·내부 점수·심사 결과는 언급하지 마세요. 해요체로 써 주세요.',
     'min_chars': 350, 'contains': ['수료율', 'N+1'], 'forbidden': ['80점', '심사 통과', '제작 과정에서 고생']},
    {'id': 'logs', 'agent': 'coding', 'prompt':
     '비공개 SRE 평가예요. IP와 이메일이 제거된 로그는 nginx: open() /srv/app/static/main.css failed (13: Permission denied), '
     '응답은 403이에요. 원인을 단정하지 말고 권한 점검 순서와 최소 권한 복구안을 250자 이상 설명해 주세요. '
     'chmod 777이나 서비스를 무조건 재시작하는 처방은 하지 마세요.',
     'min_chars': 250, 'contains': ['권한'], 'manual_review': ['chmod 777을 권장하는지, 잘못된 방법으로 경고하는지 구분해요.']},
    {'id': 'web', 'agent': 'checker', 'prompt':
     'Django 5.2 공식 문서 https://docs.djangoproject.com/en/5.2/ref/models/querysets/ 를 실제로 열어 '
     'select_related와 prefetch_related가 관련 객체를 가져오는 방식의 차이를 확인해 주세요. '
     '확인한 공식 URL을 포함해 250자 이상 해요체로 설명하고 원문을 확인하지 못하면 그 사실을 밝혀 주세요.',
     'tools': ['WebSearch', 'WebFetch'], 'min_chars': 250,
     'contains': ['docs.djangoproject.com', 'select_related', 'prefetch_related']},
]


def check(case, text):
    issues = []
    if len(text) < case.get('min_chars', 1):
        issues.append('분량 미달')
    for value in case.get('contains', []):
        if value not in text:
            issues.append('필수 내용 누락: ' + value)
    for value in case.get('forbidden', []):
        if value in text:
            issues.append('금지 표현: ' + value)
    if case.get('json_keys'):
        try:
            # 운영 파서도 코드펜스를 제거한다. 원 응답 형식만으로 품질 차이를 부풀리지 않는다.
            cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.S)
            data = json.loads(cleaned)
        except ValueError:
            issues.append('유효한 JSON이 아니에요.')
        else:
            if not isinstance(data, dict) or set(data) != set(case['json_keys']):
                issues.append('JSON 필드 불일치')
            elif any(data.get(k) != v for k, v in case.get('equals', {}).items()):
                issues.append('기준 판정 불일치')
            elif any(not isinstance(data.get(k), list) or len(data[k]) != n
                     for k, n in case.get('lengths', {}).items()):
                issues.append('요청한 항목 수 불일치')
    return issues
