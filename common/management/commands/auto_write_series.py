"""
연재 칼럼(시리즈) 회차 발행·리메이크 커맨드

회차는 칼럼과 같은 연구실 검증을 거친다(office/series_pipeline.py):
  집필(윤성) → 자동 점검 → 팩트체크(하경, 웹으로 공식 문서 대조) → 평론(예원) → 편집 심사(승현, 80점 이상)
  → 미달이면 1회 보완·재심 → 통과하면 발행(리메이크는 제자리 갱신), 아니면 보류(/lab/admin/ 에서 운영자 판단)

사용법:
  python manage.py auto_write_series --series agent              # 다음 미발행 회차 1편
  python manage.py auto_write_series --series agent --force      # 직전 회차 후 최소 간격 무시
  python manage.py auto_write_series --series django --remake 3  # 발행된 3편을 다시 만들어 제자리 갱신
  python manage.py auto_write_series --series django --remake all
  python manage.py auto_write_series --series agent --dry-run    # 저장 없이 결과만
  python manage.py auto_write_series --revise-draft 42 --note "…"   # 보류 원고에 운영자 지시 반영(관리 화면이 호출)

기획서(시리즈 정의·목차·회차 골격·발행 일정·코드 발췌)는 community/series_catalog.py — 연재 화면과 공유한다.

서버 cron — 월요일 10시, ISO 주 번호 홀짝으로 두 시리즈가 번갈아 (series_catalog.SCHEDULE 과 같아야 함):
  0 10 * * 1  [ $(( $(date +\%V) \% 2 )) -eq 1 ] && ... auto_write_series --series django
  0 10 * * 1  [ $(( $(date +\%V) \% 2 )) -eq 0 ] && ... auto_write_series --series agent
"""
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from community.series_catalog import MIN_GAP_DAYS, OUTLINES, SERIES, too_soon


class Command(BaseCommand):
    help = '연재 회차를 연구실 검증을 거쳐 발행하거나, 발행된 회차를 리메이크합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--series', choices=list(SERIES.keys()), default='django',
                            help='시리즈 키 (기본: django)')
        parser.add_argument('--episode', type=int, default=None,
                            help='새로 발행할 회차 강제 지정 (기본: 다음 미발행 회차)')
        parser.add_argument('--remake', default=None,
                            help='발행된 회차 번호(또는 all)를 다시 만들어 제자리 갱신')
        parser.add_argument('--revise-draft', type=int, default=None, help='보류된 연재 원고 id')
        parser.add_argument('--note', default='', help='--revise-draft 와 함께: 운영자 수정 지시')
        parser.add_argument('--by', default='', help='--revise-draft 와 함께: 지시한 운영자 아이디')
        parser.add_argument('--dry-run', action='store_true', help='저장하지 않고 결과만 출력')
        parser.add_argument('--force', action='store_true',
                            help='직전 회차 후 최소 간격(MIN_GAP_DAYS)이 안 지났어도 발행')

    def handle(self, *args, **opts):
        from office import live
        try:
            if opts['revise_draft']:
                return self._revise(opts)
            if opts['remake']:
                return self._remake(opts)
            return self._new(opts)
        finally:
            live.finish()
            try:
                call_command('polish_logs', limit=12, verbosity=0)   # 연구실 공개 피드 문장 다듬기
            except Exception:  # noqa: BLE001
                pass

    # ── 새 회차
    def _new(self, opts):
        from community.models import Category, ColumnSeries
        from office.series_pipeline import produce_episode

        key, cfg = opts['series'], SERIES[opts['series']]
        series = ColumnSeries.objects.filter(slug=cfg['slug']).first()
        if series is None and not opts['dry_run']:
            series = ColumnSeries.objects.create(
                slug=cfg['slug'], title=cfg['title'], subtitle=cfg['subtitle'], description=cfg['description'],
                audience=cfg['audience'], category=Category.objects.get(name=cfg['category_name']),
                total_episodes=len(OUTLINES[key]))
            self.stdout.write(self.style.SUCCESS(f'시리즈 생성: {series.title}'))

        last = series.published_episodes.last() if series else None
        if opts['episode'] is None and not opts['force'] and last and too_soon(last.create_date):
            self.stdout.write(f'직전 회차({last.episode_number}편, {last.create_date:%m-%d}) 후 {MIN_GAP_DAYS}일이 '
                              '지나지 않아 이번 차례는 건너뜁니다. (--force 로 강제)')
            return
        no = opts['episode'] if opts['episode'] is not None else (series.next_episode_number if series else 0)
        if not any(o['no'] == no for o in OUTLINES[key]):
            self.stdout.write(self.style.SUCCESS(f'발행할 회차가 없습니다. (총 {len(OUTLINES[key])}편 완결)'))
            return
        self._report(produce_episode(key, no, dry=opts['dry_run'], out=self.stdout.write), key, no)

    # ── 리메이크(제자리 갱신)
    def _remake(self, opts):
        from community.models import ColumnSeries
        from office.series_pipeline import produce_episode

        key, cfg = opts['series'], SERIES[opts['series']]
        series = ColumnSeries.objects.filter(slug=cfg['slug']).first()
        if series is None:
            raise CommandError('시리즈가 아직 없습니다.')
        eps = list(series.published_episodes)
        if opts['remake'] != 'all':
            eps = [e for e in eps if str(e.episode_number) == str(opts['remake'])]
            if not eps:
                raise CommandError(f"발행된 {opts['remake']}편이 없습니다.")
        for ep in eps:
            self.stdout.write(f'[{datetime.now():%H:%M:%S}] 리메이크 {ep.episode_number}편 #{ep.id} 「{ep.subject}」')
            self._report(produce_episode(key, ep.episode_number, target=ep, dry=opts['dry_run'], out=self.stdout.write),
                         key, ep.episode_number)

    # ── 보류 원고 재작성(운영자 지시)
    def _revise(self, opts):
        from django.contrib.auth.models import User
        from office.models import ColumnDraft
        from office.series_pipeline import revise_draft

        draft = ColumnDraft.objects.filter(pk=opts['revise_draft']).exclude(series_key='').first()
        if draft is None:
            raise CommandError('연재 원고가 아닙니다.')
        by = User.objects.filter(username=opts['by']).first() if opts['by'] else None
        self._report(revise_draft(draft, opts['note'], by=by, out=self.stdout.write),
                     draft.series_key, draft.episode_number)

    def _report(self, res, key, no):
        status = res.get('status')
        head = f"[{SERIES[key]['title']}] {no}편"
        if status in ('published', 'updated'):
            verb = '제자리 갱신' if status == 'updated' else '발행'
            self.stdout.write(self.style.SUCCESS(f"{head} {verb} 완료 — {res['score']}점 (id={res['question'].pk})"))
        elif status == 'hold':
            self.stdout.write(self.style.WARNING(f"{head} 기준 미달({res['score']}점) — 보류. /lab/admin/ 에서 검토"
                                                 + (' (원문은 그대로 둡니다)' if res['draft'].target_question_id else '')))
        elif status == 'dry':
            self.stdout.write(self.style.WARNING(f"{head} [dry-run] {res['score']}점 · {res['verdict']}"))
        else:
            self.stderr.write(self.style.ERROR(f"{head} 실패: {res.get('reason', '')}"))
