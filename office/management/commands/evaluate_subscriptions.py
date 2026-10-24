"""구독 백엔드 비공개 비교. DB·메일·공개 원고를 변경하지 않는다."""
import hashlib
import json
import os
from pathlib import Path
import time

from django.core.management.base import BaseCommand, CommandError

from common.services import claude, codex
from common.services.cli_errors import ProviderUnavailable
from common.services.cli_lock import codex_lock
from office.agents import AGENTS
from office.subscription_eval import CASES, check


class Command(BaseCommand):
    help = '고정 입력 12건으로 Claude/Codex 구독 응답을 비공개 비교해요. 실제 구독 사용량이 들어요.'

    def add_arguments(self, parser):
        parser.add_argument('--backend', required=True, choices=['claude', 'codex'])
        parser.add_argument('--effort', choices=['medium', 'high'], default='high')
        parser.add_argument('--cases', default='')
        parser.add_argument('--output-dir', required=True)
        parser.add_argument('--timeout', type=int, default=300)
        parser.add_argument('--recheck-only', action='store_true', help='기존 응답만 다시 검사해요. 모델을 호출하지 않아요.')

    def handle(self, *args, **opts):
        selected = set(opts['cases'].split(',')) if opts['cases'] else {c['id'] for c in CASES}
        unknown = selected - {c['id'] for c in CASES}
        if unknown:
            raise CommandError('알 수 없는 평가 항목이에요: ' + ', '.join(sorted(unknown)))
        root = Path(opts['output_dir']).resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # 평가에서는 API를 호출하지 않고, 구독 CLI 어댑터를 직접 호출한다.
        previous = os.environ.get('CODEX_REASONING_EFFORT')
        os.environ['CODEX_REASONING_EFFORT'] = opts['effort']
        report, error = [], None
        try:
            for case in CASES:
                if case['id'] not in selected:
                    continue
                role = AGENTS[case['agent']]['system']
                signature = hashlib.sha256((json.dumps(case, ensure_ascii=False, sort_keys=True) + role +
                                           opts['backend'] + opts['effort'] + codex.model_name()).encode()).hexdigest()
                path = root / (case['id'] + '.json')
                if path.exists():
                    old = json.loads(path.read_text(encoding='utf-8'))
                    if opts['recheck_only'] or (old.get('signature') == signature and old.get('ok')):
                        if old.get('ok'):
                            old['issues'] = check(case, old['text'])
                            if opts['backend'] == 'codex' and case.get('tools') and not old.get('usage', {}).get('web_search_calls'):
                                old['issues'].append('웹 도구 실행 이벤트가 없어요. 원문 확인 여부를 검토해 주세요.')
                            old['manual_review'] = case.get('manual_review', [])
                            path.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding='utf-8')
                        report.append(old)
                        self.stdout.write(case['id'] + ': 기존 응답을 재사용해요.')
                        continue
                if opts['recheck_only']:
                    raise CommandError('재검사할 응답이 없어요: ' + case['id'])
                row = {'case': case['id'], 'signature': signature, 'backend': opts['backend'],
                       'model': codex.model_name() if opts['backend'] == 'codex' else str(claude.DEFAULT_MODEL),
                       'effort': opts['effort'], 'ok': False}
                started = time.monotonic()
                try:
                    if opts['backend'] == 'codex':
                        with codex_lock():
                            text, usage = codex.ask(case['prompt'], system=role, timeout=opts['timeout'],
                                                    tools=tuple(case.get('tools', [])), output_schema=case.get('schema'))
                    else:
                        text, usage = claude._cli_ask(case['prompt'], system=role, model=claude.DEFAULT_MODEL,
                                                     timeout=opts['timeout'], tools=tuple(case.get('tools', [])))
                    row.update(ok=True, text=text, usage=usage, issues=check(case, text),
                               manual_review=case.get('manual_review', []))
                    if opts['backend'] == 'codex' and case.get('tools') and not usage.get('web_search_calls'):
                        row['issues'].append('웹 도구 실행 이벤트가 없어요. 원문 확인 여부를 검토해 주세요.')
                except ProviderUnavailable as exc:
                    row.update(error=str(exc), error_kind=exc.kind)
                    error = exc
                row['seconds'] = round(time.monotonic() - started, 1)
                path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
                path.chmod(0o600)
                report.append(row)
                self.stdout.write(f"{case['id']}: {'완료' if row['ok'] else '실패'} ({row['seconds']}초)")
                if error:
                    break  # 한도·인증 실패 후 나머지 호출로 구독을 낭비하지 않는다.
        finally:
            if previous is None:
                os.environ.pop('CODEX_REASONING_EFFORT', None)
            else:
                os.environ['CODEX_REASONING_EFFORT'] = previous
        summary = {'backend': opts['backend'], 'effort': opts['effort'], 'requested': len(selected),
                   'completed': sum(r['ok'] for r in report),
                   'checks_passed': sum(r['ok'] and not r.get('issues') for r in report),
                   'cases': [{k: r[k] for k in ('case', 'ok', 'issues', 'seconds', 'usage', 'error') if k in r} for r in report],
                   'note': '자동 점검은 편집 품질 동등성을 보장하지 않아요. 출력 원문과 실제 제작 검증을 함께 검토해요.'}
        (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        if error:
            raise CommandError(f'평가를 멈췄어요: {error}')
        self.stdout.write(json.dumps({k: v for k, v in summary.items() if k != 'cases'}, ensure_ascii=False))
