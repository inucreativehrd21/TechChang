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

# 자동 칼럼 작성 봇 계정 (auto_write_columns 와 동일)
COLUMN_BOT_USERNAME = 'techchang연구팀'


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
        ai_analysis    = self._analyze_errors(hours, journal_stats)

        html = self._render_html(since, hours, db_stats, journal_stats, security_stats, sys_stats, ai_analysis)
        text = self._render_text(since, hours, db_stats, journal_stats, security_stats, sys_stats, ai_analysis)
        return {'html': html, 'text': text}

    # ------------------------------------------------------------------ #
    def _analyze_errors(self, hours, journal):
        """
        Claude(Sonnet)를 에러 분석관으로 활용해 치명적 로그를 해설한다.
        에러/5xx가 있을 때만 호출되며, API 키 미설정·호출 실패 시 조용히 None을 반환해
        리포트 발송 자체는 막지 않는다.
        """
        top_errors = journal.get('top_errors', [])
        error_count = journal.get('error_count', 0)
        status_5xx  = journal.get('status_5xx', 0)

        # 치명적 신호가 없으면 분석하지 않는다 (평소 API 비용 0)
        if not top_errors and status_5xx == 0:
            return {'available': True, 'skipped': True}

        try:
            from common.services.claude import ask_json, ClaudeModel

            error_block = '\n'.join(
                f'{i}. {e}' for i, e in enumerate(top_errors, 1)
            ) or '(개별 에러 라인은 수집되지 않았으나 5xx 응답이 발생함)'

            system = (
                '당신은 테크창(Django 5.1 / Gunicorn / Nginx / Ubuntu 24.04, SQLite) 서비스의 '
                '시니어 SRE 겸 에러 분석관입니다. 운영 로그에서 추출한 에러를 보고, '
                '서버 전문 지식이 깊지 않은 운영자도 이해할 수 있도록 한국어로 간결하게 분석합니다. '
                '추측을 단정하지 말고 근거에 기반해 원인을 추정하며, 바로 실행할 수 있는 조치를 제안합니다.'
            )
            prompt = (
                f'다음은 최근 {hours}시간 동안 테크창 서버 로그에서 추출한 에러 지표와 샘플입니다.\n\n'
                f'[지표]\n'
                f'- 5xx 에러 응답: {status_5xx}건\n'
                f'- 4xx 에러 응답: {journal.get("status_4xx", 0)}건\n'
                f'- Error/Exception 라인: {error_count}건\n'
                f'- Warning 라인: {journal.get("warning_count", 0)}건\n\n'
                f'[에러 로그 샘플]\n{error_block}\n\n'
                '치명적인 문제 위주로 분석해 아래 JSON 형식으로만 응답하세요.\n'
                '```json\n'
                '{\n'
                '  "severity": "심각 | 주의 | 정보 중 하나",\n'
                '  "overview": "전체 상황을 한두 문장으로 요약한 총평",\n'
                '  "findings": [\n'
                '    {"title": "문제 제목", "cause": "추정 원인", "action": "권장 조치"}\n'
                '  ]\n'
                '}\n'
                '```\n'
                'findings는 가장 중요한 것 위주로 최대 3개까지만 작성하세요.'
            )

            data = ask_json(
                prompt,
                system=system,
                model=ClaudeModel.SONNET,
                max_tokens=1500,
            )

            findings = data.get('findings', [])
            if isinstance(findings, dict):
                findings = [findings]

            return {
                'available': True,
                'skipped': False,
                'severity': str(data.get('severity', '정보')).strip(),
                'overview': str(data.get('overview', '')).strip(),
                'findings': findings[:3],
            }

        except Exception as e:
            self.stderr.write(self.style.WARNING(f'에러 분석(Claude) 건너뜀: {e}'))
            return {'available': False, 'error': str(e)}

    # ------------------------------------------------------------------ #
    #  파일 로그 폴백
    #  journalctl은 mysite 유닛 로그를 보려면 서비스 계정이 systemd-journal
    #  그룹에 속해야 한다. 권한이 없으면(대부분의 기본 배포) returncode != 0이 되어
    #  로그 분석·보안·실시간 로그가 모두 비활성화된다. 그 경우 앱이 직접 기록하는
    #  logs/django.log(prod LOGGING)를 읽어 동일 정보를 제공한다 — 추가 권한 불필요.
    # ------------------------------------------------------------------ #
    def _app_log_path(self):
        """Django 파일 로그 경로 (LOGGING의 logs/django.log)."""
        try:
            base = str(settings.BASE_DIR)
        except Exception:
            base = os.getcwd()
        return os.path.join(base, 'logs', 'django.log')

    def _read_log_file(self, hours=None, tail=None, max_bytes=6 * 1024 * 1024):
        """
        logs/django.log를 읽어 라인 리스트로 반환 (journalctl 폴백 소스).
        - hours    : 최근 N시간 라인만 (asctime '%Y-%m-%d %H:%M:%S' 기준 필터)
        - tail     : 마지막 N줄만
        - max_bytes: 파일 끝에서 최대 이만큼만 읽어 비용을 제한 (기본 6MB)
        파일이 없거나 못 읽으면 None.
        """
        path = self._app_log_path()
        if not os.path.exists(path):
            return None
        try:
            size = os.path.getsize(path)
            with open(path, 'r', errors='replace') as f:
                if size > max_bytes:
                    f.seek(size - max_bytes)
                    f.readline()  # 잘린 첫 줄 버림
                lines = [l.rstrip('\n') for l in f]
        except OSError:
            return None

        if hours is not None:
            cutoff = datetime.now() - timedelta(hours=hours)
            ts_pat = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
            kept, keep = [], False
            for line in lines:
                m = ts_pat.search(line)
                if m:
                    try:
                        keep = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S') >= cutoff
                    except ValueError:
                        pass
                if keep:
                    kept.append(line)
            lines = kept

        if tail is not None:
            lines = lines[-tail:]
        return lines

    @staticmethod
    def _classify_level(line):
        lower = line.lower()
        if 'error' in lower or 'exception' in lower or 'traceback' in lower or '" 5' in line:
            return 'error'
        if 'warning' in lower or 'warn' in lower or '" 4' in line:
            return 'warn'
        return 'info'

    # ------------------------------------------------------------------ #
    def _tail_logs(self, lines=120):
        """
        실시간 모니터링용 최근 로그 라인 (읽기 전용).
        journalctl 우선, 미가용 시 logs/django.log 폴백.
        """
        out = {'available': False, 'lines': [], 'source': None}
        try:
            lines = max(20, min(int(lines), 300))
        except (TypeError, ValueError):
            lines = 120

        # 1) journalctl (systemd)
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'mysite', '-n', str(lines),
                 '--no-pager', '-o', 'short-iso'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                out['available'] = True
                out['source'] = 'journal'
                for line in result.stdout.splitlines():
                    out['lines'].append({'text': line, 'level': self._classify_level(line)})
                return out
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # 2) 폴백: Django 파일 로그
        file_lines = self._read_log_file(tail=lines)
        if file_lines is not None:
            out['available'] = True
            out['source'] = 'file'
            for line in file_lines:
                out['lines'].append({'text': line, 'level': self._classify_level(line)})

        return out

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

            # 자동 칼럼 작성 내역 (테크창 연구팀 봇)
            try:
                week_ago = today - timedelta(days=7)
                bot_cols = Question.objects.filter(
                    is_deleted=False, author__username=COLUMN_BOT_USERNAME
                ).select_related('category')
                stats['column_total'] = bot_cols.count()
                stats['column_today'] = bot_cols.filter(create_date__date=today).count()
                stats['column_week']  = bot_cols.filter(create_date__date__gte=week_ago).count()
                stats['recent_columns'] = [
                    {
                        'subject': c.subject,
                        'category': c.category.name if c.category else '-',
                        'date': c.create_date,
                    }
                    for c in bot_cols.order_by('-create_date')[:8]
                ]
            except Exception:
                stats['column_total'] = stats['column_today'] = stats['column_week'] = 0
                stats['recent_columns'] = []

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
            'source': None,
        }

        raw_lines = None
        # 1) journalctl (systemd)
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'mysite', f'--since={hours} hours ago',
                 '--no-pager', '-o', 'short'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                raw_lines = result.stdout.splitlines()
                stats['source'] = 'journal'
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # 2) 폴백: Django 파일 로그
        if raw_lines is None:
            file_lines = self._read_log_file(hours=hours)
            if file_lines is not None:
                raw_lines = file_lines
                stats['source'] = 'file'

        if raw_lines is not None:
            stats['available'] = True
            errors = []

            for line in raw_lines:
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

        # 요청/상태 코드는 보통 nginx 액세스 로그에 있다 (저널/파일에 없을 때 보완)
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
            'source': None,
        }

        raw_lines = None
        # 1) journalctl --grep (systemd). 매칭이 없으면 returncode 1 → 파일 폴백으로 진행.
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'mysite', f'--since={hours} hours ago',
                 '--no-pager', '-o', 'short', '--grep',
                 r'blocked\|rate limit\|DDoS\|suspicious'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                raw_lines = result.stdout.splitlines()
                stats['source'] = 'journal'
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # 2) 폴백: Django 파일 로그 (보안 미들웨어 로그가 logs/django.log에 기록됨)
        if raw_lines is None:
            file_lines = self._read_log_file(hours=hours)
            if file_lines is not None:
                raw_lines = file_lines
                stats['source'] = 'file'

        if raw_lines is not None:
            stats['available'] = True
            for line in raw_lines:
                lower = line.lower()
                if 'blocked' in lower:
                    stats['blocked_ips'] += 1
                if 'rate limit' in lower:
                    stats['rate_limit_hits'] += 1
                if 'ddos' in lower:
                    stats['ddos_detected'] += 1

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

    def _severity_color(self, severity):
        """심각도 텍스트 → 컬러 매핑"""
        return {
            '심각': '#dc2626',
            '주의': '#ca8a04',
            '정보': '#16a34a',
        }.get((severity or '').strip(), '#4f46e5')

    def _render_ai_card(self, ai):
        """Claude 에러 분석 카드 (HTML). 분석 결과가 없으면 빈 문자열."""
        if not ai or not ai.get('available') or ai.get('skipped'):
            return ''
        findings = ai.get('findings', [])
        if not ai.get('overview') and not findings:
            return ''

        severity = ai.get('severity', '정보')
        sev_color = self._severity_color(severity)

        items_html = ''
        for f in findings:
            title  = (f.get('title') or '').strip()
            cause  = (f.get('cause') or '').strip()
            action = (f.get('action') or '').strip()
            items_html += (
                '<div style="padding:11px 0;border-bottom:1px solid #f4f4f5;">'
                '<div style="font-weight:700;font-size:0.8125rem;color:#18181b;margin-bottom:5px;">'
                f'{title}</div>'
                '<div style="font-size:0.78rem;color:#52525b;margin-bottom:3px;">'
                f'<span style="color:#a1a1aa;">원인&nbsp;</span>{cause}</div>'
                '<div style="font-size:0.78rem;color:#52525b;">'
                f'<span style="color:#a1a1aa;">조치&nbsp;</span>{action}</div>'
                '</div>'
            )

        return (
            '<div class="card" style="border-left:3px solid ' + sev_color + ';">'
            '<h2>AI 에러 분석관 '
            '<span style="font-weight:700;font-size:0.6875rem;color:#fff;background:' + sev_color + ';'
            'padding:1px 8px;border-radius:999px;margin-left:6px;vertical-align:middle;">'
            + severity + '</span></h2>'
            '<div style="font-size:0.82rem;color:#3f3f46;line-height:1.55;margin-bottom:4px;">'
            + ai.get('overview', '') + '</div>'
            + items_html +
            '<div style="font-size:0.65rem;color:#c4c4cc;margin-top:10px;">Claude Sonnet 분석 · 참고용</div>'
            '</div>'
        )

    def _render_html(self, since, hours, db, journal, security, sys, ai=None):
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
                '<span style="color:#3f3f46;">{i}. {subj}</span>'
                '<span style="color:#a1a1aa;">{vc:,}회</span>'
                '</div>'.format(i=i, subj=subj, vc=vc)
            )
        if not top_q_html:
            top_q_html = '<div style="color:#a1a1aa;">데이터 없음</div>'

        # 칼럼 자동 작성 내역
        col_rows = ''
        for c in db.get('recent_columns', []):
            subj = (c.get('subject') or '')[:42]
            cat  = c.get('category', '-')
            d    = c.get('date')
            date_str = d.strftime('%m-%d %H:%M') if hasattr(d, 'strftime') else str(d)
            col_rows += (
                '<div class="row">'
                '<span style="color:#3f3f46;"><span class="cat">{cat}</span>{subj}</span>'
                '<span style="color:#a1a1aa;white-space:nowrap;">{date}</span>'
                '</div>'.format(cat=cat, subj=subj, date=date_str)
            )
        if not col_rows:
            col_rows = '<div style="color:#a1a1aa;">아직 자동 작성된 칼럼이 없습니다.</div>'

        # AI 에러 분석 카드
        ai_card = self._render_ai_card(ai)

        return """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans KR',sans-serif;
          background:#fafafa; margin:0; padding:20px; color:#3f3f46; -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:640px; margin:0 auto; }}
  .card {{ background:#fff; border:1px solid #e8e8eb; border-radius:14px; padding:22px 24px;
           margin-bottom:14px; box-shadow:0 1px 2px rgba(16,24,40,.04); }}
  h1 {{ font-size:1.0625rem; font-weight:800; letter-spacing:-.02em; color:#18181b; margin:0 0 4px; }}
  h2 {{ font-size:0.8125rem; font-weight:700; color:#18181b; margin:0 0 14px;
        padding-bottom:9px; border-bottom:1px solid #f0f0f1; letter-spacing:.01em; }}
  .sub {{ font-size:0.8125rem; color:#71717a; }}
  .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
  .stat {{ background:#fafafa; border:1px solid #f0f0f1; border-radius:10px; padding:12px; text-align:center; }}
  .stat-num {{ font-size:1.375rem; font-weight:800; letter-spacing:-.02em; color:#4f46e5; }}
  .stat-num.g {{ color:#059669; }}
  .stat-label {{ font-size:0.6875rem; color:#a1a1aa; margin-top:3px; }}
  .row {{ display:flex; justify-content:space-between; gap:10px; padding:7px 0;
          border-bottom:1px solid #f4f4f5; font-size:0.8125rem; color:#3f3f46; }}
  .row:last-child {{ border:none; }}
  .cat {{ display:inline-block; font-size:0.65rem; font-weight:700; color:#4f46e5;
          background:#eef2ff; padding:1px 7px; border-radius:999px; margin-right:6px; }}
  a {{ color:#4f46e5; text-decoration:none; }}
</style></head>
<body>
<div class="wrap">
<div class="card" style="background:#18181b; border:none; color:#fff; padding:20px 24px;">
  <h1 style="color:#fff;">테크창 서버 리포트</h1>
  <div class="sub" style="color:rgba(255,255,255,.7);">{since_str} ~ {now_str} ({hours}h)</div>
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
  <h2>칼럼 자동 작성 내역</h2>
  <div class="grid" style="margin-bottom:14px;">
    <div class="stat"><div class="stat-num">{column_total}</div><div class="stat-label">전체 칼럼</div></div>
    <div class="stat"><div class="stat-num g">+{column_week}</div><div class="stat-label">최근 7일</div></div>
    <div class="stat"><div class="stat-num g">+{column_today}</div><div class="stat-label">오늘</div></div>
  </div>
  {col_rows}
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

{ai_card}

<div style="text-align:center;font-size:0.75rem;color:#a1a1aa;margin-top:6px;padding-bottom:8px;">
  자동 발송 · techchang.com | <a href="https://techchang.com">사이트 바로가기</a>
</div>
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
            column_total=db.get('column_total', 0),
            column_week=db.get('column_week', 0),
            column_today=db.get('column_today', 0),
            col_rows=col_rows,
            top_q_html=top_q_html,
            journal_html=journal_html,
            security_html=security_html,
            errors_card=errors_card,
            ai_card=ai_card,
        )

    def _render_text(self, since, hours, db, journal, security, sys, ai=None):
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

        # 칼럼 자동 작성 내역
        lines += [
            '',
            '[칼럼 자동 작성 내역]',
            f'  전체 {db.get("column_total", 0)}건 (최근 7일 +{db.get("column_week", 0)}, 오늘 +{db.get("column_today", 0)})',
        ]
        recent_cols = db.get('recent_columns', [])
        if recent_cols:
            for c in recent_cols:
                d = c.get('date')
                date_str = d.strftime('%m-%d') if hasattr(d, 'strftime') else str(d)
                lines.append(f'    - [{c.get("category", "-")}] {(c.get("subject") or "")[:40]} ({date_str})')
        else:
            lines.append('    (아직 자동 작성된 칼럼이 없습니다)')

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

        # AI 에러 분석관
        if ai and ai.get('available') and not ai.get('skipped'):
            findings = ai.get('findings', [])
            if ai.get('overview') or findings:
                lines += ['', f'[AI 에러 분석관 · {ai.get("severity", "정보")}]', f'  {ai.get("overview", "")}']
                for f in findings:
                    lines += [
                        f'  - {(f.get("title") or "").strip()}',
                        f'      원인: {(f.get("cause") or "").strip()}',
                        f'      조치: {(f.get("action") or "").strip()}',
                    ]

        lines += ['', '-' * 50, 'techchang.com 자동 발송']
        return '\n'.join(lines)
