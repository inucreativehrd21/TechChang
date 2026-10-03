"""발행된 칼럼에서 **기계적으로 고칠 수 있는 것**만 손본다 (모델 호출 없음).

전수 검증에서 나온 결함 중 글을 다시 쓰지 않고도 해결되는 것들이다. 데이터 근거 섹션
신설처럼 새 내용이 필요한 작업은 여기서 하지 않는다 — 그건 리메이크의 몫이다.

  footer   옛 고지 문구("본 칼럼은 AI 보조로 작성…") 제거. 2026-09 에 쓰지 않기로 한 문구다

사용법:
  python manage.py clean_columns                 # 무엇이 바뀌는지만 보여 준다
  python manage.py clean_columns --apply
  python manage.py clean_columns --apply --id 44 --id 45
"""
import re

from django.core.management.base import BaseCommand
from django.utils import timezone

from community.models import Question
from office.models import WorkLog

BOT = 'techchang연구팀'
# 문구 모양이 조금씩 달라 한 줄 전체를 지운다. 앞뒤 구분선·빈 줄도 함께 정리한다.
FOOTER = re.compile(r'^[ \t>*_]*본 칼럼은 AI[^\n]*\n?', re.M)


def strip_footer(content: str) -> str:
    """고지 문구가 있을 때만 손댄다.

    공백 정리를 무조건 돌리면 문구가 없는 글까지 '바뀐 것'으로 잡혀, 몇 편을 고쳤는지가
    실제와 어긋난다(검증은 45편인데 56편으로 셌다).
    """
    if not FOOTER.search(content):
        return content
    text = FOOTER.sub('', content)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.rstrip() + '\n'


class Command(BaseCommand):
    help = '발행 칼럼의 기계적 결함을 정리합니다 (모델 호출 없음).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='실제로 저장 (기본은 미리보기)')
        parser.add_argument('--id', type=int, action='append', help='특정 칼럼만')
        parser.add_argument('--author', default=BOT)

    def handle(self, *args, **opts):
        out = self.stdout.write
        qs = Question.objects.filter(is_deleted=False, author__username=opts['author'])
        if opts['id']:
            qs = qs.filter(pk__in=opts['id'])

        hits = []
        for q in qs.order_by('id'):
            new = strip_footer(q.content)
            if new != q.content:
                hits.append((q, new))

        if not hits:
            out('고칠 것이 없습니다.')
            return

        out(f'옛 고지 문구가 남은 칼럼 {len(hits)}편')
        for q, _ in hits[:10]:
            line = next((ln.strip() for ln in q.content.splitlines() if '본 칼럼은 AI' in ln), '')
            out(f'  #{q.id:<4d} {q.subject[:40]:42s} …{line[:50]}')
        if len(hits) > 10:
            out(f'  … 외 {len(hits) - 10}편')

        if not opts['apply']:
            out(self.style.WARNING('\n미리보기입니다. 실제로 고치려면 --apply 를 붙이세요.'))
            return

        for q, new in hits:
            q.content = new
            q.modify_date = timezone.now()
            q.save(update_fields=['content', 'modify_date'])
        WorkLog.objects.create(agent='editor', action='revise',
                               text=f'옛 고지 문구 일괄 제거 {len(hits)}편')
        out(self.style.SUCCESS(f'\n{len(hits)}편 정리 완료'))
