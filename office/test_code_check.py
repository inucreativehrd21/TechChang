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
