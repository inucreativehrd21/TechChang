import json
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from common.services import claude
from office.models import Meeting

SYNTHESIS = {
    'summary': '이번 주는 HRD 칼럼에 집중한다.',
    'decisions': [{'kind': 'column', 'topic': 'hrd', 'question': '다음 주 HRD 칼럼 주제',
                   'options': [{'key': 'a', 'title': '사내 AI 교육의 ROI', 'detail': '측정 지표 3가지를 다룬다', 'proposed_by': '한빈',
                                'keywords': ['AI 교육 ROI']},
                               {'key': 'b', 'title': '내일배움카드 개편 총정리', 'detail': '11월 바뀌는 것', 'proposed_by': '한빈',
                                'keywords': ['내일배움카드']}]}],
}
TRENDS = {'unit': 'volume', 'note': '', 'sources': {'geeknews': 20, 'google_trends': 20},
          'fields': {'hrd': [{'topic': '내일배움카드 개편', 'why': '11월 제도 변경', 'url': '', 'keywords': ['내일배움카드'],
                              'demand_kw': '내일배움카드', 'demand': 90000, 'demand_note': '월 90,000회 검색'}]}}


def fake_cli(fail_on=()):
    """n번째 호출(0부터)이 fail_on 에 있으면 CLI 실패 → API 폴백을 흉내 낸다."""
    count = {'n': 0}

    def run(prompt, *, system, model):
        n = count['n']
        count['n'] += 1
        if n in fail_on:
            raise claude.CliUnavailable('Claude AI usage limit reached')
        text = json.dumps(SYNTHESIS, ensure_ascii=False) if 'JSON 스키마' in prompt else f'발언 {n}번입니다.'
        return text, {'input_tokens': 100, 'output_tokens': 20}
    return run


class MeetingMailTests(TestCase):
    def setUp(self):
        patches = [
            mock.patch.dict('os.environ', {'CLAUDE_BACKEND': 'cli', 'AI_FALLBACK_BACKEND': ''}),
            mock.patch('office.management.commands.hold_meeting.collect_site_snapshot', return_value={}),
            mock.patch('office.management.commands.hold_meeting.snapshot_as_text', return_value='방문자 120명'),
            mock.patch('office.trends.scout', return_value=TRENDS),
            mock.patch('office.trends.measure', return_value=({'내일배움카드': 90000, 'AI 교육 ROI': 30}, 'volume')),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        claude._fallback_alerted = False

    def test_mail_has_transcript_steps_decisions_and_fallback(self):
        with mock.patch.dict('os.environ', {'AI_ALLOW_PAID_API': 'true', 'CLAUDE_CLI_FALLBACK': 'true'}), \
                mock.patch('common.services.claude._cli_ask', side_effect=fake_cli(fail_on={2})), \
                mock.patch('common.services.claude._api_ask', return_value=('API 발언', {'input_tokens': 5, 'output_tokens': 5})):
            call_command('hold_meeting', email='admin@example.com', stdout=mock.MagicMock())

        self.assertEqual(Meeting.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)  # 회의 메일에 폴백을 담으므로 별도 알림은 없다
        msg = mail.outbox[0]
        self.assertIn('API 폴백 1회', msg.subject)
        body = msg.body
        for expected in ('결론 요약', 'HRD 칼럼에 집중', '실행 결과', 'usage limit reached',
                         '1라운드 · ', '결론 정리', '회의록·안건 저장', '측정 지표 3가지', '제안 한빈',
                         '발언 전문', 'API 발언', '방문자 120명'):
            self.assertIn(expected, body)
        html = msg.alternatives[0][0]
        self.assertIn('<table', html)
        self.assertIn('사내 AI 교육의 ROI', html)

    def test_no_fallback_is_stated_plainly(self):
        with mock.patch('common.services.claude._cli_ask', side_effect=fake_cli()):
            call_command('hold_meeting', email='admin@example.com', stdout=mock.MagicMock())
        msg = mail.outbox[0]
        self.assertNotIn('폴백', msg.subject)
        self.assertIn('폴백 없음', msg.body)

    def test_failure_mid_meeting_still_sends_mail(self):
        def broken(prompt, *, system, model):
            if 'JSON 스키마' in prompt:
                raise RuntimeError('결론 정리 중 오류')
            return '발언', {'input_tokens': 1, 'output_tokens': 1}

        with mock.patch('common.services.claude._cli_ask', side_effect=broken):
            with self.assertRaises(RuntimeError):
                call_command('hold_meeting', email='admin@example.com', stdout=mock.MagicMock())

        self.assertEqual(Meeting.objects.count(), 0)
        msg = mail.outbox[0]
        self.assertIn('편집회의 실패', msg.subject)
        self.assertIn('결론 정리', msg.subject)
        self.assertIn('결론 정리 중 오류', msg.body)
        self.assertIn('발언 전문', msg.body)  # 실패 전까지의 발언도 남긴다

    def test_trend_scout_runs_before_talk_and_options_ranked_by_demand(self):
        from office.models import Decision
        with mock.patch('common.services.claude._cli_ask', side_effect=fake_cli()):
            call_command('hold_meeting', email='admin@example.com', stdout=mock.MagicMock())
        meeting = Meeting.objects.get()
        self.assertEqual(meeting.snapshot['trends']['fields']['hrd'][0]['demand'], 90000)
        opts = Decision.objects.get().options
        self.assertEqual([(o['key'], o['title']) for o in opts], [('a', '내일배움카드 개편 총정리'), ('b', '사내 AI 교육의 ROI')])
        self.assertTrue(opts[0]['recommended'])
        self.assertEqual(opts[0]['demand'], 90000)
        body = mail.outbox[0].body
        self.assertIn('★ 추천(검색 수요 1위) 내일배움카드 개편 총정리', body)
        self.assertIn('트렌드 정찰', body)
        self.assertIn('후보 1개 · GeekNews 20', body)
        self.assertIn("네이버 검색어 '내일배움카드' 월 90,000회 검색", body)
