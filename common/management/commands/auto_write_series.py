r"""
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
  python manage.py auto_write_series --revise-held --wait-on-limit  # 보류 원고 전부를 받은 지적으로 고쳐 재검증

기획서(시리즈 정의·목차·회차 골격·발행 일정·코드 발췌)는 community/series_catalog.py — 연재 화면과 공유한다.

서버 cron — 월요일 10시, ISO 주 번호 홀짝으로 두 시리즈가 번갈아 (series_catalog.SCHEDULE 과 같아야 함):
  0 10 * * 1  [ $(( $(date +\%V) \% 2 )) -eq 1 ] && ... auto_write_series --series django
  0 10 * * 1  [ $(( $(date +\%V) \% 2 )) -eq 0 ] && ... auto_write_series --series agent
"""
import re
import time
from datetime import datetime, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from community.series_catalog import MIN_GAP_DAYS, OUTLINES, SERIES, too_soon

# 구독(CLI) 사용 한도 — 'You've hit your session limit · resets 1am (Asia/Seoul)'
LIMIT_RE = re.compile(r'session limit|usage limit|rate limit|hit your .*limit', re.I)
RESET_RE = re.compile(r'resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)', re.I)
MAX_LIMIT_RETRIES = 6


def limit_wait_seconds(reason: str, now=None):
    """구독 한도 오류면 초기화 시각(+3분)까지 기다릴 초, 아니면 None. 시각을 못 읽으면 30분."""
    from django.utils import timezone
    if not LIMIT_RE.search(reason or ''):
        return None
    now = now or timezone.localtime()
    m = RESET_RE.search(reason)
    if not m:
        return 1800
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0)
    at = now.replace(hour=hour, minute=int(m.group(2) or 0), second=0, microsecond=0)
    if at <= now:
        at += timedelta(days=1)
    return int((at - now).total_seconds()) + 180


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
        parser.add_argument('--revise-held', dest='revise_draft', action='store_const', const=-1,
                            help='보류된 연재 원고 전부를 각자 받은 편집장·검증관 지적으로 고쳐 다시 검증')
        parser.add_argument('--note', default='', help='--revise-draft 와 함께: 운영자 수정 지시')
        parser.add_argument('--by', default='', help='--revise-draft 와 함께: 지시한 운영자 아이디')
        parser.add_argument('--dry-run', action='store_true', help='저장하지 않고 결과만 출력')
        parser.add_argument('--force', action='store_true',
                            help='직전 회차 후 최소 간격(MIN_GAP_DAYS)이 안 지났어도 발행')
        parser.add_argument('--wait-on-limit', action='store_true',
                            help='구독 사용 한도에 걸리면 초기화 시각까지 기다렸다가 같은 회차부터 이어서 진행')

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
        self._report(self._produce(opts, lambda: produce_episode(key, no, dry=opts['dry_run'], out=self.stdout.write)),
                     key, no)

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
            res = self._produce(opts, lambda ep=ep: produce_episode(key, ep.episode_number, target=ep,
                                                                    dry=opts['dry_run'], out=self.stdout.write))
            self._report(res, key, ep.episode_number)
            if res.get('limit'):
                self.stderr.write(self.style.ERROR('구독 사용 한도 — 남은 회차는 건너뜁니다. '
                                                   '--wait-on-limit 으로 다시 실행하면 기다렸다 이어 갑니다.'))
                return

    def _produce(self, opts, run):
        """회차 제작. 구독 한도로 실패하면 그 원고 기록을 지우고, --wait-on-limit 이면 초기화 뒤 다시 한다."""
        for _attempt in range(MAX_LIMIT_RETRIES):
            res = run()
            wait = limit_wait_seconds(res.get('reason', '')) if res.get('status') == 'failed' else None
            if wait is None:
                return res
            if res.get('draft') is not None and res['draft'].pk and not res.get('keep'):
                res['draft'].delete()          # 한도로 끊긴 새 원고는 일시적 실패 — 연구실 기록에 남기지 않는다
            if not opts.get('wait_on_limit'):
                return {**res, 'limit': True}
            self.stdout.write(f'[{datetime.now():%H:%M:%S}] 구독 사용 한도 — {wait // 60}분 뒤 같은 회차를 다시 합니다.')
            time.sleep(wait)
        return {**res, 'limit': True}

    # ── 보류 원고 재작성(운영자 지시)
    def _revise(self, opts):
        from django.contrib.auth.models import User
        from office.models import ColumnDraft
        from office.series_pipeline import revise_draft

        by = User.objects.filter(username=opts['by']).first() if opts['by'] else None
        if opts['revise_draft'] == -1:          # --revise-held: 보류된 연재 원고 전부, 각자 받은 지적으로
            drafts = list(ColumnDraft.objects.filter(status=ColumnDraft.STATUS_HOLD).exclude(series_key='')
                          .order_by('series_key', 'episode_number', 'id'))
            self.stdout.write(f'보류된 연재 원고 {len(drafts)}건을 지적 반영해 다시 검증합니다.')
        else:
            drafts = list(ColumnDraft.objects.filter(pk=opts['revise_draft']).exclude(series_key=''))
            if not drafts:
                raise CommandError('연재 원고가 아닙니다.')
        for draft in drafts:
            self.stdout.write(f'[{datetime.now():%H:%M:%S}] 원고 #{draft.id} {draft.series_key} '
                              f'{draft.episode_number}편 ({draft.qa_score}점) 재작성')
            res = self._produce(opts, lambda d=draft: revise_draft(d, opts['note'], by=by, out=self.stdout.write))
            self._report(res, draft.series_key, draft.episode_number)
            if res.get('limit'):
                self.stderr.write(self.style.ERROR('구독 사용 한도 — 남은 원고는 건너뜁니다(보류 상태 유지).'))
                return

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
