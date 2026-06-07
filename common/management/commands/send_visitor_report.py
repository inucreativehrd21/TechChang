"""
방문자 통계 이메일 리포트 (서버 로그 리포트와 분리)

DailyVisitor(date, visitor_count) 한 테이블을 ORM으로 집계해
주간/월간 방문자 총합·일평균·증감·추세를 정리하고,
(선택) Google Search Console의 노출/클릭/CTR/게재순위를 덧붙여 발송한다.

사용법:
    python manage.py send_visitor_report --period weekly  [--to admin@x.com] [--dry-run]
    python manage.py send_visitor_report --period monthly [--to admin@x.com] [--dry-run]

크론(매주 월요일 오전 8시 30분):
    30 8 * * 1 ... manage.py send_visitor_report --period weekly --to $ADMIN_EMAIL
"""
import os
from collections import OrderedDict
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

WEEKDAY_KR = ['월', '화', '수', '목', '금', '토', '일']
LAUNCH_DATE = date(2025, 10, 1)  # 서비스 런칭일 (base_views와 동일)


class Command(BaseCommand):
    help = '방문자 통계를 집계해 주간/월간 이메일 리포트를 발송합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--period', choices=['weekly', 'monthly'], default='weekly',
                            help='집계 주기 (기본: weekly)')
        parser.add_argument('--to', type=str, default='',
                            help='수신자 이메일 (기본: DJANGO_ADMIN_EMAIL 환경변수)')
        parser.add_argument('--dry-run', action='store_true',
                            help='발송 없이 콘솔에 텍스트 리포트만 출력')

    def handle(self, *args, **options):
        period = options['period']
        dry_run = options['dry_run']
        recipient = (
            options['to']
            or os.environ.get('DJANGO_ADMIN_EMAIL', '')
            or getattr(settings, 'ADMINS', [('', '')])[0][1]
        )
        if not recipient and not dry_run:
            self.stderr.write(self.style.ERROR(
                '수신자 이메일이 없습니다. --to 또는 DJANGO_ADMIN_EMAIL 환경변수를 설정하세요.'
            ))
            return

        self.stdout.write(f'[{datetime.now():%Y-%m-%d %H:%M}] 방문자 리포트 집계 시작 ({period})...')
        data = self._collect(period)
        gsc = self._collect_gsc(data['range_start'], data['range_end'])

        text = self._render_text(period, data, gsc)
        html = self._render_html(period, data, gsc)

        if dry_run:
            # Windows 콘솔(cp949)에서도 깨지지 않도록 인코딩-안전하게 출력.
            # 실제 이메일은 UTF-8로 발송되므로 이 처리는 미리보기 표시에만 영향.
            enc = getattr(self.stdout._out, 'encoding', None) or 'utf-8'
            safe = ('\n' + '=' * 60 + '\n' + text + '\n' + '=' * 60)
            self.stdout.write(safe.encode(enc, errors='replace').decode(enc))
            return

        label = '주간' if period == 'weekly' else '월간'
        subject = (f'[테크창] 📊 방문자 {label} 리포트 '
                   f'{data["range_start"]:%Y-%m-%d} ~ {data["range_end"]:%Y-%m-%d}')
        send_mail(
            subject=subject,
            message=text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            html_message=html,
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(f'방문자 리포트 발송 완료 → {recipient}'))

    # ------------------------------------------------------------------ #
    #  방문자 데이터 집계 (DailyVisitor)
    # ------------------------------------------------------------------ #
    def _collect(self, period):
        from community.models import DailyVisitor
        from django.db.models import Sum

        today = date.today()

        # 전체 행을 dict(date -> count)로 적재 (최근 ~120일이면 충분)
        oldest_needed = today - timedelta(days=120)
        rows = DailyVisitor.objects.filter(date__gte=oldest_needed).values_list('date', 'visitor_count')
        counts = {d: c for d, c in rows}

        def total(start, end):
            """start~end (양끝 포함) 일별 합계와 집계된 일수."""
            s = 0
            for i in range((end - start).days + 1):
                s += counts.get(start + timedelta(days=i), 0)
            return s, (end - start).days + 1

        if period == 'weekly':
            # 직전 '완료된' 주 (지난 월~일) 기준
            this_monday = today - timedelta(days=today.weekday())
            cur_start = this_monday - timedelta(days=7)
            cur_end = this_monday - timedelta(days=1)
            prev_start = cur_start - timedelta(days=7)
            prev_end = cur_start - timedelta(days=1)
        else:
            # 직전 '완료된' 달 기준
            first_this_month = today.replace(day=1)
            cur_end = first_this_month - timedelta(days=1)        # 지난달 말일
            cur_start = cur_end.replace(day=1)                    # 지난달 1일
            prev_end = cur_start - timedelta(days=1)              # 전전달 말일
            prev_start = prev_end.replace(day=1)                  # 전전달 1일

        cur_total, cur_days = total(cur_start, cur_end)
        prev_total, prev_days = total(prev_start, prev_end)
        cur_avg = round(cur_total / cur_days, 1) if cur_days else 0
        prev_avg = round(prev_total / prev_days, 1) if prev_days else 0

        # 어제 + 전주 동요일 대비
        yest = today - timedelta(days=1)
        yest_count = counts.get(yest, 0)
        same_dow_prev = counts.get(yest - timedelta(days=7), 0)

        # 최근 7일 일별 (막대 표시용)
        last7 = [(today - timedelta(days=i), counts.get(today - timedelta(days=i), 0))
                 for i in range(7, 0, -1)]

        # 주차별 추이 (최근 8주 완료 주 총합)
        week_trend = []
        for w in range(8, 0, -1):
            ws = (today - timedelta(days=today.weekday())) - timedelta(days=7 * w)
            we = ws + timedelta(days=6)
            wt, _ = total(ws, we)
            week_trend.append({'label': f'{ws:%m/%d}', 'total': wt})

        # 요일별 평균 (최근 28일)
        dow_sum = [0] * 7
        dow_cnt = [0] * 7
        for i in range(1, 29):
            d = today - timedelta(days=i)
            dow_sum[d.weekday()] += counts.get(d, 0)
            dow_cnt[d.weekday()] += 1
        dow_avg = [round(dow_sum[i] / dow_cnt[i], 1) if dow_cnt[i] else 0 for i in range(7)]

        # 최근 30일 일평균
        m30_total, _ = total(today - timedelta(days=30), yest)
        avg_30d = round(m30_total / 30, 1)

        # 누적 총 방문자 (전체) + 피크
        cumulative = DailyVisitor.objects.aggregate(s=Sum('visitor_count'))['s'] or 0
        peak_row = (DailyVisitor.objects.order_by('-visitor_count')
                    .values('date', 'visitor_count').first())

        return {
            'period': period,
            'range_start': cur_start, 'range_end': cur_end,
            'cur_total': cur_total, 'cur_avg': cur_avg, 'cur_days': cur_days,
            'prev_total': prev_total, 'prev_avg': prev_avg,
            'prev_start': prev_start, 'prev_end': prev_end,
            'yest': yest, 'yest_count': yest_count, 'same_dow_prev': same_dow_prev,
            'last7': last7, 'week_trend': week_trend, 'dow_avg': dow_avg,
            'avg_30d': avg_30d, 'cumulative': cumulative, 'peak': peak_row,
            'launch_days': max((date.today() - LAUNCH_DATE).days, 0),
        }

    # ------------------------------------------------------------------ #
    #  Google Search Console (선택 — 미설정/미설치 시 조용히 비활성)
    # ------------------------------------------------------------------ #
    GSC_SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']

    def _gsc_credentials(self):
        """OAuth 토큰(우선) 또는 서비스 계정 키로 자격증명을 만든다.

        반환: (credentials, None) 성공 / (None, 사유) 실패.
        OAuth 토큰은 만료 시 refresh token으로 자동 갱신하고 파일에 다시 저장한다.
        """
        oauth_path = getattr(settings, 'GSC_OAUTH_TOKEN', '')
        sa_path = getattr(settings, 'GSC_CREDENTIALS_JSON', '')

        # 1) OAuth 2.0 클라이언트 토큰 (authorized_user)
        if oauth_path and os.path.exists(oauth_path):
            try:
                from google.oauth2.credentials import Credentials
                from google.auth.transport.requests import Request
                creds = Credentials.from_authorized_user_file(oauth_path, self.GSC_SCOPES)
                if not creds.valid and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(oauth_path, 'w', encoding='utf-8') as f:
                        f.write(creds.to_json())  # 갱신된 access token 보존
                return creds, None
            except Exception as ex:
                return None, f'OAuth 토큰 오류: {ex}'

        # 2) 서비스 계정 키
        if sa_path and os.path.exists(sa_path):
            try:
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_file(
                    sa_path, scopes=self.GSC_SCOPES)
                return creds, None
            except Exception as ex:
                return None, f'서비스계정 키 오류: {ex}'

        return None, '미설정'

    def _collect_gsc(self, start, end):
        site_url = getattr(settings, 'GSC_SITE_URL', '')
        if not site_url:
            return {'available': False, 'reason': '미설정'}

        creds, reason = self._gsc_credentials()
        if creds is None:
            return {'available': False, 'reason': reason}

        try:
            from googleapiclient.discovery import build
        except Exception:
            return {'available': False, 'reason': '라이브러리 미설치'}

        try:
            svc = build('searchconsole', 'v1', credentials=creds, cache_discovery=False)
            s, e = start.isoformat(), end.isoformat()

            def query(body):
                return svc.searchanalytics().query(siteUrl=site_url, body=body).execute()

            totals = query({'startDate': s, 'endDate': e}).get('rows', [])
            t = totals[0] if totals else {}

            # 직전 동일 길이 기간 (증감 비교용)
            span = (end - start).days + 1
            pe = start - timedelta(days=1)
            ps = pe - timedelta(days=span - 1)
            ptotals = query({'startDate': ps.isoformat(), 'endDate': pe.isoformat()}).get('rows', [])
            pt = ptotals[0] if ptotals else {}

            top_q = query({'startDate': s, 'endDate': e,
                           'dimensions': ['query'], 'rowLimit': 5}).get('rows', [])
            top_p = query({'startDate': s, 'endDate': e,
                           'dimensions': ['page'], 'rowLimit': 5}).get('rows', [])

            return {
                'available': True,
                'clicks': t.get('clicks', 0), 'impressions': t.get('impressions', 0),
                'ctr': t.get('ctr', 0), 'position': t.get('position', 0),
                'prev_clicks': pt.get('clicks', 0), 'prev_impressions': pt.get('impressions', 0),
                'prev_ctr': pt.get('ctr', 0), 'prev_position': pt.get('position', 0),
                'top_queries': [{'k': r['keys'][0], 'clicks': r.get('clicks', 0),
                                 'impr': r.get('impressions', 0), 'ctr': r.get('ctr', 0)}
                                for r in top_q],
                'top_pages': [{'k': r['keys'][0], 'clicks': r.get('clicks', 0),
                               'impr': r.get('impressions', 0)} for r in top_p],
            }
        except Exception as ex:
            self.stderr.write(self.style.WARNING(f'GSC 수집 건너뜀: {ex}'))
            return {'available': False, 'reason': str(ex)}

    # ------------------------------------------------------------------ #
    #  표시 헬퍼
    # ------------------------------------------------------------------ #
    @staticmethod
    def _pct(cur, prev):
        """증감률 텍스트 (없으면 '–')."""
        if not prev:
            return '–'
        diff = (cur - prev) / prev * 100
        arrow = '▲' if diff > 0 else ('▼' if diff < 0 else '–')
        return f'{arrow} {diff:+.0f}%'

    @staticmethod
    def _bar(value, maxv, width=13):
        filled = int(round((value / maxv) * width)) if maxv else 0
        filled = max(0, min(width, filled))
        return '█' * filled + '░' * (width - filled)

    def _delta_color(self, cur, prev, lower_is_better=False):
        if not prev or cur == prev:
            return '#a1a1aa'
        up = cur > prev
        good = (not up) if lower_is_better else up
        return '#16a34a' if good else '#dc2626'

    # ------------------------------------------------------------------ #
    #  텍스트 렌더
    # ------------------------------------------------------------------ #
    def _render_text(self, period, d, gsc):
        label = '주간' if period == 'weekly' else '월간'
        unit = '주' if period == 'weekly' else '달'
        L = [
            f'[테크창] 방문자 {label} 리포트',
            f'기간: {d["range_start"]:%Y-%m-%d} ~ {d["range_end"]:%Y-%m-%d} ({d["cur_days"]}일)',
            '=' * 50, '',
            '[한눈에 보기]',
            f'  어제 방문자   : {d["yest_count"]:,}명  ({self._pct(d["yest_count"], d["same_dow_prev"])} 전주 동요일)',
            f'  이번 {unit} 총합 : {d["cur_total"]:,}명  ({self._pct(d["cur_total"], d["prev_total"])} 지난 {unit} {d["prev_total"]:,})',
            f'  이번 {unit} 일평균: {d["cur_avg"]:,}명  ({self._pct(d["cur_avg"], d["prev_avg"])})',
            f'  최근 30일 일평균: {d["avg_30d"]:,}명',
            f'  누적 방문자   : {d["cumulative"]:,}명  (런칭 {d["launch_days"]}일째)',
        ]
        if d['peak']:
            L.append(f'  최고 방문일   : {d["peak"]["date"]:%Y-%m-%d} ({d["peak"]["visitor_count"]:,}명)')

        maxv = max((c for _, c in d['last7']), default=0)
        L += ['', '[최근 7일 추세]']
        for dt, c in d['last7']:
            L.append(f'  {dt:%m/%d}({WEEKDAY_KR[dt.weekday()]}) {self._bar(c, maxv)} {c:,}')

        maxw = max((w['total'] for w in d['week_trend']), default=0)
        L += ['', '[주차별 추이 (최근 8주)]']
        for w in d['week_trend']:
            L.append(f'  {w["label"]}주 {self._bar(w["total"], maxw)} {w["total"]:,}')

        L += ['', '[요일별 평균 (최근 28일)]']
        L.append('  ' + ' / '.join(f'{WEEKDAY_KR[i]} {d["dow_avg"][i]:g}' for i in range(7)))

        if gsc.get('available'):
            L += ['', '[Google Search Console]',
                  f'  노출수    : {gsc["impressions"]:,.0f}  ({self._pct(gsc["impressions"], gsc["prev_impressions"])})',
                  f'  클릭수    : {gsc["clicks"]:,.0f}  ({self._pct(gsc["clicks"], gsc["prev_clicks"])})',
                  f'  평균 CTR  : {gsc["ctr"]*100:.2f}%  ({self._pct(gsc["ctr"], gsc["prev_ctr"])})',
                  f'  평균 순위 : {gsc["position"]:.1f}위  (낮을수록 좋음)']
            if gsc['top_queries']:
                L.append('  상위 검색어:')
                for q in gsc['top_queries']:
                    L.append(f'    - {q["k"][:30]} (클릭 {q["clicks"]:.0f}, CTR {q["ctr"]*100:.1f}%)')
        elif gsc.get('reason') and gsc['reason'] != '미설정':
            L += ['', f'[GSC] 수집 건너뜀: {gsc["reason"]}']

        L += ['', '-' * 50, 'techchang.com 자동 발송 · 방문자 리포트']
        return '\n'.join(L)

    # ------------------------------------------------------------------ #
    #  HTML 렌더
    # ------------------------------------------------------------------ #
    _STYLE = """
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans KR',sans-serif;
       background:#fafafa;margin:0;padding:20px;color:#3f3f46;-webkit-font-smoothing:antialiased;}
  .wrap{max-width:640px;margin:0 auto;}
  .card{background:#fff;border:1px solid #e8e8eb;border-radius:14px;padding:22px 24px;
        margin-bottom:14px;box-shadow:0 1px 2px rgba(16,24,40,.04);}
  h1{font-size:1.0625rem;font-weight:800;letter-spacing:-.02em;color:#fff;margin:0 0 4px;}
  h2{font-size:.8125rem;font-weight:700;color:#18181b;margin:0 0 14px;padding-bottom:9px;
     border-bottom:1px solid #f0f0f1;letter-spacing:.01em;}
  .sub{font-size:.8125rem;color:rgba(255,255,255,.75);}
  .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
  .stat{background:#fafafa;border:1px solid #f0f0f1;border-radius:10px;padding:12px;text-align:center;}
  .stat-num{font-size:1.375rem;font-weight:800;letter-spacing:-.02em;color:#059669;}
  .stat-label{font-size:.6875rem;color:#a1a1aa;margin-top:3px;}
  .stat-delta{font-size:.6875rem;font-weight:700;margin-top:2px;}
  .row{display:flex;justify-content:space-between;gap:10px;padding:7px 0;
       border-bottom:1px solid #f4f4f5;font-size:.8125rem;color:#3f3f46;}
  .row:last-child{border:none;}
  .bar{font-family:monospace;font-size:11px;color:#059669;letter-spacing:-1px;}
  .muted{color:#a1a1aa;}
  a{color:#059669;text-decoration:none;}
"""

    def _stat(self, num, label, delta='', color='#a1a1aa'):
        delta_html = f'<div class="stat-delta" style="color:{color};">{delta}</div>' if delta else ''
        return (f'<div class="stat"><div class="stat-num">{num}</div>'
                f'<div class="stat-label">{label}</div>{delta_html}</div>')

    def _render_html(self, period, d, gsc):
        label = '주간' if period == 'weekly' else '월간'
        unit = '주' if period == 'weekly' else '달'

        # 한눈에 보기 카드
        tot_delta = self._pct(d['cur_total'], d['prev_total'])
        avg_delta = self._pct(d['cur_avg'], d['prev_avg'])
        yest_delta = self._pct(d['yest_count'], d['same_dow_prev'])
        overview = (
            '<div class="grid" style="margin-bottom:12px;">'
            + self._stat(f'{d["yest_count"]:,}', '어제 방문자', yest_delta,
                         self._delta_color(d['yest_count'], d['same_dow_prev']))
            + self._stat(f'{d["cur_total"]:,}', f'이번 {unit} 총합', tot_delta,
                         self._delta_color(d['cur_total'], d['prev_total']))
            + self._stat(f'{d["cur_avg"]:g}', f'이번 {unit} 일평균', avg_delta,
                         self._delta_color(d['cur_avg'], d['prev_avg']))
            + '</div>'
            + f'<div class="row"><span>최근 30일 일평균</span><span>{d["avg_30d"]:g}명</span></div>'
            + f'<div class="row"><span>누적 방문자</span><span>{d["cumulative"]:,}명 '
              f'<span class="muted">(런칭 {d["launch_days"]}일째)</span></span></div>'
        )
        if d['peak']:
            overview += (f'<div class="row"><span>최고 방문일</span><span>'
                         f'{d["peak"]["date"]:%Y-%m-%d} ({d["peak"]["visitor_count"]:,}명)</span></div>')

        # 최근 7일
        maxv = max((c for _, c in d['last7']), default=0)
        last7 = ''.join(
            f'<div class="row"><span>{dt:%m/%d}({WEEKDAY_KR[dt.weekday()]})</span>'
            f'<span><span class="bar">{self._bar(c, maxv)}</span> {c:,}</span></div>'
            for dt, c in d['last7'])

        # 주차별 추이
        maxw = max((w['total'] for w in d['week_trend']), default=0)
        weeks = ''.join(
            f'<div class="row"><span>{w["label"]}주</span>'
            f'<span><span class="bar">{self._bar(w["total"], maxw)}</span> {w["total"]:,}</span></div>'
            for w in d['week_trend'])

        # 요일별 평균
        dow = ''.join(
            f'<div class="row"><span>{WEEKDAY_KR[i]}요일</span><span>{d["dow_avg"][i]:g}명</span></div>'
            for i in range(7))

        # GSC 카드
        gsc_card = ''
        if gsc.get('available'):
            gsc_card = (
                '<div class="card"><h2>Google Search Console</h2>'
                '<div class="grid" style="margin-bottom:12px;">'
                + self._stat(f'{gsc["impressions"]:,.0f}', '노출수',
                             self._pct(gsc['impressions'], gsc['prev_impressions']),
                             self._delta_color(gsc['impressions'], gsc['prev_impressions']))
                + self._stat(f'{gsc["clicks"]:,.0f}', '클릭수',
                             self._pct(gsc['clicks'], gsc['prev_clicks']),
                             self._delta_color(gsc['clicks'], gsc['prev_clicks']))
                + self._stat(f'{gsc["ctr"]*100:.2f}%', '평균 CTR',
                             self._pct(gsc['ctr'], gsc['prev_ctr']),
                             self._delta_color(gsc['ctr'], gsc['prev_ctr']))
                + '</div>'
                + f'<div class="row"><span>평균 게재순위</span><span>{gsc["position"]:.1f}위 '
                  f'<span class="muted">(낮을수록 좋음)</span></span></div>'
            )
            if gsc['top_queries']:
                gsc_card += '<h2 style="margin-top:16px;">상위 검색어</h2>'
                for q in gsc['top_queries']:
                    gsc_card += (f'<div class="row"><span>{q["k"][:34]}</span>'
                                 f'<span class="muted">클릭 {q["clicks"]:.0f} · CTR {q["ctr"]*100:.1f}%</span></div>')
            if gsc['top_pages']:
                gsc_card += '<h2 style="margin-top:16px;">상위 유입 페이지</h2>'
                for p in gsc['top_pages']:
                    path = p['k'].replace('https://techchang.com', '').replace('sc-domain:', '') or '/'
                    gsc_card += (f'<div class="row"><span>{path[:34]}</span>'
                                 f'<span class="muted">클릭 {p["clicks"]:.0f} · 노출 {p["impr"]:.0f}</span></div>')
            gsc_card += '</div>'

        return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>{self._STYLE}</style></head>
<body><div class="wrap">
<div class="card" style="background:#065f46;border:none;padding:20px 24px;">
  <h1>📊 테크창 방문자 {label} 리포트</h1>
  <div class="sub">{d["range_start"]:%Y-%m-%d} ~ {d["range_end"]:%Y-%m-%d} ({d["cur_days"]}일)</div>
</div>
<div class="card"><h2>한눈에 보기</h2>{overview}</div>
<div class="card"><h2>최근 7일 추세</h2>{last7}</div>
<div class="card"><h2>주차별 추이 (최근 8주 총합)</h2>{weeks}</div>
<div class="card"><h2>요일별 평균 (최근 28일)</h2>{dow}</div>
{gsc_card}
<div style="text-align:center;font-size:.75rem;color:#a1a1aa;margin-top:6px;padding-bottom:8px;">
  자동 발송 · 방문자 리포트 | <a href="https://techchang.com">사이트 바로가기</a>
</div>
</div></body></html>"""
