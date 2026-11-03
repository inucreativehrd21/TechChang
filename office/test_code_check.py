"""코드 예제 점검 — 문서 대조로 못 잡는 코드 결함을 정적 점검과 실행으로 확인한다(office.code_check)."""
import os
from unittest import mock

from django.test import SimpleTestCase

from office import code_check as CC

MODELS = '''```python
# blog/models.py
from django.db import models

class Author(models.Model):
    name = models.CharField(max_length=50)

class Tag(models.Model):
    name = models.CharField(max_length=30)

class Post(models.Model):
    title = models.CharField(max_length=100)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    tags = models.ManyToManyField(Tag)
```
'''

TESTS = '''```python
# blog/tests.py
from django.test import TestCase
from .models import Author, Post, Tag

def listing():
    return Post.objects.select_related("author").prefetch_related("tags")

class PostListQueryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        author = Author.objects.create(name="kim")
        tag = Tag.objects.create(name="django")
        for i in range(5):
            Post.objects.create(title=f"post {i}", author=author).tags.add(tag)

    def test_post_list_queries(self):
        with self.assertNumQueries(__N__):
            for post in listing():
                _ = post.author.name
                _ = [t.name for t in post.tags.all()]
```
'''

VIEW = '''```python
# albums/views.py
from rest_framework import viewsets
from .serializers import AlbumSerializer

class AlbumViewSet(viewsets.ModelViewSet):
    serializer_class = AlbumSerializer
```
'''


class StaticTests(SimpleTestCase):
    def test_test_method_outside_class_is_flagged(self):
        # 2026-10-31 조정 전 B 파일럿의 수정본에서 실제로 나온 모양
        body = ('```python\nfrom django.test import TestCase\n\nclass EntryQueryTests(TestCase):\n'
                '    def setUp(self):\n        pass\n\ndef test_select_related_uses_one_query(self):\n'
                '        with self.assertNumQueries(1):\n            pass\n```\n')
        issues = CC.static_issues(body)
        self.assertEqual(len(issues), 1)
        self.assertIn('test_select_related_uses_one_query', issues[0])

    def test_method_excerpt_and_indented_snippet_are_not_flagged(self):
        body = ('```python\ndef get_queryset(self):\n    return Album.objects.prefetch_related("tracks")\n```\n'
                '```python\n    posts = Post.objects.all()\n```\n')
        self.assertEqual(CC.static_issues(body), [])

    def test_syntax_error_is_flagged(self):
        self.assertIn('파싱되지 않아요', CC.static_issues('```python\ndef broken(:\n    pass\n```\n')[0])


class AssembleTests(SimpleTestCase):
    def test_skips_view_blocks_and_project_imports(self):
        models_py, tests_py, expected = CC.assemble(MODELS + VIEW + TESTS.replace('__N__', '2'))
        self.assertNotIn('serializers', models_py + tests_py)
        self.assertNotIn('from .models import Author', tests_py)      # 임시 앱의 .models * 로 대신한다
        self.assertIn('def listing', tests_py)                        # 테스트 블록의 보조 함수는 옮긴다
        self.assertEqual(expected, {'test_post_list_queries': [2]})

    def test_needs_models_and_tests(self):
        self.assertIsNone(CC.assemble(MODELS))
        self.assertIsNone(CC.assemble(VIEW))


class FactsTests(SimpleTestCase):
    RESULT = {'ran': True, 'django': '5.2.6', 'tests': [
        {'name': 'test_a', 'status': 'passed', 'message': '', 'expected': [2]},
        {'name': 'test_b', 'status': 'failed', 'message': 'AssertionError: 2 != 0 : 2 queries executed, 0 expected',
         'expected': []},
        {'name': 'test_c', 'status': 'error', 'message': "NameError: name 'Blog' is not defined", 'expected': []}]}

    def test_failures_exclude_environment_problems(self):
        block = CC.facts(self.RESULT)
        self.assertIn('test_a: 통과 (assertNumQueries 2회)', block)
        self.assertIn('실제 실행 2회, 본문 기대 0회', block)
        self.assertEqual([f.split(':')[0] for f in CC.failures(block)], ['test_b'])

    def test_replace_keeps_other_evidence(self):
        pack = CC.replace('- 근거 A', CC.facts(self.RESULT)) + '\n- 근거 B — 검증관 확인'
        new = CC.replace(pack, '')
        self.assertEqual(new, '- 근거 A\n- 근거 B — 검증관 확인')
        self.assertEqual(CC.failures(new), [])


class RunTests(SimpleTestCase):
    def test_disabled_by_default(self):
        with mock.patch.dict(os.environ, {'OFFICE_CODE_RUN': ''}):
            self.assertFalse(CC.run_examples(MODELS + TESTS.replace('__N__', '2'))['ran'])

    def test_runs_examples_in_separate_process(self):
        with mock.patch.dict(os.environ, {'OFFICE_CODE_RUN': '1'}):
            ok = CC.run_examples(MODELS + TESTS.replace('__N__', '2'))
            wrong = CC.run_examples(MODELS + TESTS.replace('__N__', '1'))
        self.assertTrue(ok['ran'], ok)
        self.assertEqual([t['status'] for t in ok['tests']], ['passed'])
        self.assertEqual([f.split(':')[0] for f in CC.failures(CC.facts(wrong))], ['test_post_list_queries'])
        self.assertIn('실제 실행 2회, 본문 기대 1회', CC.facts(wrong))


# 여러 파일로 나눈 예제 — 2026-11-02 atomic 파일럿에서 services.py 블록이 빠져 NameError 로 전부 실패했다
SPLIT = '''```python
# shop/models.py
from django.db import models

class Order(models.Model):
    item = models.CharField(max_length=100)
```

```python
# shop/services.py
from django.db import transaction

from .models import Order


class PaymentError(Exception):
    pass


def place(item, fail=False):
    with transaction.atomic():
        order = Order.objects.create(item=item)
        if fail:
            raise PaymentError(item)
    return order
```

```python
# shop/tests.py
from django.test import TestCase

from shop.models import Order
from shop.services import PaymentError, place


class PlaceTests(TestCase):
    def test_rolls_back(self):
        with self.assertRaises(PaymentError):
            place("book", fail=True)
        self.assertEqual(Order.objects.count(), 0)
```
'''


class SupportModuleTests(SimpleTestCase):
    def test_path_header_blocks_are_support_modules(self):
        self.assertEqual({k: v[0] for k, v in CC.support_modules(SPLIT).items()}, {'services': 'shop'})
        # 모델·테스트·뷰 같은 예약 이름과 클래스가 든 블록은 보조 모듈이 아니다
        self.assertEqual(CC.support_modules(MODELS + TESTS.replace('__N__', '2')), {})

    def test_tests_import_support_module_but_models_do_not(self):
        models_py, tests_py, _ = CC.assemble(SPLIT)
        self.assertIn('from .services import PaymentError, place', tests_py)   # shop.services → .services
        self.assertNotIn('services', models_py)                                  # models ← services 순환 방지

    def test_runs_split_example(self):
        with mock.patch.dict(os.environ, {'OFFICE_CODE_RUN': '1'}):
            result = CC.run_examples(SPLIT)
        self.assertTrue(result['ran'], result)
        self.assertEqual([(t['name'], t['status']) for t in result['tests']], [('test_rolls_back', 'passed')])


class FormatIssueTests(SimpleTestCase):
    """튜토리얼 실행 예제 형식 — 실행기를 넓히지 않고 형식을 고정한다(2026-11-02 atomic 2차·select 4차)."""
    STANDALONE = ('```python\n# welcome_test.py\nimport django\nfrom django.conf import settings\n'
                  'settings.configure(INSTALLED_APPS=["django.contrib.auth"])\ndjango.setup()\n```\n')

    def test_runnable_split_example_passes(self):
        self.assertEqual(CC.format_issues(SPLIT), [])
        self.assertEqual(CC.format_issues(MODELS + TESTS.replace('__N__', '2')), [])

    def test_standalone_script_and_missing_tests_are_flagged(self):
        issues = CC.format_issues(self.STANDALONE)
        self.assertEqual(len(issues), 2)
        self.assertIn('혼자 실행하는 스크립트', issues[0])
        self.assertIn('# 앱/tests.py', issues[1])

    def test_no_code_no_issue(self):
        self.assertEqual(CC.format_issues('## 실행 예제\n\n코드는 없습니다.'), [])


class RunFirstTests(SimpleTestCase):
    """튜토리얼(B): 실행할 수 없는 예제는 사실 검증 전에 한 번 고치고, 고친 원고로 다시 실행한다."""
    def _run(self, content, fixed):
        from office.management.commands.office_publish import Command
        cmd = Command()
        logs, records = [], []
        stages = mock.Mock(stages=[], record=lambda *a, **k: records.append((a, k)))
        with mock.patch('office.management.commands.office_publish.P.step_fix_draft',
                        return_value=('제목', fixed, [])) as fix, \
                mock.patch.object(Command, '_code_facts', return_value='pack-after') as facts:
            out = cmd._run_first(stages, lambda *a: logs.append(a), lambda s, a, fn, **k: fn(), 'coding', 'coding',
                                 '제목', content, 'pack', 'tutorial')
        return out, fix, facts, logs

    def test_unrunnable_example_is_fixed_before_fact_check(self):
        out, fix, facts, logs = self._run(FormatIssueTests.STANDALONE, SPLIT)
        self.assertEqual(out, ('제목', SPLIT, 'pack-after'))
        self.assertIn('혼자 실행하는 스크립트', fix.call_args.args[3][0])
        facts.assert_called_once()
        self.assertTrue(any('사실 검증 전에' in str(l) for l in logs))

    def test_runnable_example_goes_straight_on(self):
        out, fix, facts, logs = self._run(SPLIT, SPLIT)
        self.assertEqual(out, ('제목', SPLIT, 'pack'))
        fix.assert_not_called()
        facts.assert_not_called()


# 2026-11-03 atomic 3차 — 형식은 지켰지만 실행기 빈틈으로 오류 14건: 모듈째 import, 앱 경로 mock.patch, 일부러 실패하는 예시
SPLIT_MODULE = SPLIT.replace('from shop.services import PaymentError, place', 'from . import services') \
    .replace('PaymentError):\n            place(', 'services.PaymentError):\n            services.place(') + '''
```python
# shop/tests_wrong.py — 잘못된 예 (이 테스트는 실패합니다)
from django.test import TestCase


class WrongTests(TestCase):
    def test_wrong(self):
        self.assertEqual(1, 2)
```

```python
# shop/test_patch.py
from unittest import mock

from django.test import TestCase

from . import services


class PatchTests(TestCase):
    def test_patch_by_app_path(self):
        with mock.patch("shop.services.place", return_value="patched"):
            self.assertEqual(services.place("x"), "patched")
```
'''


class AppPathTests(SimpleTestCase):
    def test_app_label_follows_headers(self):
        self.assertEqual(CC.app_label(SPLIT), 'shop')
        self.assertEqual(CC.app_label('```python\n# json/models.py\nx = 1\n```'), 'colapp')   # 표준 라이브러리와 겹침
        self.assertEqual(CC.app_label('```python\nx = 1\n```'), 'colapp')                       # 머리글 없음

    def test_module_import_patch_path_and_wrong_example(self):
        models_py, tests_py, _ = CC.assemble(SPLIT_MODULE)
        self.assertIn('from . import services', tests_py)
        self.assertNotIn('WrongTests', tests_py)                  # 설명이 붙은 '잘못된 예' 블록은 빠진다
        with mock.patch.dict(os.environ, {'OFFICE_CODE_RUN': '1'}):
            result = CC.run_examples(SPLIT_MODULE)
        self.assertTrue(result['ran'], result)
        self.assertEqual(sorted((t['name'], t['status']) for t in result['tests']),
                         [('test_patch_by_app_path', 'passed'), ('test_rolls_back', 'passed')])


class RunFirstOverclaimTests(SimpleTestCase):
    def test_overclaim_sentence_is_fixed_before_fact_check(self):
        content = SPLIT + '\n이 방법은 항상 한 번의 커밋으로 끝납니다.\n'     # '~없습니다' 같은 부정문은 단정이 아니다
        out, fix, facts, logs = RunFirstTests._run(self, content, SPLIT)
        self.assertTrue(any('단정·일반화 문장' in i for i in fix.call_args.args[3]))
        facts.assert_called_once()
