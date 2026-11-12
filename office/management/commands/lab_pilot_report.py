"""사람 평가가 채워진 실증 묶음만 전환 기준과 비교한다."""
import json
import math
from pathlib import Path
from statistics import median
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)

    def handle(self, *args, **opts):
        path = Path(opts['input'])
        try:
            rows = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError('사람 평가 JSON을 읽을 수 없어요.') from exc
        root = path.parent
        if root.name == 'blind':
            root = root.parent
            try:
                cases = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
                mapping = {case['blind_id']: case['id'] for case in cases}
                rows = [{**row, 'case_id': mapping[row['blind_id']]} for row in rows]
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise CommandError('블라인드 평가와 실증 목록이 일치하지 않아요.') from exc
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('case_id'), str) for r in rows):
            raise CommandError('사람 평가의 사례 목록 형식을 확인해 주세요.')
        groups = {p: [r for r in rows if r['case_id'].endswith('-'+p)] for p in ('a', 'b')}
        if len(groups['a']) != len(groups['b']) or len(groups['a']) not in (3, 6) or sum(map(len, groups.values())) != len(rows):
            raise CommandError('A/B 각각 3편 또는 반복 실증 6편의 사람 평가가 필요해요.')
        if len({r['case_id'] for r in rows}) != len(rows):
            raise CommandError('중복된 실증 사례가 있어요.')
        if {r['case_id'][:-2] for r in groups['a']} != {r['case_id'][:-2] for r in groups['b']}:
            raise CommandError('동일 기획의 A/B 평가 쌍이 필요해요.')
        if any(any(r.get(k) is None for k in ('approved', 'usefulness', 'major_errors', 'review_minutes')) for r in rows):
            raise CommandError('사람 평가가 미완료예요. B 전환을 판정하지 않아요.')
        for r in rows:
            if (type(r['approved']) is not bool or type(r['major_errors']) is not int or r['major_errors'] < 0
                    or any(type(r[k]) not in (int, float) or not math.isfinite(r[k]) for k in ('usefulness', 'review_minutes'))
                    or not 1 <= r['usefulness'] <= 5 or r['review_minutes'] <= 0):
                raise CommandError('사람 평가 값의 범위를 확인해 주세요.')
        from office.pilot_bundle import verify
        try:
            source, artifacts = verify(root, rows)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        a, b = groups['a'], groups['b']
        from office.lab_metrics import measured_sum
        usage = {}
        for profile in ('a', 'b'):
            runs = [r for r in artifacts if r['profile'] == profile]
            calls = [call for r in runs for call in r['calls']]
            usage[profile] = {'attempts': len(runs), 'completed': sum(r['outcome'] == 'complete' for r in runs),
                              'recorded_calls': len(calls), 'input_tokens': measured_sum(calls, 'input_tokens'),
                              'cache_read_input_tokens': measured_sum(calls, 'cache_read_input_tokens', 'cached_input_tokens'),
                              'cache_creation_input_tokens': measured_sum(calls, 'cache_creation_input_tokens'),
                              'output_tokens': measured_sum(calls, 'output_tokens'),
                              'model_seconds': sum(c.get('seconds') or 0 for c in calls)}
        result = {'human_approved_b': all(r['approved'] for r in b),
                  'completed_b': all(r['outcome'] == 'complete' for r in artifacts if r['profile'] == 'b'),
                  'usage_measured': all(r['calls'] and all(type(c.get('input_tokens')) is int and type(c.get('output_tokens')) is int
                                       for c in r['calls']) for r in artifacts if r['outcome'] == 'complete'),
                  'no_major_errors_b': sum(r['major_errors'] for r in b) == 0,
                  'usefulness_not_worse': median(r['usefulness'] for r in b) >= median(r['usefulness'] for r in a),
                  'review_time_reduced_20pct': median(r['review_minutes'] for r in b) <= .8 * median(r['review_minutes'] for r in a)}
        self.stdout.write(json.dumps({'criteria': result, 'eligible_for_review': all(result.values()),
                                     'code_fingerprint': source['code_fingerprint'],
                                     'usage': usage,
                                     'completed': {p: sum(r['outcome'] == 'complete' for r in artifacts if r['profile'] == p) for p in ('a', 'b')},
                                     'changes_profile': False}, ensure_ascii=False, indent=2))
