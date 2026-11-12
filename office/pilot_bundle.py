"""사람 평가가 실제 동일 버전 실행 자료를 가리키는지 검증한다."""
import json
import uuid
from pathlib import Path
from .audit import fingerprint
from .recorder import digest


def case_record(case, rows, body, source, *, failed=False, stable=True, assets=None):
    finals = [row for row in rows if row['stage'] == 'final' and row['status'] == 'ok']
    return {'version': 1, 'case_id': case['id'], 'blind_id': case['blind_id'], 'profile': case['profile'],
            'run_id': rows[0]['run_id'] if rows else str(uuid.uuid4()),
            'code_fingerprint': source['code_fingerprint'], 'manifest_digest': source['manifest_digest'],
            'source_stable': stable, 'outcome': 'complete' if finals and not failed else 'failed',
            'draft_digest': digest(body), 'stages_digest': fingerprint(rows), 'assets': assets or []}


def blind_body(body, assets):
    for asset in assets:
        body = body.replace('/media/'+asset['path'], 'assets/'+asset['sha256']+'.png')
    return body


def verify(root, reviews):
    root = Path(root)
    try:
        cases = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        source = json.loads((root / 'source.json').read_text(encoding='utf-8'))
        if source.get('version') != 2 or fingerprint(cases) != source['manifest_digest']:
            raise ValueError('실증 목록과 소스 증명서가 일치하지 않아요.')
        if len({case['id'] for case in cases}) != len(cases) or {case['id'] for case in cases} != {r['case_id'] for r in reviews}:
            raise ValueError('모든 실증 사례의 평가와 실행 자료가 필요해요.')
        by_id = {row['case_id']: row for row in reviews}
        results, run_ids, blinds = [], set(), set()
        for case in cases:
            if not case['id'].replace('-', '').isalnum() or not case['blind_id'].isdigit():
                raise ValueError('실증 식별자가 올바르지 않아요.')
            folder = root / case['id']
            record_text = (folder / 'case.json').read_text(encoding='utf-8')
            record = json.loads(record_text)
            rows = json.loads((folder / 'stages.json').read_text(encoding='utf-8'))
            body = (folder / 'draft.md').read_text(encoding='utf-8')
            review = by_id[case['id']]
            uuid.UUID(record['run_id'])
            if (record['version'] != 1 or record['case_id'] != case['id'] or record['profile'] != case['profile']
                    or record['blind_id'] != case['blind_id'] or review['blind_id'] != case['blind_id']
                    or record['code_fingerprint'] != source['code_fingerprint']
                    or record['manifest_digest'] != source['manifest_digest'] or not record['source_stable']
                    or record['draft_digest'] != digest(body) or record['stages_digest'] != fingerprint(rows)
                    or review.get('artifact_hash') != digest(record_text)):
                raise ValueError('평가 대상 원고·실행·소스의 지문이 일치하지 않아요.')
            if record['run_id'] in run_ids or case['blind_id'] in blinds:
                raise ValueError('중복된 실행 또는 블라인드 번호가 있어요.')
            run_ids.add(record['run_id']); blinds.add(case['blind_id'])
            if any(row['run_id'] != record['run_id'] for row in rows):
                raise ValueError('서로 다른 실행의 단계가 섞였어요.')
            if rows:
                execution = rows[0]['output']['execution']
                if execution['profile'] != case['profile'] or execution['code_fingerprint'] != source['code_fingerprint']:
                    raise ValueError('단계 기록의 실제 실행 버전이 달라요.')
            from .artifacts import safe_path
            import hashlib
            for asset in record.get('assets', []):
                original = safe_path(folder / 'media', asset['path']).read_bytes()
                blinded = safe_path(root / 'blind/assets', asset['sha256']+'.png').read_bytes()
                if (hashlib.sha256(original).hexdigest() != asset['sha256'] or len(original) != asset['size']
                        or original != blinded):
                    raise ValueError('평가 이미지가 제작 산출물과 달라요.')
            if (root / 'blind' / (case['blind_id']+'.md')).read_text(encoding='utf-8') != blind_body(body, record.get('assets', [])):
                raise ValueError('블라인드 원고가 실행 결과와 달라요.')
            finals = [row for row in rows if row['stage'] == 'final' and row['status'] == 'ok']
            if record['outcome'] == 'complete':
                if not finals or not body.strip() or [r['seq'] for r in rows] != list(range(1, len(rows)+1)):
                    raise ValueError('완료 사례의 원고·최종 단계 기록이 누락됐어요.')
                final = finals[-1]
                title, content = body.split('\n\n', 1)
                if title != '# '+final['output']['subject'] or digest(content) != final['text_digest']:
                    raise ValueError('최종 원고 본문이 제작 기록과 달라요.')
                if not {'check', 'review'}.issubset({r['stage'] for r in rows}):
                    raise ValueError('완료 사례의 필수 검증·심사 기록이 없어요.')
            elif record['outcome'] != 'failed' or review.get('approved') is True:
                raise ValueError('실패·중단 사례를 승인 결과로 표시할 수 없어요.')
            calls = [call for row in rows for call in row.get('calls', [])]
            results.append({**record, 'calls': calls})
        return source, results
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError('실증 증거 묶음이 없거나 형식이 올바르지 않아요.') from exc
