"""제목 결별 검색 클릭률 비교 — 예전 결(은유·콜론 부제)과 요즘 결("검색어, 설명" 공식)을 GSC 성과로 견줘요.

  python manage.py title_ctr_report            (기본 최근 90일)
  python manage.py title_ctr_report --days 180

모델 호출은 없어요. 클릭률은 검색 순위에 크게 좌우되므로 평균 순위가 비슷한 묶음끼리만 비교하세요.
표본이 작은 묶음(글 5편·노출 300 미만)은 '표본 작음'으로 표시해요.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = '제목 결별 검색 노출·클릭률·평균 순위를 비교합니다(GSC).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90)

    def handle(self, *args, **opts):
        from office import seo_audit as S
        try:
            stats = S.page_queries(days=opts['days'])
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f'GSC 성과를 읽지 못했어요: {exc}')
        rows = S.title_ctr_groups(stats, S._columns())
        if not rows:
            self.stdout.write('비교할 칼럼 성과가 없어요.')
            return
        self.stdout.write(f"최근 {opts['days']}일 · 발행 {S.RETITLE_MIN_AGE_DAYS}일 지난 칼럼 · 20위 안")
        for r in rows:
            note = ' (표본 작음)' if r['small_sample'] else ''
            self.stdout.write(f"- {r['style']}: {r['posts']}편 · 노출 {r['impr']:,} · 클릭 {r['clicks']:,} · "
                              f"클릭률 {r['ctr']}% · 평균 {r['position']}위{note}")
            for ex in r['examples']:
                self.stdout.write(f'    「{ex}」')
