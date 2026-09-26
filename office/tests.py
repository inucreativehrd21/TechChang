"""정비반 패치 적용 회귀 테스트.

apply_edits 가 원본 줄바꿈을 바꿔버리면 10줄짜리 수정이 파일 전체 diff 로 번져
PR 을 읽을 수 없게 된다 (실제로 853줄 diff 가 나왔다). 그 재발을 막는다.
"""
import os
import tempfile

from django.test import TestCase

from office.maintenance import apply_edits


class ApplyEditsNewlineTests(TestCase):
    def setUp(self):
        self.wt = tempfile.mkdtemp()

    def _write(self, rel, data: bytes):
        path = os.path.join(self.wt, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        return path

    def _read(self, rel) -> bytes:
        with open(os.path.join(self.wt, rel), 'rb') as f:
            return f.read()

    def test_crlf_file_keeps_crlf(self):
        self._write('app/mod.py', b'a = 1\r\nb = 2\r\nc = 3\r\n')
        done, errs = apply_edits(self.wt, [
            {'path': 'app/mod.py', 'action': 'replace', 'find': 'b = 2', 'replace': 'b = 99'}])
        self.assertEqual((done, errs), (['app/mod.py'], []))
        self.assertEqual(self._read('app/mod.py'), b'a = 1\r\nb = 99\r\nc = 3\r\n')

    def test_lf_file_keeps_lf(self):
        self._write('app/mod.py', b'a = 1\nb = 2\n')
        apply_edits(self.wt, [
            {'path': 'app/mod.py', 'action': 'replace', 'find': 'b = 2', 'replace': 'b = 99'}])
        self.assertEqual(self._read('app/mod.py'), b'a = 1\nb = 99\n')

    def test_find_uses_lf_even_in_crlf_file(self):
        """모델은 항상 \\n 으로 된 조각을 준다 — CRLF 파일에서도 매칭돼야 한다."""
        self._write('app/mod.py', b'def f():\r\n    return 1\r\n')
        done, errs = apply_edits(self.wt, [
            {'path': 'app/mod.py', 'action': 'replace',
             'find': 'def f():\n    return 1', 'replace': 'def f():\n    return 2'}])
        self.assertEqual((done, errs), (['app/mod.py'], []))
        self.assertEqual(self._read('app/mod.py'), b'def f():\r\n    return 2\r\n')

    def test_denied_paths_are_rejected(self):
        self._write('logs/django.log', b'x\n')
        done, errs = apply_edits(self.wt, [
            {'path': 'logs/django.log', 'action': 'replace', 'find': 'x', 'replace': 'y'}])
        self.assertEqual(done, [])
        self.assertEqual(len(errs), 1)

    def test_escape_outside_worktree_is_rejected(self):
        done, errs = apply_edits(self.wt, [
            {'path': '../outside.py', 'action': 'create', 'content': 'x = 1\n'}])
        self.assertEqual(done, [])
        self.assertEqual(len(errs), 1)
