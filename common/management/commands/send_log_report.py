"""
서버 로그 요약 이메일 리포트
사용법: python manage.py send_log_report [--hours 24] [--to admin@example.com]
크론탭: 0 8 * * * /path/to/venv/bin/python manage.py send_log_report
"""
import subprocess
import re
import os
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone


class Command(BaseCommand):
    help = '서버 로그를 분석하고 요약 이메일을 발송합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours', type=int, default=24,
            help='분석할 시간 범위 (기본: 24시간)'
        )
        parser.add_argument(
            '--to', type=str, default='',
            help='수신자 이메일 (기본: DJANGO_ADMIN_EMAIL 환경변수)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='이메일 발송 없이 콘솔에 출력만'
        )

    def handle(self, *args, **options):
        hours = options['hours']
        dry_run = options['dry_run']
        recipient = (
            options['to']
            or os.environ.get('DJANGO_ADMIN_EMAIL', '')
            or getattr(settings, 'ADMINS', [('', '')])[0][1]
        )

        if not recipient:
            self.stderr.write(self.style.ERROR(
                '수신자 이메일이 설정되지 않았습니다. --to 옵션 또는 DJANGO_ADMIN_EMAIL 환경변수를 설정하세요.'
            ))
            return

        self.stdout.write(f'[{datetime.now():%Y-%m-%d %H:%M}] 로그 분석 시작 ({hours}시간)...')
        report = self._build_report(hours)

        if dry_run:
            self.stdout.write('\n' + '=' * 60)
            self.stdout.write(report['text'])
            self.stdout.write('=' * 60)
        else:
            subject = f'[테크창] 서버 리포트 {datetime.now():%Y-%m-%d %H:%M} ({hours}h)'
            send_mail(
                subject=subject,
                message=report['text'],
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                html_message=report['html'],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(f'리포트 발송 완료 → {recipient}'))

    # ------------------------------------------------------------------ #
    def _build_report(self, hours):
        since = datetime.now() - timedelta(hours=hours)
        db_stats       = self._collect_db_stats()
        journal_stats  = self._collect_journal(hours)
        security_stats = self._collect_security_logs(hours)
        sys_stats      = self._collect_system_stats()

        html = self._render_html(since, hours, db_stats, journal_stats, security_stats, sys_stats)
        text = self._render_text(since, hours, db_stats, journal_stats, security_stats, sys_stats)
        return {'html': html, 'text': text}

    # ------------------------------------------------------------------ #
    def _collect_db_stats(self):
        from community.models import Question, Answer, Comment
        from common.models import Profile

        now   = timezone.now()
        today = now.date()

        stats = {}
        try:
            stats['total_users']      = User.objects.count()
            stats['new_users_today']  = User.objects.filter(date_joined__date=today).count()
            stats['active_users_7d']  = User.objects.filter(
                last_login__date__gte=today - timedelta(days=7)
            ).count()
            stats['active_users_30d'] = User.objects.filter(
                last_login__date__gte=today - timedelta(days=30)
            ).count()

            stats['total_questions'] = Question.objects.filter(is_deleted=False).count()
            stats['new_questions']   = Question.objects.filter(
                is_deleted=False, create_date__date=today
            ).count()
            stats['total_answers']   = Answer.objects.filter(is_deleted=False).count()
            stats['new_answers']     = Answer.objects.filter(
                is_deleted=False, create_date__date=today
            ).count()
            stats['total_comments']     = Comment.objects.count()
            stats['new_comments_today'] = Comment.objects.filter(create_date__date=today).count()

            # 방문자 수
            try:
                from community.models import DailyVisitor
                vc  = DailyVisitor.objects.filter(date=today).first()
                yvc = DailyVisitor.objects.filter(date=today - timedelta(days=1)).first()
                stats['visitors_today']     = vc.visitor_count  if vc  else 0
                stats['visitors_yesterday'] = yvc.visitor_count if yvc else 0
            except Exception:
                stats['visitors_today']     = '-'
                stats['visitors_yesterday'] = '-'

            # 게임 플레이 수 (오늘)
            try:
                from community.models import NumberBaseballGame, Game2048, MinesweeperGame, TicTacToeGame
                b = NumberBaseballGame.objects.filter(create_date__date=today).count()
                g = Game2048.objects.filter(create_date__date=today).count()
                m = MinesweeperGame.objects.filter(create_date__date=today).count()
                t = TicTacToeGame.objects.filter(create_date__date=today).count()
                stats['game_plays_today'] = b + g + m + t
                stats['game_detail'] = {'숫자야구': b, '2048': g, '지뢰찾기': m, '틱택토': t}
            except Exception:
                stats['game_plays_today'] = '-'
                stats['game_detail'] = {}

            # 인기 질문 Top 5
            try:
                stats['top_questions'] = list(
                    Question.objects.filter(is_deleted=False)
                    .order_by('-view_count')[:5]
                    .values('subject', 'view_count')
                )
            except Exception:
                stats['top_questions'] = []

        except Exception as e:
            stats['error'] = str(e)

        return stats

    # ------------------------------------------------------------------ #
    def _collect_journal(self, hours):
        stats = {
            'error_count': 0,
            'warning_count': 0,
            'request_count': 0,
            'status_5xx': 0,
            'status_4xx': 0,
            'top_errors': [],
            'available': False,
        }
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'mysite', f'--since={hours} hours ago',
                 '--no-pager', '-o', 'short'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                return stats

            lines = result.stdout.splitlines()
            stats['available'] = True
            errors = []

            for line in lines:
                lower = line.lower()
                if 'error' in lower or 'exception' in lower or 'traceback' in lower:
                    stats['error_count'] += 1
                    errors.append(line[-120:])
                elif 'warning' in lower or 'warn' in lower:
                    stats['warning_count'] += 1

                m = re.search(r'"[A-Z]+ .+?" (\d{3})', line)
                if m:
                    code = int(m.group(1))
                    stats['request_count'] += 1
                    if 500 <= code < 600:
                        stats['status_5xx'] += 1
                    elif 400 <= code < 500:
                        stats['status_4xx'] += 1

            seen = set()
            for e in errors:
                key = e[-60:]
                if key not in seen:
                    seen.add(key)
                    stats['top_errors'].append(e)
                    if len(stats['top_errors']) >= 5:
                        break

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        if stats['available'] and stats['request_count'] == 0:
            stats.update(self._collect_nginx_access(hours, stats))

        return stats

    # ------------------------------------------------------------------ #
    def _collect_nginx_access(self, hours, existing_stats):
        from datetime import timezone as tz

        candidates = [
            '/var/log/nginx/techchang_access.log',
            '/var/log/nginx/mysite_access.log',
            '/var/log/nginx/access.log',
        ]

        cutoff = datetime.now(tz.utc).replace(tzinfo=None) - timedelta(hours=hours)
        date_pat = re.compile(r'\[(\d{2}/\w+/\d{4}:\d{2}:\d{2}:\d{2})')
        month_map = {
            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
        }

        req_count = status_5xx = status_4xx = 0

        for log_path in candidates:
            if not os.path.exists(log_path):
                continue
            try:
                with open(log_path, 'r', errors='replace') as f:
                    for line in f:
                        dm = date_pat.search(line)
                        if dm:
                            raw   = dm.group(1)
                            parts = raw.split('/')
                            day   = int(parts[0])
                            mon   = month_map.get(parts[1], 0)
                            rest  = parts[2].split(':')
                            year  = int(rest[0])
                            h, mi, s = int(rest[1]), int(rest[2]), int(rest[3])
                            log_dt = datetime(year, mon, day, h, mi, s)
                            if log_dt < cutoff:
                                continue

                        sm = re.search(r'"[A-Z]+ .+?" (\d{3})', line)
                        if sm:
                            code = int(sm.group(1))
                            req_count += 1
                            if 500 <= code < 600:
                                status_5xx += 1
                            elif 400 <= code < 500:
                                status_4xx += 1
            except OSError:
                continue
            break

        return {
            'request_count': req_count,
            'status_5xx': existing_stats.get('status_5xx', 0) + status_5xx,
            'status_4xx': existing_stats.get('status_4xx', 0) + status_4xx,
        }

    # ------------------------------------------------------------------ #
    def _collect_security_logs(self, hours):
        stats = {
            'blocked_ips': 0,
            'rate_limit_hits': 0,
            'ddos_detected': 0,
            'available': False,
        }
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'mysite', f'--since={hours} hours ago',
                 '--no-pager', '-o', 'short', '--grep',
                 r'blocked\|rate limit\|DDoS\|suspicious'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                return stats

            lines = result.stdout.splitlines()
            stats['available'] = True

            for line in lines:
                lower = line.lower()
                if 'blocked' in lower:
                    stats['blocked_ips'] += 1
                if 'rate limit' in lower:
                    stats['rate_limit_hits'] += 1
                if 'ddos' in lower:
                    stats['ddos_detected'] += 1

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return stats

    # ------------------------------------------------------------------ #
    def _collect_system_stats(self):
        stats = {}
        try:
            mem = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=5)
            for line in mem.stdout.splitlines():
                if line.startswith('Mem:'):
                    parts = line.split()
                    total, used = int(parts[1]), int(parts[2])
                    stats['mem_total_mb'] = total
                    stats['mem_used_mb']  = used
                    stats['mem_pct']      = round(used / total * 100, 1)
                    break

            df = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=5)
            for line in df.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    stats['disk_total'] = parts[1]
                    stats['disk_used']  = parts[2]
                    stats['disk_pct']   = parts[4]
                    break

            uptime = subprocess.run(['uptime'], capture_output=True, text=True, timeout=5)
            m = re.search(r'load average[s]?:\s+([\d.]+)', uptime.stdout)
            if m:
                stats['load_avg'] = m.group(1)

            svc = subprocess.run(['systemctl', 'is-active', 'mysite'],
                                 capture_output=True, text=True, timeout=5)
            stats['mysite_status'] = svc.stdout.strip()

            nginx = subprocess.run(['systemctl', 'is-active', 'nginx'],
                                   capture_output=True, text=True, timeout=5)
            stats['nginx_status'] = nginx.stdout.strip()

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass

        return stats

    # ------------------------------------------------------------------ #
    def _ok(self, ok=True):
        """상태 표시 - 이모지 없이 컬러 텍스트"""
        if ok:
            return '<span style="color:#16a34a;font-weight:700;">정상</span>'
        return '<span style="color:#dc2626;font-weight:700;">오류</span>'

    def _warn_span(self, value, warn=70, danger=90):
        """수치 기반 상태 컬러"""
        if value >= danger:
            return f'<span style="color:#dc2626;font-weight:700;">{value}%</span>'
        if value >= warn:
            return f'<span style="color:#ca8a04;font-weight:700;">{value}%</span>'
        return f'<span style="color:#16a34a;">{value}%</span>'

    def _render_html(self, since, hours, db, journal, security, sys):
        now_str   = datetime.now().strftime('%Y-%m-%d %H:%M')
        since_str = since.strftime('%Y-%m-%d %H:%M')

        mysite_ok = sys.get('mysite_status', '') == 'active'
        nginx_ok  = sys.get('nginx_status', '') == 'active'
        mem_pct   = sys.get('mem_pct', 0)
        disk_str  = sys.get('disk_pct', '0%').replace('%', '')
        disk_int  = int(disk_str) if disk_str.isdigit() else 0

        # 로그 분석 섹션
        if journal.get('available'):
            has_5xx = journal.get('status_5xx', 0) > 0
            journal_html = (
                '<div class="row"><span>총 요청 수</span>'
                '<span>{:,}</span></div>'.format(journal.get('request_count', 0)) +
                '<div class="row"><span>5xx 에러</span>'
                '<span style="color:{};">{}</span></div>'.format(
                    '#dc2626' if has_5xx else '#16a34a', journal.get('status_5xx', 0)
                ) +
                '<div class="row"><span>4xx 에러</span>'
                '<span>{:,}</span></div>'.format(journal.get('status_4xx', 0)) +
                '<div class="row"><span>Warning</span>'
                '<span>{}</span></div>'.format(journal.get('warning_count', 0)) +
                '<div class="row"><span>Error/Exception</span>'
                '<span style="color:{};">{}</span></div>'.format(
                    '#dc2626' if journal.get('error_count', 0) > 0 else '#374151',
                    journal.get('error_count', 0)
                )
            )
        else:
            journal_html = '<div style="color:#6b7280;font-size:0.875rem;">journalctl 접근 불가 (로컬 환경)</div>'

        # 보안 섹션
        if security.get('available'):
            security_html = (
                '<div class="row"><span>IP 차단</span>'
                '<span style="color:{};">{}</span></div>'.format(
                    '#dc2626' if security.get('blocked_ips', 0) > 5 else '#374151',
                    security.get('blocked_ips', 0)
                ) +
                '<div class="row"><span>Rate Limit 발동</span>'
                '<span>{}</span></div>'.format(security.get('rate_limit_hits', 0)) +
                '<div class="row"><span>DDoS 감지</span>'
                '<span style="color:{};">{}</span></div>'.format(
                    '#dc2626' if security.get('ddos_detected', 0) > 0 else '#374151',
                    security.get('ddos_detected', 0)
                )
            )
        else:
            security_html = '<div style="color:#6b7280;font-size:0.875rem;">journalctl 접근 불가</div>'

        # 에러 로그
        errors_html = ''
        for e in journal.get('top_errors', []):
            errors_html += (
                '<li style="font-family:monospace;font-size:11px;color:#dc2626;margin-bottom:4px;">'
                + e + '</li>'
            )
        errors_card = ''
        if journal.get('available') and errors_html:
            errors_card = (
                '<div class="card"><h2>최근 에러 로그</h2>'
                '<ul style="margin:0;padding-left:16px;">' + errors_html + '</ul></div>'
            )

        # 게임 플레이 상세
        game_detail_html = ''
        for name, cnt in db.get('game_detail', {}).items():
            game_detail_html += (
                '<div class="row"><span>{}</span><span>{}</span></div>'.format(name, cnt)
            )

        # 인기 질문 Top 5
        top_q_html = ''
        for i, q in enumerate(db.get('top_questions', []), 1):
            subj = q.get('subject', '')[:40]
            vc   = q.get('view_count', 0)
            top_q_html += (
                '<div class="row">'
                '<span style="color:#374151;">{i}. {subj}</span>'
                '<span style="color:#6b7280;">{vc:,}회</span>'
                '</div>'.format(i=i, subj=subj, vc=vc)
            )
        if not top_q_html:
            top_q_html = '<div style="color:#6b7280;">데이터 없음</div>'

        return """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><style>
  body {{ font-family: -apple-system, sans-serif; background:#f3f4f6; margin:0; padding:20px; }}
  .card {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
  h1 {{ font-size:1.125rem; font-weight:800; color:#111; margin:0 0 4px; }}
  h2 {{ font-size:0.875rem; font-weight:700; color:#374151; margin:0 0 14px;
        border-bottom:1px solid #e5e7eb; padding-bottom:8px; letter-spacing:.02em; }}
  .sub {{ font-size:0.8125rem; color:#6b7280; }}
  .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
  .grid4 {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
  .stat {{ background:#f9fafb; border-radius:8px; padding:12px; text-align:center; }}
  .stat-num {{ font-size:1.375rem; font-weight:800; color:#3b82f6; }}
  .stat-num.g {{ color:#16a34a; }}
  .stat-label {{ font-size:0.6875rem; color:#6b7280; margin-top:2px; }}
  .row {{ display:flex; justify-content:space-between; padding:6px 0;
          border-bottom:1px solid #f3f4f6; font-size:0.8125rem; color:#374151; }}
  .row:last-child {{ border:none; }}
</style></head>
<body>
<div class="card" style="background:#1e40af; color:#fff; padding:20px 24px;">
  <h1 style="color:#fff; font-size:1rem;">테크창 서버 리포트</h1>
  <div class="sub" style="color:rgba(255,255,255,.75);">{since_str} ~ {now_str} ({hours}h)</div>
</div>

<div class="card">
  <h2>서비스 상태</h2>
  <div class="row"><span>Django (mysite)</span><span>{mysite_icon}</span></div>
  <div class="row"><span>Nginx</span><span>{nginx_icon}</span></div>
  <div class="row"><span>CPU 부하 (Load Avg)</span><span>{load_avg}</span></div>
  <div class="row"><span>메모리</span><span>{mem_span} ({mem_used}/{mem_total} MB)</span></div>
  <div class="row"><span>디스크</span><span>{disk_span} ({disk_used}/{disk_total})</span></div>
</div>

<div class="card">
  <h2>DB 현황 (오늘)</h2>
  <div class="grid" style="margin-bottom:12px;">
    <div class="stat"><div class="stat-num">{total_users}</div><div class="stat-label">전체 회원</div></div>
    <div class="stat"><div class="stat-num g">+{new_users}</div><div class="stat-label">신규 가입</div></div>
    <div class="stat"><div class="stat-num">{visitors}</div><div class="stat-label">오늘 방문자</div></div>
    <div class="stat"><div class="stat-num">{total_q}</div><div class="stat-label">전체 질문</div></div>
    <div class="stat"><div class="stat-num g">+{new_q}</div><div class="stat-label">오늘 질문</div></div>
    <div class="stat"><div class="stat-num g">+{new_a}</div><div class="stat-label">오늘 답변</div></div>
  </div>
  <div class="row"><span>오늘 댓글</span><span>+{new_comments}</span></div>
  <div class="row"><span>전체 댓글</span><span>{total_comments:,}</span></div>
</div>

<div class="card">
  <h2>사용자 활동</h2>
  <div class="grid" style="margin-bottom:12px;">
    <div class="stat"><div class="stat-num">{active_7d}</div><div class="stat-label">7일 활성 유저</div></div>
    <div class="stat"><div class="stat-num">{active_30d}</div><div class="stat-label">30일 활성 유저</div></div>
    <div class="stat"><div class="stat-num">{game_plays}</div><div class="stat-label">오늘 게임 플레이</div></div>
  </div>
  {game_detail_html}
</div>

<div class="card">
  <h2>인기 질문 Top 5</h2>
  {top_q_html}
</div>

<div class="card">
  <h2>로그 분석 ({hours}h)</h2>
  {journal_html}
</div>

<div class="card">
  <h2>보안 이벤트 ({hours}h)</h2>
  {security_html}
</div>

{errors_card}

<div style="text-align:center;font-size:0.75rem;color:#9ca3af;margin-top:8px;">
  자동 발송 — techchang.com | <a href="https://techchang.com" style="color:#3b82f6;">사이트 바로가기</a>
</div>
</body></html>""".format(
            since_str=since_str, now_str=now_str, hours=hours,
            mysite_icon=self._ok(mysite_ok),
            nginx_icon=self._ok(nginx_ok),
            load_avg=sys.get('load_avg', '-'),
            mem_span=self._warn_span(mem_pct),
            mem_used=sys.get('mem_used_mb', '-'), mem_total=sys.get('mem_total_mb', '-'),
            disk_span=self._warn_span(disk_int),
            disk_used=sys.get('disk_used', '-'), disk_total=sys.get('disk_total', '-'),
            total_users=db.get('total_users', '-'),
            new_users=db.get('new_users_today', 0),
            visitors=db.get('visitors_today', '-'),
            total_q=db.get('total_questions', '-'),
            new_q=db.get('new_questions', 0),
            new_a=db.get('new_answers', 0),
            new_comments=db.get('new_comments_today', 0),
            total_comments=db.get('total_comments', 0),
            active_7d=db.get('active_users_7d', '-'),
            active_30d=db.get('active_users_30d', '-'),
            game_plays=db.get('game_plays_today', '-'),
            game_detail_html=game_detail_html,
            top_q_html=top_q_html,
            journal_html=journal_html,
            security_html=security_html,
            errors_card=errors_card,
        )

    def _render_text(self, since, hours, db, journal, security, sys):
        now_str = since.strftime('%Y-%m-%d %H:%M') + ' ~ ' + datetime.now().strftime('%H:%M')
        lines = [
            f'[테크창] 서버 리포트 ({now_str}, {hours}h)',
            '=' * 50,
            '',
            '[서비스 상태]',
            f'  Django : {sys.get("mysite_status", "unknown")}',
            f'  Nginx  : {sys.get("nginx_status", "unknown")}',
            f'  CPU 부하: {sys.get("load_avg", "-")}',
            f'  메모리  : {sys.get("mem_used_mb", "-")}/{sys.get("mem_total_mb", "-")} MB ({sys.get("mem_pct", "-")}%)',
            f'  디스크  : {sys.get("disk_used", "-")}/{sys.get("disk_total", "-")} ({sys.get("disk_pct", "-")})',
            '',
            '[DB 현황]',
            f'  전체 회원    : {db.get("total_users", "-")} (신규 +{db.get("new_users_today", 0)})',
            f'  오늘 방문자  : {db.get("visitors_today", "-")} (어제 {db.get("visitors_yesterday", "-")})',
            f'  전체 질문    : {db.get("total_questions", "-")} (오늘 +{db.get("new_questions", 0)})',
            f'  전체 답변    : {db.get("total_answers", "-")} (오늘 +{db.get("new_answers", 0)})',
            f'  오늘 댓글    : +{db.get("new_comments_today", 0)} (전체 {db.get("total_comments", 0):,})',
            '',
            '[사용자 활동]',
            f'  7일 활성 유저  : {db.get("active_users_7d", "-")}명',
            f'  30일 활성 유저 : {db.get("active_users_30d", "-")}명',
            f'  오늘 게임 플레이: {db.get("game_plays_today", "-")}회',
        ]

        game_detail = db.get('game_detail', {})
        for name, cnt in game_detail.items():
            lines.append(f'    - {name}: {cnt}회')

        top_q = db.get('top_questions', [])
        if top_q:
            lines += ['', '[인기 질문 Top 5]']
            for i, q in enumerate(top_q, 1):
                subj = q.get('subject', '')[:45]
                vc   = q.get('view_count', 0)
                lines.append(f'  {i}. {subj} ({vc:,}회)')

        lines.append('')

        if journal.get('available'):
            lines += [
                '[로그 분석]',
                f'  총 요청    : {journal.get("request_count", 0):,}',
                f'  5xx 에러   : {journal.get("status_5xx", 0)}',
                f'  4xx 에러   : {journal.get("status_4xx", 0):,}',
                f'  Warning    : {journal.get("warning_count", 0)}',
                f'  Error/Exc  : {journal.get("error_count", 0)}',
                '',
                '[보안 이벤트]',
                f'  IP 차단    : {security.get("blocked_ips", 0)}',
                f'  Rate Limit : {security.get("rate_limit_hits", 0)}',
                f'  DDoS 감지  : {security.get("ddos_detected", 0)}',
                '',
            ]
            if journal.get('top_errors'):
                lines.append('[최근 에러]')
                for e in journal['top_errors']:
                    lines.append(f'  {e[-100:]}')
        else:
            lines.append('[로그] journalctl 접근 불가 (서버에서 실행하세요)')

        lines += ['', '-' * 50, 'techchang.com 자동 발송']
        return '\n'.join(lines)
