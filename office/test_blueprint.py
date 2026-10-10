"""집필 설계도와 사전 검증 — 본문을 쓰기 전에 주장·근거를 확정한다."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from community import series_catalog as C
from community.models import Category, ColumnSeries, Question
from office import blueprint as B

BP = {'reader_question': 'jj를 지금 팀 저장소에 써도 되나?', 'thesis': '훅·LFS·속성이 걸리면 아직 막힌다',
      'sections': [{'heading': '숫자로 보는 현황', 'point': '기능 표 20행'}],
      'claims': [{'claim': '기능 표는 20개 행이다', 'source': 'docs', 'kind': 'doc'},
                 {'claim': '공식 문서가 제약 11개를 분류했다', 'source': '?', 'kind': 'doc'},
                 {'claim': 'jj arrange 가 rebase -i 를 대신한다', 'source': '?', 'kind': 'code'}],
      'key_table': {'title': '점검 대상 11개의 영향도 점수', 'columns': ['항목', '등급']},
      'visual': '영향도 등급 분포', 'promises': ['막히는 3가지 → 숫자로 보는 현황']}
VER = {'claims': [{'claim': '기능 표는 20개 행이다', 'status': 'verified', 'note': 'https://docs.jj-vcs.dev'},
                  {'claim': '공식 문서가 제약 11개를 분류했다', 'status': 'wrong', 'note': ''},
                  {'claim': 'jj arrange 가 rebase -i 를 대신한다', 'status': 'unverifiable', 'note': ''}],
       'thesis_ok': False, 'thesis_note': '"공식 문서상 대안 안내 없음"으로 한정'}


class BlueprintBlockTests(SimpleTestCase):
    def test_only_verified_claims_are_usable_and_the_rest_are_forbidden(self):
        text = B.block(BP, VER)
        usable, forbidden = text.split('쓰면 안 되는 주장')
        self.assertIn('기능 표는 20개 행이다', usable)
        self.assertIn('공식 문서가 제약 11개를 분류했다', forbidden)       # 틀렸는데 고친 표현이 없으면 금지
        self.assertIn('jj arrange', forbidden)
        self.assertIn('### 표 1. 점검 대상 11개의 영향도 점수', text)       # 핵심 표는 실제로 싣게
        self.assertIn('공식 문서상 대안 안내 없음', text)                    # 답의 범위를 검증관이 좁힘

    def test_no_blueprint_means_no_block(self):
        self.assertEqual(B.block({}, {}), '')
        self.assertEqual(B.make_blueprint('coding', 'x', ask_json=lambda *a, **k: {'thesis': ''}), {})
        self.assertIn('2개 중 1개', B.summary({'claims': [1, 2]}, {'claims': [{'status': 'verified'}]}))


class SeriesBlueprintFlowTests(TestCase):
    def test_writer_receives_the_verified_blueprint(self):
        cat = Category.objects.create(name='프로그래밍')
        User.objects.create_user(Question.BOT_USERNAME, password='x')
        ColumnSeries.objects.create(slug=C.SERIES['agent']['slug'], title='t', category=cat, total_episodes=10)
        seen = {}

        def ask_json(key, prompt, **kw):
            if key == 'coding' and '설계도를 먼저' in prompt:
                return BP
            if key == 'checker' and '사전 검증' in prompt:
                return VER
            return {}

        def ask(key, prompt, **kw):
            seen.setdefault('draft', prompt)
            raise RuntimeError('집필은 여기서 멈춘다')        # 프롬프트만 확인

        from office import series_pipeline as S
        with mock.patch('office.series_pipeline.ask_agent_json', side_effect=ask_json), \
             mock.patch('office.series_pipeline.ask_agent', side_effect=ask), \
             mock.patch('office.series_pipeline.live'):
            S.produce_episode('agent', 1, out=lambda *_: None)
        self.assertIn('확인된 설계도', seen['draft'])
        self.assertIn('쓰면 안 되는 주장', seen['draft'])
