"""이미 발행된 칼럼의 차트를 현재 렌더러로 다시 그린다.

차트 spec 은 따로 저장하지 않지만, 칼럼 본문에 차트와 **같은 값의 표**가 함께 들어가므로
거기서 spec 을 복원할 수 있다. 덕분에 Claude API 를 부르지 않고(=추가 과금 없이) 그림만
다시 만든다. 파일명을 그대로 쓰므로 본문은 건드리지 않고 이미지가 교체된다.

사용법:
  python manage.py redraw_chart --question 104
  python manage.py redraw_chart --question 104 --dry-run   # 복원한 spec 만 보여준다
  python manage.py redraw_chart --all                      # 차트가 있는 발행 칼럼 전부
"""
import re

from django.core.management.base import BaseCommand, CommandError

from community.models import Question
from office.models import ColumnDraft, WorkLog
from office.services import effective_chart_type, render_chart

IMAGE_RE = re.compile(r'!\[(?P<title>[^\]]*)\]\(/media/(?P<path>columns/[^)]+)\)')
UNIT_RE = re.compile(r'\(단위:\s*(?P<unit>[^)]+)\)')
SOURCE_RE = re.compile(r'^\*출처:\s*(?P<source>.+?)\*\s*$', re.MULTILINE)


def extract_spec(content: str) -> tuple:
    """본문에서 차트 spec 을 복원. 반환 (spec, 이미지 상대경로) 또는 (None, 사유)."""
    m = IMAGE_RE.search(content)
    if not m:
        return None, '본문에 차트 이미지가 없음'

    rows = [ln.strip() for ln in content.splitlines()
            if ln.strip().startswith('|') and ln.strip().endswith('|')]
    rows = [r for r in rows if not re.fullmatch(r'\|(\s*:?-+:?\s*\|)+', r)]
    if len(rows) < 2:
        return None, '차트와 짝이 되는 표를 찾지 못함'

    def cells(row):
        return [c.strip() for c in row.strip('|').split('|')]

    header = cells(rows[0])
    if len(header) < 2:
        return None, '표에 값 열이 없음'

    labels, columns = [], [[] for _ in header[1:]]
    for row in rows[1:]:
        c = cells(row)
        if len(c) != len(header):
            continue
        try:
            values = [float(v.replace(',', '')) for v in c[1:]]
        except ValueError:
            continue                      # 숫자가 아닌 행은 표의 일부가 아니다
        labels.append(c[0])
        for i, v in enumerate(values):
            columns[i].append(v)

    if len(labels) < 2:
        return None, '표에서 숫자 행을 2개 이상 읽지 못함'

    unit_m = UNIT_RE.search(content)
    source_m = SOURCE_RE.search(content)
    spec = {
        'type': 'bar',                    # 실제 방향은 렌더러가 항목명 길이로 정한다
        'title': m.group('title'),
        'labels': labels,
        'series': [{'name': name, 'values': vals} for name, vals in zip(header[1:], columns)],
        'unit': unit_m.group('unit').strip() if unit_m else '',
        'source': source_m.group('source').strip() if source_m else '',
    }
    return spec, m.group('path')


class Command(BaseCommand):
    help = '발행된 칼럼의 차트를 현재 렌더러로 다시 그립니다 (API 호출 없음).'

    def add_arguments(self, parser):
        parser.add_argument('--question', type=int, help='칼럼(Question) ID')
        parser.add_argument('--all', action='store_true', help='차트가 있는 발행 칼럼 전부')
        parser.add_argument('--dry-run', action='store_true', help='복원한 spec 만 출력')

    def handle(self, *args, **opts):
        if opts['question']:
            targets = list(Question.objects.filter(pk=opts['question'], is_deleted=False))
            if not targets:
                raise CommandError(f"칼럼 #{opts['question']} 없음")
        elif opts['all']:
            targets = list(Question.objects.filter(is_deleted=False, content__contains='/media/columns/'))
        else:
            raise CommandError('--question 또는 --all 중 하나가 필요합니다')

        out = self.stdout.write
        done = failed = 0
        for q in targets:
            spec, info = extract_spec(q.content)
            if spec is None:
                out(self.style.WARNING(f'#{q.id} 건너뜀 — {info}'))
                failed += 1
                continue

            kind = effective_chart_type(spec['type'], spec['labels'])
            out(f"#{q.id} {q.subject[:40]}")
            out(f"    항목 {len(spec['labels'])}개 · 계열 {len(spec['series'])}개 · {kind} · {info}")
            if opts['dry_run']:
                for lab, v in zip(spec['labels'], spec['series'][0]['values']):
                    out(f"      {lab} = {v:g}")
                continue

            stem = info.rsplit('/', 1)[-1].rsplit('.', 1)[0]
            rel, err = render_chart(spec, stem)
            if not rel:
                out(self.style.ERROR(f'    렌더 실패: {err}'))
                failed += 1
                continue
            done += 1
            out(self.style.SUCCESS(f'    다시 그림: /media/{rel}'))
            ColumnDraft.objects.filter(question=q).update(
                chart_note=f"차트 재렌더({kind}, 항목 {len(spec['labels'])}개)"[:300])
            WorkLog.objects.create(agent='charter', action='chart',
                                   text=f'#{q.id} 차트 재렌더: {q.subject[:40]} ({kind})')

        if not opts['dry_run']:
            out(f'\n완료 {done}건' + (f' · 실패·건너뜀 {failed}건' if failed else ''))
