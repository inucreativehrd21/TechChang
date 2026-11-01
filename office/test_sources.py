"""근거 문서 묶음 — 공식 문서를 코드가 받아 문단으로 나누고, 원고와 관련 있는 문단으로 대조한다(office.sources)."""
import socket
from unittest import mock

from django.test import SimpleTestCase

from office import evidence as E
from office import grounded as GR
from office import model_router as R
from office import sources as SRC

URL = 'https://docs.djangoproject.com/en/5.2/ref/models/querysets/'
PAGE = '''<html><head><title>QuerySet API reference | Django documentation</title><script>var x=1;</script></head>
<body><nav>Home Download Documentation menu links that are long enough to be a block of text here</nav>
<h2>select_related()<a>¶</a></h2>
<p>Returns a QuerySet that will "follow" foreign-key relationships, selecting additional related-object data
when it executes its query.</p>
<p>select_related is limited to single-valued relationships - foreign key and one-to-one.</p>
<h2>prefetch_related()</h2>
<p>prefetch_related, on the other hand, does a separate lookup for each relationship, and does the joining in Python.</p>
<h2>Unrelated</h2><p>Aggregation functions compute summary values over the whole queryset for reporting.</p>
</body></html>'''


def public(host, port, proto=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('151.101.1.1', port))]


class AllowedTests(SimpleTestCase):
    def test_only_https_public_hosts(self):
        with mock.patch('office.sources.socket.getaddrinfo', side_effect=public):
            self.assertTrue(SRC.allowed(URL))
            self.assertFalse(SRC.allowed('http://docs.djangoproject.com/x'))
            self.assertFalse(SRC.allowed('https://example.org/x'))
            self.assertFalse(SRC.allowed('https://user@docs.djangoproject.com/x'))
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 443))]
        with mock.patch('office.sources.socket.getaddrinfo', return_value=private):
            self.assertFalse(SRC.allowed('https://internal.corp/x'))

    def test_urls_are_normalized_and_deduplicated(self):
        self.assertEqual(SRC.urls_in(f'{URL}#select-related 그리고 ({URL}).'), [URL])


class ParagraphTests(SimpleTestCase):
    def test_html_keeps_body_text_with_section_and_drops_scripts_and_nav(self):
        title, paras = SRC.paragraphs(PAGE)
        self.assertEqual(title, 'QuerySet API reference | Django documentation')
        text = ' '.join(p['text'] for p in paras)
        self.assertIn('single-valued relationships', text)
        self.assertNotIn('var x', text)
        self.assertNotIn('Download Documentation', text)
        self.assertEqual(paras[0]['section'], 'select_related()')


class CorpusTests(SimpleTestCase):
    def corpus(self):
        c = SRC.Corpus()
        with mock.patch.object(SRC, 'allowed', return_value=True), \
                mock.patch.object(SRC, '_download', return_value=(PAGE, 'text/html; charset=utf-8')) as dl:
            c.add([URL, URL + '#x', 'https://down.example/y'])
        return c, dl

    def test_each_url_fetched_once(self):
        c, dl = self.corpus()
        self.assertEqual(dl.call_count, 2)          # 같은 문서는 한 번, 다른 주소는 따로(여기선 같은 응답)
        self.assertEqual(c.docs[URL]['version'], '5.2')

    def test_select_prefers_paragraphs_sharing_rare_identifiers(self):
        c, _ = self.corpus()
        picked = c.select('역방향 FK에는 select_related 대신 prefetch_related를 써요. single-valued 관계만 JOIN 해요.')
        texts = ' '.join(p['text'] for p in picked)
        self.assertIn('single-valued', texts)
        self.assertNotIn('Aggregation', texts)

    def test_disabled_by_setting(self):
        c = SRC.Corpus()
        with mock.patch.dict('os.environ', {'OFFICE_SOURCE_FETCH': '0'}), \
                mock.patch.object(SRC, '_download') as dl:
            c.add([URL])
        dl.assert_not_called()


class DocumentGroundingTests(SimpleTestCase):
    def test_document_paragraph_supports_claim_through_contract(self):
        c, _ = CorpusTests().corpus()
        items = GR.entries(documents=SRC.entries(c.select('select_related single-valued foreign key one-to-one')))
        self.assertTrue(items and items[0]['kind'] == 'document')
        self.assertIn('[문서]', GR.ledger_text(items))
        e = next(i for i in items if 'single-valued' in i['quote'])
        claim = GR.attach({'claim': 'select_related는 FK와 일대일 같은 단일값 관계에만 써요.', 'status': 'verified',
                           'evidence': e['id'],
                           'quote': 'select_related is limited to single-valued relationships - foreign key and one-to-one.'},
                          {i['id']: i for i in items})
        with R.use_profile('b'):
            checked = E.validate_check({'claims': [claim]})
        self.assertEqual(checked['claims'][0]['status'], 'verified', checked['claims'][0].get('note'))
        self.assertIn('5.2판 문서', checked['claims'][0]['period'])


class CoverageSelectTests(SimpleTestCase):
    def test_every_code_identifier_gets_a_paragraph_before_filling_by_score(self):
        c = SRC.Corpus()
        filler = [{'section': 'x', 'text': 'prefetch_related joins in Python. ' * 30} for _ in range(5)]
        rare = {'section': 'assertNumQueries()', 'text': 'assertNumQueries asserts that num database queries are executed.'}
        c.docs[URL] = {'title': 'Doc', 'version': '5.2', 'paras': filler + [rare]}
        picked = c.select('prefetch_related 와 assertNumQueries 를 써요.', budget=len(filler[0]['text']) + 200)
        self.assertTrue(any('assertNumQueries' in p['text'] for p in picked))
