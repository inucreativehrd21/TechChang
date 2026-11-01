"""StageRun에서 첫 심사·재작업·보류·사용량을 재현 가능하게 집계한다."""
from collections import defaultdict
from statistics import median
from .review_protocol import publishable


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row['run_id'])].append(row)
    runs = []
    for run_id, stages in groups.items():
        stages.sort(key=lambda s: s['seq'])
        reviews = [s for s in stages if s['stage'] == 'review' and isinstance(s['output'], dict)]
        if not reviews:
            continue
        calls = [c for s in stages for c in (s.get('calls') or [])]
        first, last = reviews[0]['output'], reviews[-1]['output']
        runs.append({'run_id': run_id, 'first_pass': publishable(first), 'final_pass': publishable(last),
                     'reviews': len(reviews), 'first_score': first.get('score'), 'last_score': last.get('score'),
                     'model_calls': len(calls), 'model_seconds': round(sum(c.get('seconds') or 0 for c in calls), 2),
                     'models': sorted({str(c.get('model')) for c in calls if c.get('model')}),
                     'input_tokens': sum(c.get('input_tokens') or 0 for c in calls),
                     'output_tokens': sum(c.get('output_tokens') or 0 for c in calls),
                     'has_call_measurements': bool(calls)})
    n = len(runs)
    return {'sample_size': n, 'first_pass_count': sum(r['first_pass'] for r in runs),
            'first_pass_rate': sum(r['first_pass'] for r in runs)/n if n else None,
            'final_pass_count': sum(r['final_pass'] for r in runs),
            'median_reviews': median(r['reviews'] for r in runs) if n else None,
            'runs': runs,
            'limitations': ['모델 심사 기록의 지표이며 독립적인 사람 평가나 사실 오류율을 대신하지 않아요.',
                            '호출 기록이 없는 과거 실행의 모델 호출 수·토큰을 0비용으로 해석하지 않아요.']}
