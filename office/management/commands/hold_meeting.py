"""
주간 편집회의 — 연구팀 6명이 지표를 놓고 다음 주 칼럼 주제·시리즈·개발 방향을 논의하고,
팀장이 안건별 선택지(2~3개)로 정리한다. 관리자는 /lab/admin/ 에서 하나씩 고른다.

사용법:
  python manage.py hold_meeting              # 이번 주(월요일 기준) 회의. 이미 있으면 건너뜀
  python manage.py hold_meeting --force      # 같은 주에 다시 개최 (기존 회의는 남고 새로 생성)
  python manage.py hold_meeting --email a@b  # 회의록 요약 메일

cron (일요일 20:00 → 다음 주 월요일 주차로 기록):
  0 20 * * 0  .../python manage.py hold_meeting --email seunghyunmoon55@gmail.com
"""
import json
import time
import traceback
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.html import escape

from common.services.claude import call_tags, track_calls
from office import live
from office.agents import AGENTS, MEETING_ORDER
from office.models import Decision, Meeting
from office.services import ask_agent, ask_agent_json, collect_site_snapshot, log, snapshot_as_text, week_monday

ROUND1 = (
    '{who} — 지금은 주간 편집회의 1라운드(제안)입니다.\n\n[사이트 지표·현황]\n{brief}\n\n[지금까지 발언]\n{transcript}\n\n'
    '{task}\n5문장 이내로, 회의에서 말하듯 자연스럽게 발언하세요. 목록 기호·헤더 없이 문단으로.'
)
ROUND2 = (
    '{who} — 2라운드(검토·조율)입니다. 1라운드 발언 전체를 읽고, 다른 팀원의 제안에 대해 찬성·우려·보완 의견을 '
    '3문장 이내로 말하세요. 새 제안은 하지 말고 이미 나온 것들의 우선순위를 좁히는 데 집중하세요.\n\n'
    '[사이트 지표·현황]\n{brief}\n\n[발언 기록]\n{transcript}'
)

TASKS = {
    'lead': ('회의를 열며 지표를 해석해 주세요: 무엇이 늘고 줄었는지, 어떤 분야·형식의 글이 반응이 좋았는지, '
             '이번 주 팀이 집중해야 할 한두 가지. 마지막에 각 칼럼니스트에게 주제 제안을 요청하세요.'),
    'hrd': '당신 분야에서 다음 주 칼럼으로 다룰 만한 주제 2개를 각각 한 줄 근거와 함께 제안하세요. 최근 발행 칼럼과 겹치지 않게.',
    'data': '당신 분야에서 다음 주 칼럼으로 다룰 만한 주제 2개를 각각 한 줄 근거와 함께 제안하세요. 최근 발행 칼럼과 겹치지 않게.',
    'coding': '당신 분야에서 다음 주 칼럼으로 다룰 만한 주제 2개를 각각 한 줄 근거와 함께 제안하세요. 최근 발행 칼럼과 겹치지 않게.',
    'checker': ('지금까지 나온 주제 제안 각각에 대해 (1) 기존 발행 칼럼과 핵심 소재가 겹치는지, (2) 실제 근거·출처로 검증 가능한 주제인지 '
                '짧게 판정하세요. 문제 있는 제안은 이름을 지목해 이유를 말하세요.'),
    'charter': ('나온 주제 제안 중 실제 수치·통계로 표나 차트를 만들 수 있는 것과 그렇지 않은 것을 구분해 말하고, '
                '사이트 지표에서 관리자가 봐야 할 숫자 하나를 짚어 주세요.'),
}

SYNTHESIS = (
    '회의가 끝났습니다. 팀장으로서 아래 발언 기록을 결론으로 정리하세요.\n\n[사이트 지표·현황]\n{brief}\n\n[발언 기록]\n{transcript}\n\n'
    '다음 JSON 스키마로만 출력하세요:\n'
    '{{\n'
    '  "summary": "회의 결론 3~4문장",\n'
    '  "decisions": [\n'
    '    {{"kind": "column", "topic": "hrd", "question": "다음 주 HRD 칼럼 주제",\n'
    '      "options": [{{"key": "a", "title": "칼럼 주제(구체적)", "detail": "다룰 관점·근거·예상 출처 한두 문장", "proposed_by": "한빈"}}, ...2~3개]}},\n'
    '    {{"kind": "column", "topic": "data", ...}},\n'
    '    {{"kind": "column", "topic": "coding", ...}},\n'
    '    {{"kind": "series", "topic": "", "question": "연재 시리즈 다음 방향", "options": [...2개]}},\n'
    '    {{"kind": "dev", "topic": "", "question": "사이트 개발·개선 우선 과제", "options": [...2~3개]}},\n'
    '    {{"kind": "ops", "topic": "", "question": "운영·보안 점검 과제", "options": [...1~2개]}}\n'
    '  ]\n'
    '}}\n'
    '규칙: 검증관이 중복·검증 불가로 지목한 주제는 options 에 넣지 않는다. 각 option.key 는 a,b,c. '
    'dev/ops 는 지표·지적사항에 근거한 구체적 작업으로. 발언에 근거 없는 항목을 만들지 않는다.'
)


class Command(BaseCommand):
    help = '연구팀 주간 편집회의를 열고 안건별 선택지를 저장합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='같은 주차에 이미 회의가 있어도 새로 개최')
        parser.add_argument('--email', default='', help='회의록 요약을 보낼 주소')
        parser.add_argument('--dry-run', action='store_true', help='API 는 호출하되 DB 에 저장하지 않음')

    def handle(self, *args, **opts):
        # 단계별 실행 기록 — 메일의 "실행 결과" 표가 된다. 폴백은 메일 본문에 담으므로 즉시 알림은 끈다
        self.steps = []
        self.started_at = timezone.localtime()
        with track_calls(alert=False) as calls:
            self.calls = calls
            try:
                meeting = self._hold(opts)
            except Exception:
                if opts['email'] and not opts['dry_run']:
                    self._send_failure_mail(opts['email'], traceback.format_exc())
                raise
            finally:
                live.finish()
        if meeting and opts['email']:
            self._send_mail(opts['email'], meeting)

    def _step(self, label, fn):
        """fn 을 실행하고 그 안의 Claude 호출을 단계에 묶어 기록한다.
        호출은 꼬리표(step)로 모은다 — 목록 위치로 자르면 병렬로 돈 단계의 호출이 섞인다."""
        started = time.monotonic()
        step = {'label': label, 'ok': False, 'seconds': 0.0, 'calls': [], 'note': ''}
        self.steps.append(step)
        try:
            with call_tags(step=label):
                result = fn()
            step['ok'] = True
            return result
        except Exception as ex:
            step['note'] = f'{type(ex).__name__}: {ex}'[:300]
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 1)
            step['calls'] = [c for c in self.calls if c.get('tags', {}).get('step') == label]

    def _hold(self, opts):
        # 일요일 저녁에 돌리면 '다음 주' 회의로 기록
        today = timezone.localdate()
        week = week_monday(today + timedelta(days=1)) if today.weekday() == 6 else week_monday(today)
        if not opts['force'] and Meeting.objects.filter(week_start=week).exists():
            self.stdout.write(f'{week} 주차 회의가 이미 있습니다. --force 로 다시 개최할 수 있습니다.')
            return None

        self.week = week
        live.mark('meeting', 'lead')
        self.stdout.write(f'[{timezone.localtime():%H:%M:%S}] {week} 주차 편집회의 소집 — 지표 수집 중...')
        snap = self._step('지표 수집', collect_site_snapshot)
        brief = snapshot_as_text(snap)

        transcript = []
        self.transcript = transcript  # 실패 메일에 "어디까지 말했는지" 남기기 위해

        def tx():
            return '\n'.join(f"{AGENTS[t['agent']]['name']}({AGENTS[t['agent']]['title']}): {t['text']}" for t in transcript) or '(아직 없음)'

        def who(k):
            return f"{AGENTS[k]['name']}({AGENTS[k]['title']})"

        for rnd, template in ((1, ROUND1), (2, ROUND2)):
            for key in MEETING_ORDER:
                if rnd == 2 and key == 'lead':
                    continue  # 팀장은 2라운드 대신 결론 정리를 맡는다
                prompt = template.format(who=who(key), brief=brief, transcript=tx(), task=TASKS.get(key, ''))
                text = self._step(f'{rnd}라운드 · {who(key)}', lambda: ask_agent(key, prompt, max_tokens=1500))
                transcript.append({'agent': key, 'round': rnd, 'text': text})
                self.stdout.write(f'  R{rnd} {who(key)}: {text[:60]}...')

        result = self._step('결론 정리 · ' + who('lead'),
                            lambda: ask_agent_json('lead', SYNTHESIS.format(brief=brief, transcript=tx()), max_tokens=8000))
        decisions = [d for d in result.get('decisions', []) if isinstance(d, dict) and d.get('options')]
        summary = str(result.get('summary', '')).strip()
        self.stdout.write(f'  결론: {summary[:80]}... / 안건 {len(decisions)}건')

        if opts['dry_run']:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
            return None

        return self._step('회의록·안건 저장', lambda: self._save(week, brief, transcript, snap, summary, decisions))

    def _save(self, week, brief, transcript, snap, summary, decisions):
        meeting = Meeting.objects.create(week_start=week, briefing=brief, transcript=transcript,
                                         snapshot=snap, summary=summary)
        for d in decisions:
            opts_clean = []
            for i, o in enumerate(d['options'][:3]):
                if not isinstance(o, dict) or not o.get('title'):
                    continue
                opts_clean.append({'key': o.get('key') or 'abc'[i], 'title': str(o['title'])[:200],
                                   'detail': str(o.get('detail', ''))[:600], 'proposed_by': str(o.get('proposed_by', ''))[:20]})
            if not opts_clean:
                continue
            Decision.objects.create(
                meeting=meeting, kind=d.get('kind', 'dev') if d.get('kind') in dict(Decision.KIND_CHOICES) else 'dev',
                topic=d.get('topic', '') if d.get('topic') in ('hrd', 'data', 'coding') else '',
                question=str(d.get('question', ''))[:300], options=opts_clean,
            )
        # 연구원별 1라운드 발언을 작업 기록으로 (연구실 말풍선에서 "회의에서 한 말"로 보이게)
        for t in transcript:
            if t['round'] == 1 and t['agent'] != 'lead':
                log(t['agent'], 'meeting', f"편집회의 발언: {t['text'][:120]}", meeting=meeting)
        log('lead', 'meeting', f'{week} 주차 편집회의 종료 — 안건 {meeting.decisions.count()}건, 관리자 결정 대기', meeting=meeting)
        self.stdout.write(self.style.SUCCESS(f'회의 저장 완료 (id={meeting.id}, 안건 {meeting.decisions.count()}건)'))
        return meeting

    # ───────────────────────────── 메일
    # 섹션은 (제목, 텍스트 본문, HTML 본문) 묶음으로 만들어 평문·HTML 두 판을 같은 순서로 낸다.
    def _send_mail(self, to, meeting):
        decisions = list(meeting.decisions.all())
        usage = self._usage()
        sections = [
            ('결론 요약', meeting.summary or '(요약 없음)', _br(meeting.summary or '(요약 없음)')),
            self._execution_section(usage),
            self._decisions_section(decisions),
            self._transcript_section(meeting.transcript),
            ('지표 브리핑 (회의에 제공된 자료)', meeting.briefing, f'<pre style="{PRE}">{escape(meeting.briefing)}</pre>'),
        ]
        warn = f" · ⚠ API 폴백 {usage['fallbacks']}회" if usage['fallbacks'] else ''
        subject = f'[TechChang] {meeting.week_start} 편집회의 결과 — 결정 {len(decisions)}건 대기{warn}'
        lead = f'{meeting.week_start} 주차 편집회의가 끝났습니다. 안건 {len(decisions)}건이 결정을 기다립니다.'
        self._deliver(to, subject, lead, sections)

    def _send_failure_mail(self, to, tb):
        usage = self._usage()
        week = getattr(self, 'week', '')
        transcript = getattr(self, 'transcript', [])
        failed = next((s for s in reversed(self.steps) if not s['ok']), None)
        where = failed['label'] if failed else '단계 밖(준비·메일 단계)'
        sections = [
            ('실패 지점', f'{where}\n\n{tb[-3000:]}', f'<b>{escape(where)}</b><pre style="{PRE}">{escape(tb[-3000:])}</pre>'),
            self._execution_section(usage),
        ]
        if transcript:
            sections.append(self._transcript_section(transcript))
        lead = (f'{week} 주차 편집회의가 도중에 실패해 회의록이 저장되지 않았습니다. '
                '원인을 확인한 뒤 `manage.py hold_meeting --force` 로 다시 열 수 있습니다.')
        self._deliver(to, f'[TechChang] {week} 편집회의 실패 — {where}', lead, sections)

    def _usage(self):
        calls = self.calls
        return {
            'total': len(calls),
            'cli': sum(1 for c in calls if c['backend'] == 'cli'),
            'api': sum(1 for c in calls if c['backend'] == 'api'),
            'errors': sum(1 for c in calls if not c['backend']),
            'fallbacks': sum(1 for c in calls if c['fallback']),
            'reasons': sorted({c['fallback'] for c in calls if c['fallback']}),
            'input': sum(c['input_tokens'] or 0 for c in calls),
            'output': sum(c['output_tokens'] or 0 for c in calls),
            'seconds': round((timezone.localtime() - self.started_at).total_seconds()),
        }

    def _execution_section(self, u):
        mins, secs = divmod(u['seconds'], 60)
        head = (f"Claude 호출 {u['total']}회 — 구독(CLI) {u['cli']}회 · API {u['api']}회"
                f"{' · 실패 ' + str(u['errors']) + '회' if u['errors'] else ''} / "
                f"토큰 입력 {u['input']:,} · 출력 {u['output']:,} / 총 소요 {mins}분 {secs}초")
        if u['fallbacks']:
            fb = f"⚠ API 폴백 {u['fallbacks']}회 (과금 발생). 사유:\n" + '\n'.join(f'- {r}' for r in u['reasons'])
        else:
            fb = '폴백 없음 — 모든 호출이 구독 경로로 처리되었습니다.' if u['cli'] else 'CLI 백엔드를 쓰지 않았습니다(CLAUDE_BACKEND=api).'

        rows_txt, rows_html = [], []
        for s in self.steps:
            backends = '·'.join(c['backend'] or '실패' for c in s['calls']) or '-'
            if any(c['fallback'] for c in s['calls']):
                backends += ' (폴백)'
            tokens = (f"{sum(c['input_tokens'] or 0 for c in s['calls']):,}/{sum(c['output_tokens'] or 0 for c in s['calls']):,}"
                      if s['calls'] else '-')
            result = '성공' if s['ok'] else '실패'
            rows_txt.append(f"  {result} | {s['label']} | {backends} | {s['seconds']}s | {tokens}"
                            + (f" | {s['note']}" if s['note'] else ''))
            color = '#15803d' if s['ok'] else '#b91c1c'
            rows_html.append(
                f'<tr><td style="{TD};color:{color};font-weight:600">{result}</td><td style="{TD}">{escape(s["label"])}'
                + (f'<br><small style="color:#b91c1c">{escape(s["note"])}</small>' if s['note'] else '')
                + f'</td><td style="{TD}">{escape(backends)}</td><td style="{TD};text-align:right">{s["seconds"]}s</td>'
                f'<td style="{TD};text-align:right">{tokens}</td></tr>')

        text = f"{head}\n{fb}\n\n  결과 | 단계 | 경로 | 소요 | 토큰(입/출)\n" + '\n'.join(rows_txt)
        fb_color = '#b45309' if u['fallbacks'] else '#15803d'
        th = ''.join(f'<th style="{TD};background:#f3f4f6;text-align:left">{h}</th>'
                     for h in ('결과', '단계', '경로', '소요', '토큰(입/출)'))
        html = (f'<p style="margin:0 0 6px">{escape(head)}</p>'
                f'<p style="margin:0 0 10px;color:{fb_color};font-weight:600">{_br(fb)}</p>'
                f'<table style="border-collapse:collapse;width:100%;font-size:13px"><tr>{th}</tr>'
                + ''.join(rows_html) + '</table>')
        return '실행 결과', text, html

    def _decisions_section(self, decisions):
        txt, html = [], []
        for d in decisions:
            label = f"[{d.get_kind_display()}{' · ' + d.topic if d.topic else ''}] {d.question}"
            txt.append(label)
            html.append(f'<p style="margin:14px 0 4px;font-weight:600">{escape(label)}</p><ul style="margin:0;padding-left:20px">')
            for o in d.options:
                by = f" — 제안 {o['proposed_by']}" if o.get('proposed_by') else ''
                txt.append(f"  ({o['key']}) {o['title']}{by}")
                if o.get('detail'):
                    txt.append(f"      {o['detail']}")
                html.append(f'<li style="margin-bottom:6px"><b>({escape(o["key"])}) {escape(o["title"])}</b>'
                            f'<span style="color:#6b7280">{escape(by)}</span>'
                            + (f'<br><span style="color:#374151">{escape(o["detail"])}</span>' if o.get('detail') else '')
                            + '</li>')
            txt.append('')
            html.append('</ul>')
        link = f'{SITE}/lab/admin/'
        txt.append(f'결정하러 가기: {link}')
        html.append(f'<p style="margin-top:14px"><a href="{link}">결정하러 가기 →</a></p>')
        return f'안건과 선택지 ({len(decisions)}건)', '\n'.join(txt), ''.join(html)

    def _transcript_section(self, transcript):
        txt, html = [], []
        for rnd, title in ((1, '1라운드 — 제안'), (2, '2라운드 — 검토·조율')):
            turns = [t for t in transcript if t.get('round') == rnd]
            if not turns:
                continue
            txt.append(f'■ {title}')
            html.append(f'<p style="margin:14px 0 6px;font-weight:700">{title}</p>')
            for t in turns:
                a = AGENTS.get(t['agent'], {'name': t['agent'], 'title': ''})
                txt += [f"{a['name']}({a['title']}):", t['text'], '']
                html.append(f'<div style="margin:0 0 10px;padding:8px 12px;border-left:3px solid #4f46e5;background:#f9fafb">'
                            f'<b>{escape(a["name"])}</b> <span style="color:#6b7280">{escape(a["title"])}</span>'
                            f'<div style="margin-top:4px">{_br(t["text"])}</div></div>')
        return '회의 내용 (발언 전문)', '\n'.join(txt), ''.join(html)

    def _deliver(self, to, subject, lead, sections):
        text = [lead, '']
        html = [f'<div style="font-family:-apple-system,Segoe UI,Malgun Gothic,sans-serif;font-size:14px;'
                f'line-height:1.6;color:#111827;max-width:760px"><p>{escape(lead)}</p>']
        for n, (title, body_txt, body_html) in enumerate(sections, 1):
            text += [f'{"=" * 8} {n}. {title} {"=" * 8}', body_txt, '']
            html.append(f'<h3 style="margin:28px 0 8px;padding-bottom:4px;border-bottom:2px solid #e5e7eb">'
                        f'{n}. {escape(title)}</h3>{body_html}')
        html.append('</div>')
        try:
            msg = EmailMultiAlternatives(subject=subject, body='\n'.join(text),
                                         from_email=settings.DEFAULT_FROM_EMAIL, to=[to])
            msg.attach_alternative(''.join(html), 'text/html')
            msg.send()
            self.stdout.write(f'메일 발송 → {to}')
        except Exception as ex:  # noqa: BLE001
            self.stderr.write(f'메일 발송 실패: {ex}')


SITE = 'https://techchang.com'
TD = 'padding:6px 8px;border:1px solid #e5e7eb;vertical-align:top'
PRE = 'white-space:pre-wrap;font-size:12px;background:#f9fafb;padding:10px;border-radius:6px'


def _br(text):
    return escape(text).replace('\n', '<br>')
