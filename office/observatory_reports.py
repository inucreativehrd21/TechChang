"""저장된 결과를 관리자용 보고로 정리해요. AI 호출이나 원고·심사 판정 변경은 하지 않아요."""
import json
import re

# 폴링은 최근 담당자별 판정에 필요한 키만 읽고 본문·프롬프트·실행 메타데이터는 읽지 않아요.
OUTCOME_KEYS = ('verdict', 'score', 'status', 'fatal', 'must_fix', 'open_issues', 'resolved',
                'unresolved_issue_ids', 'critical', 'duplicate', 'claims', 'verified', 'items',
                'reasons', 'issues', 'remaining', 'ok')
STATUS_LABELS = {'verified': '확인됨', 'wrong': '사실 오류', 'unverifiable': '근거 미확인',
                 'outdated': '최신성 문제', 'met': '반영 확인', 'unmet': '미반영',
                 'pass': '통과', 'accept': '통과', 'minor': '수정 필요', 'major': '보류',
                 'revise': '보완 의견', 'adopted': '수정본 반영', 'retained': '기존 원고 유지'}
SCORE_LABELS = {'structure': '구성', 'depth': '심층성·독창성', 'evidence': '근거',
                'logic': '논리·정확성', 'readability': '가독성·문체', 'visual': '시각 자료'}
FATAL_LABELS = {'unverified_data': '확인되지 않은 근거', 'duplicate': '기존 글과 중복',
                'too_short': '본문 분량 부족', 'style_broken': '문체·형식 문제',
                'overclaim': '근거보다 강한 단정', 'unsupported': '주장의 근거 부족'}
FIELDS = [('where', '위치'), ('problem', '문제'), ('request', '수정 요청'), ('fix', '할 일'),
          ('done_when', '완료 기준'), ('evidence', '확인 근거'), ('quote', '본문 근거'),
          ('reason', '판단 이유'), ('note', '설명'), ('description', '내용'), ('url', '출처')]


def text(value, limit=1800):
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        value = str(value).strip()
        return value[:limit] + ('… (전체 내용은 원 데이터에서 확인해요.)' if len(value) > limit else '')
    return ''


def rows(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return [value] if value else []


def outcome(stage, data, execution='done', *, canonical=True):
    data = data if isinstance(data, dict) else {}
    def result(state, label, explanation):
        return {'state': state, 'label': label, 'explanation': explanation}
    if execution in ('failed', 'interrupted') or stage == 'fail':
        return result('blocked', '실행 실패', '작업을 완료하지 못했어요. 중단 사유를 확인해 주세요.')
    if execution == 'running':
        return result('running', '진행 중', '담당자가 작업 중이에요. 확정된 결과는 아직 없어요.')
    if execution in ('unknown', 'quarantined'):
        return result('unknown', '상태 확인 필요', '실행 종료를 확인할 수 없어 통과 여부를 표시하지 않아요.')
    if execution == 'skipped':
        return result('waiting', '건너뜀', '이 단계는 실행하지 않았어요.')
    if not canonical:
        return result('completed', '응답 수신', 'AI 응답을 받았어요. 저장된 검증·심사 판정과는 별개예요.')
    verdict = data.get('verdict')
    if stage in ('check', 'recheck', 'reverify', 'verify'):
        if 'claims' in data and not isinstance(data['claims'], list):
            return result('unknown', '검증 자료 확인 필요', '주장별 검증 기록의 형식이 올바르지 않아 통과로 표시하지 않아요.')
        bad = [c for c in rows(data.get('claims')) if isinstance(c, dict)
               and c.get('status') in ('wrong', 'unverifiable', 'outdated')]
        if bad or data.get('critical') or data.get('duplicate') or verdict in ('fail', 'revise', 'reject'):
            return result('blocked', '사실 검증 미통과',
                          f'확인이 필요한 주장 {len(bad)}건이 있어요.' if bad else '중요 오류·중복 또는 미통과 판정을 확인해 주세요.')
        if verdict == 'pass':
            return result('passed', '사실 검증 통과', '이 단계의 저장된 사실 검증을 통과했어요. 편집 심사·운영자 승인은 별도예요.')
    if stage in ('review', 'final'):
        pending = (data.get('fatal') or data.get('must_fix') or data.get('open_issues')
                   or data.get('unresolved_issue_ids') or any(v is False for v in rows(data.get('resolved'))))
        if pending or verdict in ('minor', 'major', 'reject', 'revise', 'fail'):
            return result('blocked', '편집 심사 미통과', '필수 수정·미해결 지적 또는 보류 판정이 남아 있어요. 점수만으로 통과하지 않아요.')
        if verdict == 'accept':
            return result('passed', '편집 심사 통과', '저장된 편집 심사를 통과했어요. 공개하려면 현재 원고의 운영자 승인이 필요해요.')
    if stage == 'critique':
        if verdict in ('revise', 'reject', 'minor', 'major'):
            return result('attention', '평론 보완 의견', '독자 관점의 보완 의견이 있어요. 최종 편집 심사와는 별도 판정이에요.')
        if verdict in ('pass', 'accept'):
            return result('passed', '평론 통과', '저장된 독자 관점 평론에서 통과 의견을 받았어요.')
    if stage == 'revision_decision':
        if data.get('status') == 'retained':
            return result('blocked', '수정본 미채택', '수정 요구·검증·점수 조건을 충족하지 못해 기존 원고를 유지했어요.')
        if data.get('status') == 'adopted':
            return result('passed', '수정본 반영', '수정 요청 이행과 품질 조건을 확인하고 수정본을 반영했어요.')
    if stage == 'revision_verify':
        items = [r for r in rows(data.get('items')) if isinstance(r, dict)]
        if data.get('reasons') or any(r.get('met') is False for r in items):
            return result('blocked', '수정 요청 미반영', '완료되지 않았거나 근거가 확인되지 않은 수정 요청이 있어요.')
        if data.get('verified') is True and items and all(r.get('met') is True for r in items):
            return result('passed', '수정 요청 반영 확인', '요청별 반영 근거를 확인했어요. 최종 품질 심사는 별도예요.')
        return result('waiting', '수정 요청 확인 중', '확정되지 않은 항목이 있어 전체 반영 완료로 표시하지 않아요.')
    if stage == 'precheck':
        if data.get('issues'):
            return result('blocked', '자동 점검 미통과', '자동 점검에서 수정할 항목이 발견됐어요.')
        if isinstance(data.get('issues'), list):
            return result('passed', '자동 점검 통과', '이 자동 점검에서 지적된 항목이 없어요. 사실 검증·편집 심사는 별도예요.')
    if data.get('ok') is False:
        return result('blocked', '작업 결과 확인 필요', '결과 기록에 실패 또는 미완료가 표시돼 있어요.')
    return result('completed', '작업 완료 · 판정 없음', '산출물 기록은 있지만 이 기록만으로 검수 통과를 확정하지 않아요.')


def _item(value, number):
    if not isinstance(value, dict):
        return {'title': '', 'body': text(value), 'fields': []}
    title = text(value.get('claim') or value.get('title') or value.get('request') or value.get('problem') or value.get('label'), 500)
    fields = [{'label': label, 'text': text(value.get(key))} for key, label in FIELDS
              if text(value.get(key)) and text(value.get(key), 500) != title]
    status = value.get('status_label') or STATUS_LABELS.get(text(value.get('status')), '')
    if 'met' in value:
        status = '반영 확인' if value['met'] is True else '미반영' if value['met'] is False else '확인 대기'
    elif isinstance(value.get('resolved'), bool):
        status = '해결 확인' if value['resolved'] else '미해결'
    if status:
        fields.insert(0, {'label': '판정', 'text': text(status)})
    if not fields and not title:
        for key in ('summary', 'text', 'result', 'value', 'content'):
            if text(value.get(key)):
                fields.append({'label': '내용', 'text': text(value[key])})
    return {'title': title or f'항목 {number}', 'body': '', 'fields': fields}


def parse_response(value):
    if not isinstance(value, str):
        return value
    candidate = value.strip()
    if candidate.startswith('```') and candidate.endswith('```'):
        candidate = re.sub(r'^```(?:json)?\s*', '', candidate, count=1)[:-3].strip()
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        return value


def report(stage, value, execution='done', *, canonical=True, error=''):
    value = parse_response(value)
    data = value if isinstance(value, dict) else {}
    decision = outcome(stage, data, execution, canonical=canonical)
    sections, metrics = [], []
    def section(title, values):
        values = rows(values)
        if not values:
            return
        items = [_item(v, i+1) for i, v in enumerate(values[:30])]
        items = [v for v in items if v['title'] or v['body'] or v['fields']]
        if items:
            sections.append({'title': title, 'items': items, 'omitted': max(0, len(values)-30)})
    if error:
        section('중단 사유', error)
    for key, label in (('score', '편집 점수'), ('previous_score', '기존 점수'), ('candidate_score', '수정본 점수')):
        if isinstance(data.get(key), (int, float)) and not isinstance(data[key], bool):
            metrics.append({'label': label, 'value': f'{data[key]}점'})
    bad_claims = [c for c in rows(data.get('claims')) if isinstance(c, dict)
                  and c.get('status') in ('wrong', 'unverifiable', 'outdated')]
    if 'claims' in data:
        metrics.extend([{'label': '검증한 주장', 'value': f'{len(rows(data["claims"]))}건'},
                        {'label': '확인 필요', 'value': f'{len(bad_claims)}건'}])
    if 'items' in data:
        items = [v for v in rows(data['items']) if isinstance(v, dict)]
        metrics.extend([{'label': '반영 확인', 'value': f'{sum(v.get("met") is True for v in items)}건'},
                        {'label': '미반영·대기', 'value': f'{sum(v.get("met") is not True for v in items)}건'}])
    section('핵심 판단', data.get('notes') or data.get('summary') or data.get('reason') or data.get('why'))
    section('잘된 점', data.get('strengths'))
    section('미통과·보류 사유', data.get('reasons'))
    section('필수 수정과 완료 기준', data.get('must_fix'))
    section('미해결 지적', data.get('open_issues'))
    section('확인이 필요한 사실', bad_claims)
    section('요청별 반영 결과' if stage != 'revision_candidate' else '반영할 요청', data.get('items') or data.get('requirements'))
    section('점검·평론 지적', data.get('issues') or data.get('remaining'))
    flaws = data.get('fatal') or data.get('critical')
    section('중요 결함', [FATAL_LABELS.get(v, v) if isinstance(v, str) else
                         '중요 오류 표시가 있어요. 사실 검증 내용을 확인해 주세요.' if v is True else v for v in rows(flaws)])
    nested_review = data.get('review') if isinstance(data.get('review'), dict) else {}
    nested_check = data.get('check') if isinstance(data.get('check'), dict) else {}
    section('수정본 편집 심사 의견', nested_review.get('notes'))
    section('수정본의 남은 필수 수정', nested_review.get('must_fix'))
    section('수정본 사실 검증 문제', [c for c in rows(nested_check.get('claims')) if isinstance(c, dict)
                                    and c.get('status') in ('wrong', 'unverifiable', 'outdated')])
    section('추가 개선 제안', data.get('suggestions'))
    if isinstance(data.get('scores'), dict):
        section('항목별 편집 점수', [f'{label} {data["scores"][key]}/5'
                                 for key, label in SCORE_LABELS.items() if isinstance(data['scores'].get(key), (int, float))])
    section('검증한 사실', [c for c in rows(data.get('claims')) if c not in bad_claims])
    for key, label in (('subject', '원고 제목'), ('angle', '집필 방향'), ('outline', '내용 구성'),
                       ('questions', '답해야 할 질문'), ('data_needed', '찾아야 할 근거·지표'),
                       ('cases', '검토할 사례'), ('counterpoint', '반론과 한계'), ('avoid', '피해야 할 내용'),
                       ('findings', '조사 결과'), ('facts', '확인한 사실'), ('gaps', '남은 조사 과제'),
                       ('missing_requests', '누락된 수정 요청'),
                       ('changes', '수정 내용'), ('sources', '참고 근거'), ('note', '담당자 설명'),
                       ('report', '도판 점검'), ('tests', '확인 결과'), ('results', '작업 결과')):
        section(label, data.get(key))
    body = data.get('content') or data.get('text') or data.get('value')
    if isinstance(body, str) and body.strip():
        parts = re.split(r'(?m)^#{1,3}\s+', body)
        section('작성한 내용', [part.strip() for part in parts[:12] if part.strip()])
    if isinstance(value, list):
        section('작업 결과', value)
    elif isinstance(value, str) and value.strip():
        # JSON처럼 보이는 미완성 응답을 정리된 보고처럼 노출하지 않아요.
        if value.lstrip().startswith(('{', '[', '```json')):
            section('내용 확인', '구조화된 응답을 해석하지 못했어요. 원 데이터 보기에서 응답을 확인해 주세요.')
        else:
            section('담당자 보고', re.split(r'\n\s*\n', value.strip())[:12])
    if not sections:
        section('현재 상황', '아직 관리자 보고로 정리할 결과가 없어요. 진행 중이면 완료 후 다시 확인해 주세요.')
    next_action = {
        'running': '작업이 끝나면 결과와 판정이 자동으로 갱신돼요.',
        'blocked': '지적별 수정 방법과 완료 기준에 따라 보완한 뒤 재검증해 주세요.',
        'attention': '보완 의견을 확인하고 최종 편집 심사의 판단과 함께 검토해 주세요.',
        'passed': '이 단계의 결과를 다음 담당자의 검증·심사와 함께 확인해 주세요.',
        'unknown': '관리자 작업 로그에서 실제 실행 종료 여부를 확인해 주세요.',
        'waiting': '확정되지 않은 항목의 후속 검증 결과를 기다려 주세요.',
        'completed': '후속 검증·심사 판정을 확인해 주세요. 호출 완료만으로 통과한 것은 아니에요.',
    }[decision['state']]
    # 불필요한 메타데이터나 거대한 산출물이 보고를 밀어내지 않게 텍스트 예산을 둬요.
    budget, limited = 18000, False
    for group in sections:
        kept = []
        for item in group['items']:
            size = len(item['title']) + len(item['body']) + sum(len(f['text']) for f in item['fields'])
            if size > budget:
                group['omitted'] += 1; limited = True
                continue
            budget -= size; kept.append(item)
        group['items'] = kept
        group['collapsible'] = group['title'] in ('작성한 내용', '검증한 사실', '참고 근거')
    return {'outcome': decision, 'metrics': metrics, 'sections': sections, 'next_action': next_action, 'limited': limited}
