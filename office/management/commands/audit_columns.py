"""발행된 칼럼을 현재 기준으로 전수 검증한다.

예전 로직으로 쓰인 칼럼들은 지금의 기준(존댓말 통일·필수 섹션·수치 출처·저널식 도판)을
거치지 않았다. 무엇이 얼마나 어긋나는지 **모델 호출 없이** 먼저 세어 본다. 리메이크는
비용이 드는 작업이므로, 손볼 가치가 큰 것부터 골라내는 것이 목적이다.

점검 항목(모두 코드로 판별)
  style     평서체 섞임 (하우스 스타일은 존댓말)
  length    본문 하한 미달
  sections  필수 섹션 누락
  data      '숫자로 보는 현황' 의 단위 붙은 수치 3개 미만, 또는 지어낸 수치
  visual    차트·표 없음, 그림 중복, 옛 도판 형식(그림 N. 캡션이 없음)
  footer    옛 고지 문구 잔존

사용법:
  python manage.py audit_columns                 # 요약 + 손볼 순서
  python manage.py audit_columns --detail        # 칼럼별 지적 전부
  python manage.py audit_columns --worst 15      # 상위 N편만
  python manage.py audit_columns --csv out.csv   # 표로 저장
"""
import csv
import re

from django.core.management.base import BaseCommand

from community.models import Question
from office.pipeline import REQUIRED_SECTIONS, body_length, precheck_draft
from office.services import audit_style

BOT = 'techchang연구팀'
OLD_FOOTER = '본 칼럼은 AI 보조로 작성'
FIG_HEAD = re.compile(r'^\*\*(?:그림|표)\s*\d+\.', re.M)
IMG = re.compile(r'^!\[', re.M)
TABLE = re.compile(r'^\|', re.M)


def audit_one(q) -> dict:
    """칼럼 한 편의 결함 목록. 가중치가 큰 것부터 담는다."""
    c = q.content
    flaws, tags = [], set()

    for issue in precheck_draft(c):
        flaws.append(issue)
        if '평서체' in issue:
            tags.add('style')
        elif '하한' in issue:
            tags.add('length')
        elif '섹션' in issue:
            tags.add('sections')
        else:
            tags.add('data')

    imgs, tables, heads = len(IMG.findall(c)), len(TABLE.findall(c)), len(FIG_HEAD.findall(c))
    if not imgs and not tables:
        flaws.append('차트·표가 없습니다 — 데이터 근거가 그림으로 남지 않았습니다')
        tags.add('visual')
    elif imgs > 1 or heads > 1:
        flaws.append(f'도판이 여러 벌 들어 있습니다 (이미지 {imgs} · 캡션 {heads})')
        tags.add('visual')
    elif (imgs or tables) and not heads:
        flaws.append('옛 도판 형식입니다 — "그림 N. 제목 / 설명 / 단위·출처" 캡션이 없습니다')
        tags.add('visual')

    if OLD_FOOTER in c:
        flaws.append('옛 고지 문구가 남아 있습니다')
        tags.add('footer')

    _, st = audit_style(c)
    return {'q': q, 'flaws': flaws, 'tags': tags, 'chars': body_length(c),
            'plain': st['plain_ratio'], 'imgs': imgs, 'tables': tables,
            'views': q.view_count or 0}


class Command(BaseCommand):
    help = '발행된 칼럼을 현재 기준으로 전수 검증합니다 (모델 호출 없음).'

    def add_arguments(self, parser):
        parser.add_argument('--detail', action='store_true', help='칼럼별 지적을 모두 출력')
        parser.add_argument('--worst', type=int, default=0, help='상위 N편만 출력')
        parser.add_argument('--csv', help='결과를 CSV 로 저장')
        parser.add_argument('--by-views', action='store_true',
                            help='지적 수 대신 조회수 순으로 — 손볼 가치가 큰 글부터 본다')
        parser.add_argument('--author', default=BOT, help='대상 작성자 (기본: 연구팀 봇)')

    def handle(self, *args, **opts):
        out = self.stdout.write
        qs = (Question.objects.filter(is_deleted=False, author__username=opts['author'])
              .select_related('category').order_by('id'))
        rows = [audit_one(q) for q in qs]
        if not rows:
            out(self.style.WARNING(f"'{opts['author']}' 가 쓴 칼럼이 없습니다."))
            return

        clean = [r for r in rows if not r['flaws']]
        key = (lambda r: -r['views']) if opts['by_views'] else (lambda r: -len(r['flaws']))
        dirty = sorted((r for r in rows if r['flaws']), key=key)

        out(f'대상 {len(rows)}편 · 현재 기준 통과 {len(clean)}편 · 손봐야 할 글 {len(dirty)}편\n')
        counts = {}
        for r in dirty:
            for t in r['tags']:
                counts[t] = counts.get(t, 0) + 1
        label = {'style': '문체(평서체 섞임)', 'length': '분량 미달', 'sections': '필수 섹션 누락',
                 'data': '수치 근거 부족·지어냄', 'visual': '도판 없음·중복·옛 형식',
                 'footer': '옛 고지 문구'}
        out('결함 종류별 편수')
        for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            out(f'  {label.get(t, t):22s} {n:3d}편')

        shown = dirty[:opts['worst']] if opts['worst'] else dirty
        order = '조회수 많은 순' if opts['by_views'] else '지적 많은 순'
        out(f'\n손볼 순서 ({order}, {len(shown)}편)')
        for r in shown:
            q = r['q']
            out(f"  #{q.id:<4d} [{q.category.name if q.category else '-':6s}] "
                f"{q.subject[:36]:38s} 조회 {r['views']:>4d} · 지적 {len(r['flaws'])}건 · {r['chars']:,}자"
                + (f" · 평서체 {r['plain']:.0%}" if r['plain'] > 0.15 else ''))
            if opts['detail']:
                for f in r['flaws']:
                    out(f'        · {f[:150]}')

        if opts['csv']:
            with open(opts['csv'], 'w', encoding='utf-8-sig', newline='') as fh:
                w = csv.writer(fh)
                w.writerow(['id', '제목', '분야', '글자수', '평서체비율', '이미지', '표', '결함수', '결함'])
                for r in rows:
                    q = r['q']
                    w.writerow([q.id, q.subject, q.category.name if q.category else '',
                                r['chars'], f"{r['plain']:.2f}", r['imgs'], r['tables'],
                                len(r['flaws']), ' | '.join(r['flaws'])])
            out(self.style.SUCCESS(f"\nCSV 저장: {opts['csv']}"))
