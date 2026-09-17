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
from datetime import timedelta

from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

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
        # 일요일 저녁에 돌리면 '다음 주' 회의로 기록
        today = timezone.localdate()
        week = week_monday(today + timedelta(days=1)) if today.weekday() == 6 else week_monday(today)
        if not opts['force'] and Meeting.objects.filter(week_start=week).exists():
            self.stdout.write(f'{week} 주차 회의가 이미 있습니다. --force 로 다시 개최할 수 있습니다.')
            return

        self.stdout.write(f'[{timezone.localtime():%H:%M:%S}] {week} 주차 편집회의 소집 — 지표 수집 중...')
        snap = collect_site_snapshot()
        brief = snapshot_as_text(snap)

        transcript = []

        def tx():
            return '\n'.join(f"{AGENTS[t['agent']]['name']}({AGENTS[t['agent']]['title']}): {t['text']}" for t in transcript) or '(아직 없음)'

        def who(k):
            return f"{AGENTS[k]['name']}({AGENTS[k]['title']})"

        for rnd, template in ((1, ROUND1), (2, ROUND2)):
            for key in MEETING_ORDER:
                if rnd == 2 and key == 'lead':
                    continue  # 팀장은 2라운드 대신 결론 정리를 맡는다
                prompt = template.format(who=who(key), brief=brief, transcript=tx(), task=TASKS.get(key, ''))
                text = ask_agent(key, prompt, max_tokens=1500)
                transcript.append({'agent': key, 'round': rnd, 'text': text})
                self.stdout.write(f'  R{rnd} {who(key)}: {text[:60]}...')

        result = ask_agent_json('lead', SYNTHESIS.format(brief=brief, transcript=tx()), max_tokens=8000)
        decisions = [d for d in result.get('decisions', []) if isinstance(d, dict) and d.get('options')]
        summary = str(result.get('summary', '')).strip()
        self.stdout.write(f'  결론: {summary[:80]}... / 안건 {len(decisions)}건')

        if opts['dry_run']:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
            return

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

        if opts['email']:
            self._send_mail(opts['email'], meeting)

    def _send_mail(self, to, meeting):
        lines = [f'{meeting.week_start} 주차 편집회의가 끝났습니다.', '', meeting.summary, '', '안건:']
        for d in meeting.decisions.all():
            lines.append(f"- [{d.get_kind_display()}{' · ' + d.topic if d.topic else ''}] {d.question}")
            for o in d.options:
                lines.append(f"    ({o['key']}) {o['title']} — {o.get('proposed_by', '')}")
        lines += ['', '결정: https://techchang.com/lab/admin/']
        try:
            EmailMessage(subject=f'[TechChang] {meeting.week_start} 편집회의 결과 — 결정 {meeting.decisions.count()}건 대기',
                         body='\n'.join(lines), to=[to]).send()
            self.stdout.write(f'메일 발송 → {to}')
        except Exception as ex:  # noqa: BLE001
            self.stderr.write(f'메일 발송 실패: {ex}')
