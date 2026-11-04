"""Regression coverage for the Claude CLI activity-based watchdog."""

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as ax


FAKE_CLI = r'''
import json
import os
import sys
import time

sys.stdin.read()
mode = os.getenv('AX_CLI_WATCHDOG_CASE', 'streaming')
def emit(data):
    print(json.dumps(data), flush=True)

emit({'type':'system', 'subtype':'init', 'model':'test-model'})
if mode == 'streaming':
    for i in range(9):
        emit({'type':'stream_event', 'event':{
            'delta':{'type':'thinking_delta', 'thinking':'PRIVATE_THINKING_NOT_FOR_GUI'}}})
        time.sleep(0.12)
elif mode == 'assistant_streaming':
    for i in range(9):
        emit({'type':'assistant', 'message':{'content':[
            {'type':'text', 'text':'Checking the request.'}]}})
        time.sleep(0.12)
elif mode == 'init_only':
    time.sleep(2)
elif mode == 'silent':
    time.sleep(2)
elif mode == 'stall_after_stream':
    emit({'type':'stream_event', 'event':{'delta':{'type':'thinking_delta', 'thinking':'PRIVATE'}}})
    time.sleep(2)
elif mode == 'stall_after_assistant':
    emit({'type':'assistant', 'message':{'content':[
        {'type':'text', 'text':'Still examining.'}]}})
    time.sleep(2)
emit({'type':'result', 'is_error':False, 'structured_output':{
    'targets':[], 'reason':'done', 'question':''}})
'''


class ClaudeActivityWatchdogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temp.name) / 'claude'
        cls.binary.write_text(f'#!{sys.executable} -S\n' + FAKE_CLI, encoding='utf-8')
        cls.binary.chmod(0o700)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def call(self, mode):
        events = []
        started = time.monotonic()
        with (patch.object(ax.shutil, 'which', return_value=str(self.binary)),
              patch.object(ax, 'CLAUDE_STARTUP_TIMEOUT_SECONDS', 0.4),
              patch.object(ax, 'CLAUDE_IDLE_TIMEOUT_SECONDS', 0.4),
              patch.object(ax, 'CLAUDE_POLL_INTERVAL_SECONDS', 0.025),
              patch.dict(os.environ, {'AX_CLI_WATCHDOG_CASE': mode})):
            try:
                result = ax.run_claude_task('safe mock task', ax.CLAUDE_TARGET_SCHEMA,
                                            on_event=lambda *event: events.append(event))
                return result, events, time.monotonic() - started
            except ax.ApiError as err:
                return err, events, time.monotonic() - started

    def test_streaming_heartbeats_extend_wallclock_beyond_startup_window(self):
        result, events, duration = self.call('streaming')
        self.assertIsInstance(result, dict)
        self.assertEqual(result['reason'], 'done')
        self.assertGreater(duration, 0.8)
        transcript = '\n'.join(str(e) for e in events)
        self.assertNotIn('PRIVATE_THINKING_NOT_FOR_GUI', transcript)
        self.assertIn('cli_succeeded', transcript)

    def test_assistant_messages_extend_lease_without_total_deadline(self):
        result, events, duration = self.call('assistant_streaming')
        self.assertIsInstance(result, dict)
        self.assertGreater(duration, 0.8)
        self.assertTrue(any(e[0] == 'assistant' for e in events))

    def test_init_only_is_not_real_model_response(self):
        result, events, duration = self.call('init_only')
        self.assertIsInstance(result, ax.ApiError)
        self.assertEqual(result.status, 504)
        self.assertIn('did not start', str(result))
        self.assertLess(duration, 1.5)

    def test_silent_cli_has_startup_timeout(self):
        result, _, _ = self.call('silent')
        self.assertIsInstance(result, ax.ApiError)
        self.assertEqual(result.status, 504)
        self.assertIn('did not start', str(result))

    def test_stalled_stream_still_times_out_safely(self):
        result, events, _ = self.call('stall_after_stream')
        self.assertIsInstance(result, ax.ApiError)
        self.assertEqual(result.status, 504)
        self.assertIn('response stopped', str(result))
        self.assertTrue(any(e[-1] == 'responding' for e in events))

    def test_assistant_response_then_silence_is_not_infinite_wait(self):
        result, _, _ = self.call('stall_after_assistant')
        self.assertIsInstance(result, ax.ApiError)
        self.assertEqual(result.status, 504)
        self.assertIn('response stopped', str(result))


if __name__ == '__main__':
    unittest.main()
