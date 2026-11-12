"""독립 테스트 DB에서 같은 기획을 A/B로 비교하는 비공개 실증 도구."""
import json
import os
import random
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from django.core.management import BaseCommand, call_command
from django.core.management.base import CommandError
from django.conf import settings
from django.test.runner import DiscoverRunner
from django.test import override_settings
from office.recorder import StageRecorder

TOPICS = [('coding', 'Django select_related와 prefetch_related의 선택과 쿼리 실행 결과'),
          ('data', '공식 통계 원문에 근거한 국내 성인 평생학습 참여 변화'),
          ('hrd', '기업 교육훈련의 현장 적용 효과를 근거와 지표로 점검하는 방법')]


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.resolve() != path.parent.absolute():
        raise CommandError('실증 경로에는 심볼릭 링크를 사용할 수 없어요.')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf-8') as file:
            file.write(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_manifest(root, cases):
    path = root / 'manifest.json'
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if [{k: v for k, v in case.items() if k != 'blind_id'} for case in saved] != cases:
            raise CommandError('기존 실증 목록과 설정이 달라요. 새 출력 폴더를 지정해 주세요.')
        if len({case.get('blind_id') for case in saved}) != len(cases) or any(not case.get('blind_id') for case in saved):
            raise CommandError('고정 블라인드 번호가 없는 이전 실증이에요. 새 출력 폴더를 지정해 주세요.')
        return saved
    if (root / 'human-review.json').exists() or any((root / case['id']).exists() for case in cases):
        raise CommandError('목록 없는 기존 평가 자료가 있어요. 새 출력 폴더를 지정해 주세요.')
    numbers = list(range(1, len(cases)+1))
    random.SystemRandom().shuffle(numbers)
    cases = [{**case, 'blind_id': f'{number:02d}'} for case, number in zip(cases, numbers)]
    write_private(path, json.dumps(cases, ensure_ascii=False, indent=2))
    return cases


def refresh_blind_review(root, cases):
    from office.recorder import digest
    path = root / 'human-review.json'
    saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    by_case = {row['case_id']: row for row in saved}
    if len(by_case) != len(saved) or set(by_case) - {case['id'] for case in cases}:
        raise CommandError('사람 평가의 사례 번호가 실증 목록과 일치하지 않아요.')
    reviews = []
    for case in cases:
        row = by_case.get(case['id'])
        if row and row['blind_id'] != case['blind_id']:
            raise CommandError('기존 블라인드 번호가 달라요. 평가 자료를 확인해 주세요.')
        draft = root / case['id'] / 'draft.md'
        if not draft.exists():
            if row:
                reviews.append(row)
            continue
        target = root / 'blind' / (case['blind_id']+'.md')
        body = draft.read_text(encoding='utf-8')
        record = root / case['id'] / 'case.json'
        if record.exists():
            from office.pilot_bundle import blind_body
            from office.artifacts import atomic_write, safe_path
            assets = json.loads(record.read_text(encoding='utf-8')).get('assets', [])
            body = blind_body(body, assets)
            for asset in assets:
                data = safe_path(root / case['id'] / 'media', asset['path']).read_bytes()
                atomic_write(safe_path(root / 'blind/assets', asset['sha256']+'.png'), data, private=True)
        if target.exists() and target.read_text(encoding='utf-8') != body:
            raise CommandError('이미 제공한 블라인드 원고가 달라졌어요. 기존 평가를 덮어쓰지 않아요.')
        if not target.exists():
            write_private(target, body)
        artifact_hash = digest(record.read_text(encoding='utf-8')) if record.exists() else None
        if row and row.get('artifact_hash') and row['artifact_hash'] != artifact_hash:
            raise CommandError('평가한 실행 증명서가 바뀌었어요. 기존 평가를 덮어쓰지 않아요.')
        reviews.append({**(row or {'blind_id': case['blind_id'], 'case_id': case['id'], 'approved': None,
                              'usefulness': None, 'major_errors': None, 'review_minutes': None}),
                        'artifact_hash': artifact_hash})
    write_private(path, json.dumps(sorted(reviews, key=lambda row: row['blind_id']), ensure_ascii=False, indent=2))
    blind_path = root / 'blind/review.json'
    blind_saved = json.loads(blind_path.read_text(encoding='utf-8')) if blind_path.exists() else []
    blind_by_id = {r['blind_id']: r for r in blind_saved}
    if len(blind_by_id) != len(blind_saved) or set(blind_by_id) - {case['blind_id'] for case in cases}:
        raise CommandError('블라인드 평가의 사례 번호가 중복되거나 목록과 달라요.')
    blinded = []
    for row in reviews:
        previous = blind_by_id.get(row['blind_id'])
        if previous and previous.get('artifact_hash') != row.get('artifact_hash'):
            raise CommandError('이미 평가한 블라인드 원고의 실행 지문이 바뀌었어요.')
        blinded.append(previous or {key: value for key, value in row.items() if key != 'case_id'})
    write_private(blind_path, json.dumps(blinded, ensure_ascii=False, indent=2))


class Command(BaseCommand):
    help = '실증 목록을 만들어요. --execute는 실제 구독을 사용해 독립 테스트 DB에서 최대 12편을 만들어요.'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--freeze', action='store_true', help='모델 호출 없이 현재 소스와 실증 목록을 고정해요.')
        parser.add_argument('--rounds', type=int, choices=[1, 2], default=2)
        parser.add_argument('--case', help='중단한 한 사례만 실행할 때 사용할 사례 번호')
        parser.add_argument('--code-run', action='store_true', help='운영과 다른 로컬 코드 실행 실험임을 표시해요.')

    def handle(self, *args, **opts):
        root = Path(opts['output']).absolute()
        if root.resolve() != root:
            raise CommandError('실증 경로에는 심볼릭 링크를 사용할 수 없어요.')
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        cases = [{'id': f'{round}-{i}-{p}', 'round': round, 'topic': topic, 'profile': p, 'angle': title,
                  'code_run': opts['code_run']}
                 for round in range(1, opts['rounds']+1) for i, (topic, title) in enumerate(TOPICS, 1)
                 for p in (('a', 'b') if round % 2 else ('b', 'a'))]
        if opts.get('case') and opts['case'] not in {case['id'] for case in cases}:
            raise CommandError('실증 목록에 없는 사례 번호예요.')
        cases = prepare_manifest(root, cases)
        if not opts['execute'] and not opts['freeze']:
            return
        if opts['execute'] and (not settings.DEBUG or os.environ.get('DJANGO_SETTINGS_MODULE', '').endswith('.prod')):
            raise CommandError('실증은 DEBUG가 켜진 로컬 설정에서만 실행해요.')
        from office.release import fingerprint_now
        from office.audit import fingerprint
        source = root / 'source.json'
        metadata = {'version': 2, 'code_fingerprint': fingerprint_now(), 'history': 'empty_isolated_database',
                    'manifest_digest': fingerprint(cases)}
        if source.exists() and json.loads(source.read_text(encoding='utf-8')) != metadata:
            raise CommandError('실증 도중 소스가 바뀌었어요. 새 출력 폴더에서 비교해 주세요.')
        if not source.exists():
            write_private(source, json.dumps(metadata, indent=2))
        if not opts['execute']:
            self.stdout.write('실증 소스 고정: '+metadata['code_fingerprint'])
            return
        refresh_blind_review(root, cases)
        selected = [case for case in cases if not opts.get('case') or opts['case'] == case['id']]
        if opts.get('case') and (root / selected[0]['id'] / 'stages.json').exists():
            raise CommandError('기존 실증 기록을 덮어쓰지 않아요. 새 출력 폴더를 지정해 주세요.')
        selected = [case for case in selected if not (root / case['id'] / 'stages.json').exists()]
        if not selected:
            return
        runner = DiscoverRunner(interactive=False, verbosity=0)
        databases = runner.setup_databases()
        original = StageRecorder.record
        try:
            for case in selected:
                if fingerprint_now() != metadata['code_fingerprint']:
                    raise CommandError('실행 도중 소스가 바뀌었어요. 비교 실증을 중단해요.')
                rows, text, console = [], {}, StringIO()
                failed = False
                provider_unavailable = False
                failure = None
                call_command('flush', interactive=False, verbosity=0, stdout=StringIO())
                def record(recorder, stage, *a, **kw):
                    row = original(recorder, stage, *a, **kw)
                    rows.append({**row, 'run_id': str(recorder.run_id)})
                    progress = root / 'progress.json'
                    write_private(progress, json.dumps({'case': case['id'], 'stage': stage}, ensure_ascii=False))
                    if kw.get('text'):
                        text[stage] = kw['text']
                        if stage == 'final':
                            text[stage] = '# ' + row['output'].get('subject', '') + '\n\n' + kw['text']
                    return row
                try:
                    with override_settings(MEDIA_ROOT=root / case['id'] / 'media'), \
                         patch.dict(os.environ, {'OFFICE_GENRES': '0', 'OFFICE_CODE_RUN': '1' if opts['code_run'] else '0',
                            'OFFICE_RUN_MAX_CODEX_TOKENS': '400000', 'OFFICE_GROUNDED_WEB_MAX': '0',
                            'CLAUDE_BACKEND': 'cli', 'CLAUDE_CLI_FALLBACK': 'false', 'AI_ALLOW_PAID_API': 'false'}), \
                         patch.object(StageRecorder, 'record', record):
                        call_command('office_publish', topic=case['topic'], profile=case['profile'],
                                     dry_run=True, no_publish=True, pilot_title=case['angle'], stdout=console)
                except Exception as exc:
                    failed = True
                    from common.services.cli_errors import ProviderUnavailable
                    provider_unavailable = isinstance(exc, ProviderUnavailable)
                    failure = {'type': type(exc).__name__, 'kind': getattr(exc, 'kind', None)}
                    console.write(f'\n중단: {type(exc).__name__}: {exc}')
                target = root / case['id']
                write_private(target / 'stages.json', json.dumps(rows, ensure_ascii=False, default=str))
                write_private(target / 'draft.md', text.get('final', ''))
                write_private(target / 'console.txt', console.getvalue())
                from office.pilot_bundle import case_record
                from office.artifacts import manifest as asset_manifest
                from types import SimpleNamespace
                with override_settings(MEDIA_ROOT=root / case['id'] / 'media'):
                    assets = asset_manifest(SimpleNamespace(content=text.get('final', ''), chart_path=''), strict=True)
                stable = fingerprint_now() == metadata['code_fingerprint']
                certificate = case_record(case, rows, text.get('final', ''), metadata, failed=failed, stable=stable, assets=assets)
                certificate['failure'] = failure
                write_private(target / 'case.json', json.dumps(certificate, ensure_ascii=False, indent=2))
                refresh_blind_review(root, cases)
                if not stable:
                    raise CommandError('실행 도중 소스가 바뀌었어요. 자료를 보존하고 비교 실증을 중단해요.')
                if provider_unavailable:
                    raise CommandError('구독 제공자를 사용할 수 없어 실증을 중단했어요. 실패 자료를 보존하며 다음 사례를 재시도하지 않아요.')
        finally:
            runner.teardown_databases(databases)
