"""StageRun에서 첫 심사·재작업·보류·사용량을 재현 가능하게 집계한다."""
from collections import defaultdict
from statistics import median
from .review_protocol import publishable


def measured_sum(calls, *names):
    values = [next((c.get(name) for name in names if isinstance(c.get(name), int)), None) for c in calls]
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row['run_id'])].append(row)
    runs = []
    for run_id, stages in groups.items():
        stages.sort(key=lambda s: s['seq'])
        reviews = [s for s in stages if s['stage'] == 'review' and isinstance(s['output'], dict)]
        decisions = [s for s in stages if s['stage'] == 'revision_decision' and isinstance(s.get('output'), dict)]
        retained = any(s['output'].get('status') == 'retained' for s in decisions)
        if not reviews:
            reviews = [{**s, 'output': s['output']['review']} for s in decisions
                       if isinstance(s['output'].get('review'), dict)]
        checks = [s for s in stages if s['stage'] in ('check', 'recheck', 'reverify') and isinstance(s['output'], dict)]
        calls = [c for s in stages for c in (s.get('calls') or [])]
        first, last = (reviews[0]['output'], reviews[-1]['output']) if reviews else ({}, {})
        runs.append({'run_id': run_id, 'first_pass': publishable(first) and not retained,
                     'column_track': next((s['output']['execution'].get('column_track', '') for s in stages
                        if isinstance(s.get('output'), dict) and isinstance(s['output'].get('execution'), dict)), ''),
                     'final_pass': publishable(last) and not retained, 'revision_retained': retained,
                     'reached_review': bool(reviews),
                     'first_check_pass': checks[0]['output'].get('verdict') == 'pass' if checks else None,
                     'profile': next((s.get('output', {}).get('execution', {}).get('profile') for s in stages
                                      if isinstance(s.get('output'), dict) and s['output'].get('execution')), None),
                     'draft_status': stages[-1].get('draft__status'),
                     'failure_reasons': [s.get('error') for s in stages if s.get('error')],
                     'reviews': len(reviews), 'first_score': first.get('score'), 'last_score': last.get('score'),
                     'model_calls': len(calls), 'model_seconds': round(sum(c.get('seconds') or 0 for c in calls), 2),
                     'models': sorted({str(c.get('model')) for c in calls if c.get('model')}),
                     'input_tokens': measured_sum(calls, 'input_tokens'),
                     'cache_read_input_tokens': measured_sum(calls, 'cache_read_input_tokens', 'cached_input_tokens'),
                     'cache_creation_input_tokens': measured_sum(calls, 'cache_creation_input_tokens'),
                     'output_tokens': measured_sum(calls, 'output_tokens'),
                     'measured_usage_calls': sum(c.get('input_tokens') is not None and c.get('output_tokens') is not None for c in calls),
                     'has_call_measurements': bool(calls)})
    n = len(runs)
    return {'sample_size': n, 'first_pass_count': sum(r['first_pass'] for r in runs),
            'first_pass_rate': sum(r['first_pass'] for r in runs)/n if n else None,
            'final_pass_count': sum(r['final_pass'] for r in runs),
            'first_check_pass_rate': sum(r['first_check_pass'] is True for r in runs)/n if n else None,
            'median_reviews': median(r['reviews'] for r in runs) if n else None,
            'before_review_failures': sum(not r['reached_review'] for r in runs),
            'published_drafts': len({s.get('draft_id') for s in rows if s.get('draft_id')
                                     and s.get('draft__status') == 'published'}),
            'runs': runs,
            'limitations': ['모델 심사 기록의 지표이며 독립적인 사람 평가나 사실 오류율을 대신하지 않아요.',
                            '입력 토큰은 제공자 로그 기준이며 캐시·구독 한도 차감량과 같지 않아요.',
                            'Claude 캐시 토큰은 별도로 표시해요. Codex 캐시는 입력에 포함될 수 있으므로 입력에 다시 더하지 않아요.',
                            '호출 기록이 없는 과거 실행의 모델 호출 수·토큰을 0비용으로 해석하지 않아요.']}
