"""검색 성과로 고르는 제목 다시 쓰기 — 노출은 쌓이는데 클릭이 안 나는 칼럼의 제목만 고친다(본문은 그대로).

    python manage.py seo_retitle            # 후보와 제안 제목만 보여 준다(기본, 모델 호출 있음)
    python manage.py seo_retitle --list     # 후보만(모델 호출 없음)
    python manage.py seo_retitle --apply    # 제안 제목을 실제로 반영(IndexNow 알림은 저장 신호가 보낸다)

제목 후보는 발행 때와 같은 제목 실험실(office.pipeline.step_headline)이 만들고, 그 칼럼이 실제로
노출된 검색어를 '독자가 검색할 말'로 준다. 같은 칼럼을 너무 자주 바꾸면 검색엔진이 혼란스러워하므로
최근 60일 안에 다시 쓴 칼럼은 건너뛴다(WorkLog action='retitle').
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

COOLDOWN_DAYS = 60


class Command(BaseCommand):
    help = '검색 노출 대비 클릭이 약한 칼럼의 제목을 다시 씁니다.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='제안 제목을 실제로 반영')
        parser.add_argument('--list', action='store_true', help='후보만 출력(모델 호출 없음)')
        parser.add_argument('--max', type=int, default=3, help='한 번에 다룰 최대 칼럼 수')

    def handle(self, *args, **opts):
        from community.models import Question
        from office import pipeline as P
        from office.models import WorkLog
        from office.seo_audit import retitle_candidates
        from office.services import log

        cands = retitle_candidates()
        recent_ids = set(WorkLog.objects.filter(action='retitle',
                                                created_at__gte=timezone.now() - timedelta(days=COOLDOWN_DAYS))
                         .values_list('text', flat=True))
        cands = [c for c in cands if not any(t.startswith(f"#{c['id']} ") for t in recent_ids)][:opts['max']]
        if not cands:
            self.stdout.write('제목 다시 쓰기 후보가 없습니다.')
            return
        titles = list(Question.objects.filter(author__username=Question.BOT_USERNAME, is_deleted=False)
                      .values_list('subject', flat=True))
        for c in cands:
            self.stdout.write(f"#{c['id']} 「{c['subject']}」 노출 {c['impr']} · 클릭 {c['clicks']} "
                              f"({c['ctr']}%) · {c['position']}위 · 검색어 {', '.join(c['queries'][:3])}")
            if opts['list']:
                continue
            q = Question.objects.get(id=c['id'])
            new, why = P.step_headline(q.subject, q.content, keywords=c['queries'],
                                       recent=[t for t in titles if t != q.subject])
            if new == q.subject:
                self.stdout.write(f'    → 유지 ({why})')
                continue
            self.stdout.write(f'    → 「{new}」 — {why}')
            if opts['apply']:
                old = q.subject
                q.subject = new
                q.modify_date = timezone.now()
                q.save()
                log('editor', 'retitle', f"#{q.id} 검색 성과로 제목 수정: 「{old}」 → 「{new}」 (노출 {c['impr']}, "
                                         f"CTR {c['ctr']}%)")
