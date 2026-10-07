import os
import threading
import time
from unittest import mock

from django.test import SimpleTestCase

from common.services import claude
from office.concurrency import fan_out, parallel_enabled


class FanOutTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ('OFFICE_PARALLEL', 'OFFICE_AGENT_SPOOL', 'OFFICE_SPOOL_PARALLEL', 'OFFICE_MAX_WORKERS'):
            os.environ.pop(k, None)

    def test_results_keep_input_order_and_run_concurrently(self):
        def slow(v, delay):
            def fn():
                time.sleep(delay)
                return v
            return fn
        started = time.monotonic()
        res = fan_out({'a': slow('A', 0.3), 'b': slow('B', 0.1), 'c': slow('C', 0.2)})
        elapsed = time.monotonic() - started
        self.assertEqual(list(res), ['a', 'b', 'c'])
        self.assertEqual([o.value for o in res.values()], ['A', 'B', 'C'])
        self.assertLess(elapsed, 0.5)   # 직렬이면 0.6초 이상

    def test_failure_is_isolated(self):
        def boom():
            raise ValueError('깨짐')
        res = fan_out({'ok': lambda: 1, 'bad': boom})
        self.assertTrue(res['ok'].ok)
        self.assertFalse(res['bad'].ok)
        self.assertIn('ValueError', res['bad'].error)

    def test_serial_when_disabled_or_in_spool_mode(self):
        os.environ['OFFICE_PARALLEL'] = '0'
        self.assertFalse(parallel_enabled())
        os.environ.pop('OFFICE_PARALLEL')
        os.environ['OFFICE_AGENT_SPOOL'] = '/tmp/x'
        self.assertFalse(parallel_enabled())
        os.environ['OFFICE_SPOOL_PARALLEL'] = '1'
        self.assertTrue(parallel_enabled())

        os.environ.pop('OFFICE_SPOOL_PARALLEL')
        names = fan_out({'a': lambda: threading.current_thread().name,
                         'b': lambda: threading.current_thread().name})
        self.assertEqual({o.value for o in names.values()}, {threading.current_thread().name})

    def test_context_vars_reach_workers(self):
        with claude.call_tags(run_id='r1'):
            res = fan_out({'a': lambda: claude._call_tags.get().get('run_id'),
                           'b': lambda: claude._call_tags.get().get('run_id')})
        self.assertEqual([o.value for o in res.values()], ['r1', 'r1'])


class CallTrackingTests(SimpleTestCase):
    def test_parallel_calls_land_in_their_own_filtered_tracker(self):
        def fake_cli(prompt, *, system, model):
            time.sleep(0.05)
            return prompt, {'input_tokens': 1, 'output_tokens': 1}

        with mock.patch.dict(os.environ, {'CLAUDE_BACKEND': 'cli'}), \
                mock.patch('common.services.claude._cli_ask', side_effect=fake_cli), \
                claude.track_calls(alert=False, filter={'run_id': 'A'}) as calls_a, \
                claude.track_calls(alert=False, filter={'run_id': 'B'}) as calls_b, \
                claude.track_calls(alert=False) as all_calls:
            def call(run, n):
                with claude.call_tags(run_id=run, stage=f's{n}'):
                    claude.ask(f'{run}{n}')
            threads = [threading.Thread(target=call, args=(r, n)) for r in 'AB' for n in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(calls_a), 3)
        self.assertEqual(len(calls_b), 3)
        self.assertEqual(len(all_calls), 6)
        self.assertTrue(all(c['tags']['run_id'] == 'A' for c in calls_a))
