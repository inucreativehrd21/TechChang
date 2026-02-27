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
        recipient = options['to'] or os.environ.get('DJANGO_ADMIN_EMAIL', '') or getattr(settings, 'ADMINS', [('', '')])[0][1]

        if not recipient:
            self.stderr.write(self.style.ERROR('수신자 이메일이 설정되지 않았습니다. --to 옵션 또는 DJANGO_ADMIN_EMAIL 환경변수를 설정하세요.'))
            return

        self.stdout.write(f'[{datetime.now():%Y-%m-%d %H:%M}] 로그 분석 시작 ({hours}시간)...')

        report = self._build_report(hours)

        if dry_run:
            self.stdout.write('\n' + '='*60)
            self.stdout.write(report['text'])
            self.stdout.write('='*60)
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
        """각 섹션 데이터 수집 후 HTML/텍스트 리포트 생성"""
        since = datetime.now() - timedelta(hours=hours)

        db_stats      = self._collect_db_stats()
        journal_stats = self._collect_journal(hours)
        security_stats= self._collect_security_logs(hours)
        sys_stats     = self._collect_system_stats()

        html = self._render_html(since, hours, db_stats, journal_stats, security_stats, sys_stats)
        text = self._render_text(since, hours, db_stats, journal_stats, security_stats, sys_stats)
        return {'html': html, 'text': text}

    # ------------------------------------------------------------------ #
    def _collect_db_stats(self):
        """Django ORM으로 DB 현황 수집"""
        from community.models import Question, Answer, Comment
        from common.models import Profile

        now = timezone.now()
        today = now.date()
        yesterday = today - timedelta(days=1)

        stats = {}
        try:
            stats['total_users']    = User.objects.count()
            stats['new_users_today']= User.objects.filter(date_joined__date=today).count()
            stats['total_questions']= Question.objects.filter(is_deleted=False).count()
            stats['new_questions']  = Question.objects.filter(is_deleted=False, create_date__date=today).count()
            stats['total_answers']  = Answer.objects.filter(is_deleted=False).count()
            stats['new_answers']    = Answer.objects.filter(is_deleted=False, create_date__date=today).count()
            stats['total_comments'] = Comment.objects.count()

            # 오늘 방문자 수 (DailyVisitor 모델)
            try:
                from community.models import DailyVisitor
                stats['visitors_today'] = DailyVisitor.objects.filter(date=today).first()
                stats['visitors_today'] = stats['visitors_today'].visitor_count if stats['visitors_today'] else 0
                stats['visitors_yesterday'] = DailyVisitor.objects.filter(date=yesterday).first()
                stats['visitors_yesterday'] = stats['visitors_yesterday'].visitor_count if stats['visitors_yesterday'] else 0
            except Exception:
                stats['visitors_today'] = '-'
                stats['visitors_yesterday'] = '-'
        except Exception as e:
            stats['error'] = str(e)

        return stats

    # ------------------------------------------------------------------ #
    def _collect_journal(self, hours):
        """systemd journal + nginx 액세스 로그 파싱"""
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

                # HTTP 상태 코드 (Gunicorn 액세스 로그 형식)
                m = re.search(r'"[A-Z]+ .+?" (\d{3})', line)
                if m:
                    code = int(m.group(1))
                    stats['request_count'] += 1
                    if 500 <= code < 600:
                        stats['status_5xx'] += 1
                    elif 400 <= code < 500:
                        stats['status_4xx'] += 1

            # 상위 에러 5개 (중복 제거)
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

        # journal에 요청 수가 없으면 nginx 로그에서 보완
        if stats['available'] and stats['request_count'] == 0:
            stats.update(self._collect_nginx_access(hours, stats))

        return stats

    # ------------------------------------------------------------------ #
    def _collect_nginx_access(self, hours, existing_stats):
        """nginx 액세스 로그에서 요청 수 / 상태 코드 집계"""
        import os
        from datetime import timezone as tz

        candidates = [
            '/var/log/nginx/techchang_access.log',
            '/var/log/nginx/mysite_access.log',
            '/var/log/nginx/access.log',
        ]

        cutoff = datetime.now(tz.utc).replace(tzinfo=None) - timedelta(hours=hours)
        # nginx 로그 날짜 포맷: 27/Feb/2026:14:00:00 +0900
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
                        # 시간 필터
                        dm = date_pat.search(line)
                        if dm:
                            raw = dm.group(1)  # 27/Feb/2026:14:00:00
                            parts = raw.split('/')
                            day = int(parts[0])
                            mon = month_map.get(parts[1], 0)
                            rest = parts[2].split(':')
                            year = int(rest[0])
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
            break  # 첫 번째로 찾은 파일만 사용

        return {
            'request_count': req_count,
            'status_5xx': existing_stats.get('status_5xx', 0) + status_5xx,
            'status_4xx': existing_stats.get('status_4xx', 0) + status_4xx,
        }

    # ------------------------------------------------------------------ #
    def _collect_security_logs(self, hours):
        """보안 관련 로그 (차단 IP, Rate Limit 등)"""
        stats = {
            'blocked_ips': 0,
            'rate_limit_hits': 0,
            'ddos_detected': 0,
            'available': False,
        }
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'mysite', f'--since={hours} hours ago',
                 '--no-pager', '-o', 'short', '--grep', r'blocked\|rate limit\|DDoS\|suspicious'],
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
        """CPU, 메모리, 디스크 사용량"""
        stats = {}
        try:
            # 메모리
            mem = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=5)
            for line in mem.stdout.splitlines():
                if line.startswith('Mem:'):
                    parts = line.split()
                    total, used, free = int(parts[1]), int(parts[2]), int(parts[3])
                    stats['mem_total_mb'] = total
                    stats['mem_used_mb']  = used
                    stats['mem_pct']      = round(used / total * 100, 1)
                    break

            # 디스크
            df = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=5)
            for line in df.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    stats['disk_total']  = parts[1]
                    stats['disk_used']   = parts[2]
                    stats['disk_pct']    = parts[4]
                    break

            # CPU 부하 (uptime)
            uptime = subprocess.run(['uptime'], capture_output=True, text=True, timeout=5)
            m = re.search(r'load average[s]?:\s+([\d.]+)', uptime.stdout)
            if m:
                stats['load_avg'] = m.group(1)

            # 서비스 상태
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
    def _status_icon(self, value, good='active', warn_threshold=None):
        if isinstance(value, str):
            return '🟢' if value == good else '🔴'
        if warn_threshold and value >= warn_threshold:
            return '🔴'
        return '🟢'

    def _render_html(self, since, hours, db, journal, security, sys):
        now_str   = datetime.now().strftime('%Y-%m-%d %H:%M')
        since_str = since.strftime('%Y-%m-%d %H:%M')

        mysite_icon = self._status_icon(sys.get('mysite_status', ''), 'active')
        nginx_icon  = self._status_icon(sys.get('nginx_status', ''), 'active')
        mem_pct     = sys.get('mem_pct', 0)
        mem_icon    = '🟡' if 70 <= mem_pct < 90 else ('🔴' if mem_pct >= 90 else '🟢')
        disk_pct_str = sys.get('disk_pct', '0%').replace('%', '')
        disk_int    = int(disk_pct_str) if disk_pct_str.isdigit() else 0
        disk_icon   = '🟡' if 70 <= disk_int < 90 else ('🔴' if disk_int >= 90 else '🟢')
        err_icon    = '🔴' if journal.get('status_5xx', 0) > 0 else '🟢'

        # 에러 목록
        errors_html = ''
        for e in journal.get('top_errors', []):
            errors_html += (
                '<li style="font-family:monospace;font-size:12px;color:#dc2626;margin-bottom:4px;">'
                + e + '</li>'
            )
        if not errors_html:
            errors_html = '<li style="color:#16a34a;">에러 없음</li>'

        # 로그 분석 섹션
        if journal.get('available'):
            badge_5xx = 'err' if journal.get('status_5xx', 0) > 0 else 'ok'
            journal_html = (
                '<div class="row"><span>총 요청 수</span>'
                '<span>{:,}</span></div>'.format(journal.get('request_count', 0)) +
                '<div class="row"><span>5xx 에러</span>'
                '<span><span class="badge {}">{}</span></span></div>'.format(badge_5xx, journal.get('status_5xx', 0)) +
                '<div class="row"><span>4xx 에러</span>'
                '<span>{:,}</span></div>'.format(journal.get('status_4xx', 0)) +
                '<div class="row"><span>Warning</span>'
                '<span>{}</span></div>'.format(journal.get('warning_count', 0)) +
                '<div class="row"><span>Error/Exception</span>'
                '<span>{} {}</span></div>'.format(err_icon, journal.get('error_count', 0))
            )
        else:
            journal_html = '<div style="color:#6b7280;font-size:0.875rem;">journalctl 접근 불가 (로컬 환경)</div>'

        # 보안 섹션
        if security.get('available'):
            badge_ip  = 'err' if security.get('blocked_ips', 0) > 5 else 'ok'
            badge_ddos = 'err' if security.get('ddos_detected', 0) > 0 else 'ok'
            security_html = (
                '<div class="row"><span>IP 차단</span>'
                '<span><span class="badge {}">{}</span></span></div>'.format(badge_ip, security.get('blocked_ips', 0)) +
                '<div class="row"><span>Rate Limit 발동</span>'
                '<span>{}</span></div>'.format(security.get('rate_limit_hits', 0)) +
                '<div class="row"><span>DDoS 감지</span>'
                '<span><span class="badge {}">{}</span></span></div>'.format(badge_ddos, security.get('ddos_detected', 0))
            )
        else:
            security_html = '<div style="color:#6b7280;font-size:0.875rem;">journalctl 접근 불가</div>'

        # 에러 카드
        errors_card = ''
        if journal.get('available'):
            errors_card = (
                '<div class="card"><h2>⚠️ 최근 에러 로그</h2>'
                '<ul style="margin:0;padding-left:16px;">' + errors_html + '</ul></div>'
            )

        return """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><style>
  body {{ font-family: -apple-system, sans-serif; background:#f3f4f6; margin:0; padding:20px; }}
  .card {{ background:#fff; border-radius:12px; padding:24px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
  h1 {{ font-size:1.25rem; font-weight:800; color:#111; margin:0 0 4px; }}
  h2 {{ font-size:0.9375rem; font-weight:700; color:#374151; margin:0 0 16px; border-bottom:1px solid #e5e7eb; padding-bottom:8px; }}
  .sub {{ font-size:0.8125rem; color:#6b7280; }}
  .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
  .stat {{ background:#f9fafb; border-radius:8px; padding:12px; text-align:center; }}
  .stat-num {{ font-size:1.5rem; font-weight:800; color:#3b82f6; }}
  .stat-label {{ font-size:0.75rem; color:#6b7280; margin-top:2px; }}
  .row {{ display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #f3f4f6; font-size:0.875rem; }}
  .row:last-child {{ border:none; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:20px; font-size:0.75rem; font-weight:600; }}
  .ok {{ background:#dcfce7; color:#16a34a; }}
  .warn {{ background:#fef9c3; color:#ca8a04; }}
  .err {{ background:#fee2e2; color:#dc2626; }}
</style></head>
<body>
<div class="card" style="background:linear-gradient(135deg,#3b82f6,#6366f1);color:#fff;">
  <h1 style="color:#fff;">&#128202; 테크창 서버 리포트</h1>
  <div class="sub" style="color:rgba(255,255,255,.8);">{since_str} ~ {now_str} ({hours}h)</div>
</div>
<div class="card">
  <h2>&#128187; 서비스 상태</h2>
  <div class="row"><span>Django (mysite)</span><span>{mysite_icon} {mysite_status}</span></div>
  <div class="row"><span>Nginx</span><span>{nginx_icon} {nginx_status}</span></div>
  <div class="row"><span>CPU 부하</span><span>{load_avg}</span></div>
  <div class="row"><span>메모리 사용</span><span>{mem_icon} {mem_used} / {mem_total} MB ({mem_pct}%)</span></div>
  <div class="row"><span>디스크 사용</span><span>{disk_icon} {disk_used} / {disk_total} ({disk_pct})</span></div>
</div>
<div class="card">
  <h2>&#128200; DB 현황 (오늘)</h2>
  <div class="grid">
    <div class="stat"><div class="stat-num">{total_users}</div><div class="stat-label">전체 회원</div></div>
    <div class="stat"><div class="stat-num">+{new_users}</div><div class="stat-label">신규 가입</div></div>
    <div class="stat"><div class="stat-num">{visitors}</div><div class="stat-label">오늘 방문자</div></div>
    <div class="stat"><div class="stat-num">{total_q}</div><div class="stat-label">전체 질문</div></div>
    <div class="stat"><div class="stat-num">+{new_q}</div><div class="stat-label">오늘 질문</div></div>
    <div class="stat"><div class="stat-num">+{new_a}</div><div class="stat-label">오늘 답변</div></div>
  </div>
</div>
<div class="card">
  <h2>&#128203; 로그 분석 ({hours}h)</h2>
  {journal_html}
</div>
<div class="card">
  <h2>&#128274; 보안 이벤트 ({hours}h)</h2>
  {security_html}
</div>
{errors_card}
<div style="text-align:center;font-size:0.75rem;color:#9ca3af;margin-top:8px;">
  자동 발송 &#8212; techchang.com | <a href="https://techchang.com" style="color:#3b82f6;">사이트 바로가기</a>
</div>
</body></html>""".format(
            since_str=since_str, now_str=now_str, hours=hours,
            mysite_icon=mysite_icon, mysite_status=sys.get('mysite_status', 'unknown'),
            nginx_icon=nginx_icon,  nginx_status=sys.get('nginx_status', 'unknown'),
            load_avg=sys.get('load_avg', '-'),
            mem_icon=mem_icon, mem_used=sys.get('mem_used_mb', '-'),
            mem_total=sys.get('mem_total_mb', '-'), mem_pct=mem_pct,
            disk_icon=disk_icon, disk_used=sys.get('disk_used', '-'),
            disk_total=sys.get('disk_total', '-'), disk_pct=sys.get('disk_pct', '-'),
            total_users=db.get('total_users', '-'),
            new_users=db.get('new_users_today', 0),
            visitors=db.get('visitors_today', '-'),
            total_q=db.get('total_questions', '-'),
            new_q=db.get('new_questions', 0),
            new_a=db.get('new_answers', 0),
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
            f'  Django : {sys.get("mysite_status","unknown")}',
            f'  Nginx  : {sys.get("nginx_status","unknown")}',
            f'  CPU 부하: {sys.get("load_avg","-")}',
            f'  메모리  : {sys.get("mem_used_mb","-")}/{sys.get("mem_total_mb","-")} MB ({sys.get("mem_pct","-")}%)',
            f'  디스크  : {sys.get("disk_used","-")}/{sys.get("disk_total","-")} ({sys.get("disk_pct","-")})',
            '',
            '[DB 현황]',
            f'  전체 회원    : {db.get("total_users","-")} (신규 +{db.get("new_users_today",0)})',
            f'  오늘 방문자  : {db.get("visitors_today","-")} (어제 {db.get("visitors_yesterday","-")})',
            f'  전체 질문    : {db.get("total_questions","-")} (오늘 +{db.get("new_questions",0)})',
            f'  전체 답변    : {db.get("total_answers","-")} (오늘 +{db.get("new_answers",0)})',
            '',
        ]

        if journal.get('available'):
            lines += [
                '[로그 분석]',
                f'  총 요청    : {journal.get("request_count",0):,}',
                f'  5xx 에러   : {journal.get("status_5xx",0)}  ← 중요',
                f'  4xx 에러   : {journal.get("status_4xx",0):,}',
                f'  Warning    : {journal.get("warning_count",0)}',
                f'  Error/Exc  : {journal.get("error_count",0)}',
                '',
                '[보안 이벤트]',
                f'  IP 차단    : {security.get("blocked_ips",0)}',
                f'  Rate Limit : {security.get("rate_limit_hits",0)}',
                f'  DDoS 감지  : {security.get("ddos_detected",0)}',
                '',
            ]
            if journal.get('top_errors'):
                lines.append('[최근 에러]')
                for e in journal['top_errors']:
                    lines.append(f'  {e[-100:]}')
        else:
            lines.append('[로그] journalctl 접근 불가 (서버에서 실행하세요)')

        lines += ['', '─' * 50, 'techchang.com 자동 발송']
        return '\n'.join(lines)
