"""Run: python3 -m unittest discover -s tests -v"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ax_code_dev_app", ROOT / "app.py")
ax = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ax)
HTTP = build_opener(ProxyHandler({}))
DEMO_FILE = ROOT / "demo_workspace/drivers/power/supply/ax_ifpmic_charger.c"


class FakeOllamaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({"models": [{"name": "fake-kernel:latest"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers(); self.wfile.write(payload)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        prompt = body["prompt"]
        original = prompt.split("File contents START\n", 1)[1].rsplit("\nFile contents END", 1)[0]
        generated = json.dumps({"summary": "모의 모델 생성", "rationale": "테스트 주석 추가", "risk": "낮음",
                                "checks": ["Diff 확인"], "new_content": original + "\n/* generated sample */\n"})
        payload = json.dumps({"response": generated}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers(); self.wfile.write(payload)

    def log_message(self, *_):
        pass


class ApiFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_tempdir = tempfile.TemporaryDirectory()
        ax.CONFIG_FILE = Path(cls.config_tempdir.name) / "profiles.json"
        cls.original = DEMO_FILE.read_bytes()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ax.Handler)
        ax.PORT = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{ax.PORT}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.fake_ollama = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
        cls.fake_thread = threading.Thread(target=cls.fake_ollama.serve_forever, daemon=True)
        cls.fake_thread.start()
        ax.OLLAMA_HOST = f"http://127.0.0.1:{cls.fake_ollama.server_address[1]}"
        cls.target = "drivers/power/supply/ax_ifpmic_charger.c"

    @classmethod
    def tearDownClass(cls):
        DEMO_FILE.write_bytes(cls.original)
        cls.server.shutdown(); cls.server.server_close()
        cls.fake_ollama.shutdown(); cls.fake_ollama.server_close()
        cls.config_tempdir.cleanup()

    def setUp(self):
        DEMO_FILE.write_bytes(self.original)
        ax.PROPOSALS.clear()
        ax.RECENT.clear()
        ax.CONFIG_FILE.unlink(missing_ok=True)
        ax.save_profile(ax.DEMO.resolve(), ax.default_profile(ax.DEMO.resolve()))

    def api(self, route, body=None, token=True, host=None):
        headers = {}
        if body is not None:
            headers['Content-Type'] = 'application/json'
            if token:
                headers['X-AX-Token'] = ax.CSRF
            data = json.dumps(body).encode()
        else:
            data = None
        if host:
            headers['Host'] = host
        req = Request(self.base + route, data=data, headers=headers,
                      method='POST' if body is not None else 'GET')
        try:
            with HTTP.open(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def new_proposal(self, engine='demo'):
        status, data = self.api('/api/propose', {
            'workspace': str(ax.DEMO), 'target': self.target,
            'engine': engine, 'model': 'fake-kernel:latest' if engine == 'ollama' else '',
            'prompt': '충전 전류 입력 범위를 검증해줘.'
        })
        self.assertEqual(status, 200, data)
        return data['proposal']

    def test_00_bootstrap_and_workspace(self):
        code, data = self.api('/api/bootstrap')
        self.assertEqual(code, 200)
        self.assertEqual(data['token'], ax.CSRF)
        code, data = self.api('/api/workspace', {'path':str(ax.DEMO)})
        self.assertEqual(code, 200)
        self.assertTrue(data['configured'])
        self.assertTrue(any(f['path'] == self.target for f in data['files']))
        code, data = self.api('/api/file', {'workspace':str(ax.DEMO),'target':self.target})
        self.assertEqual(code, 200)
        self.assertIn('set_input_current', data['content'])

    def test_01_approval_gate_and_undo(self):
        p = self.new_proposal()
        self.assertEqual(p['status'],'review')
        self.assertGreater(p['plus'], 0)
        self.assertEqual(DEMO_FILE.read_bytes(), self.original, 'proposal must not write files')
        code, applied = self.api('/api/apply', {'id':p['id']})
        self.assertEqual(code,200)
        self.assertEqual(applied['proposal']['status'], 'applied')
        self.assertIn(b'current_ma < 0', DEMO_FILE.read_bytes())
        code, rejected = self.api('/api/apply', {'id':p['id']})
        self.assertEqual(code,409, 'cannot double-apply')
        code, undone = self.api('/api/undo', {'id':p['id']})
        self.assertEqual(code,200)
        self.assertEqual(undone['proposal']['status'],'undone')
        self.assertEqual(DEMO_FILE.read_bytes(), self.original)

    def test_02_reject_leaves_original_untouched(self):
        p = self.new_proposal()
        code, data = self.api('/api/reject', {'id':p['id']})
        self.assertEqual(code,200)
        self.assertEqual(data['proposal']['status'],'rejected')
        self.assertEqual(DEMO_FILE.read_bytes(),self.original)

    def test_03_stale_file_is_never_overwritten(self):
        p = self.new_proposal()
        DEMO_FILE.write_bytes(self.original + b'\n/* changed by human */\n')
        code, data = self.api('/api/apply', {'id':p['id']})
        self.assertEqual(code,409)
        self.assertIn(b'changed by human',DEMO_FILE.read_bytes())

    def test_04_csrf_and_path_traversal(self):
        code, data = self.api('/api/workspace', {'path':str(ax.DEMO)}, token=False)
        self.assertEqual(code,403)
        code, data = self.api('/api/file', {'workspace':str(ax.DEMO),'target':'../../etc/passwd'})
        self.assertEqual(code,400)
        code, data = self.api('/api/bootstrap', host='evil.example.com')
        self.assertEqual(code,403)

    def test_05_fake_ollama_integration(self):
        code, data = self.api('/api/models')
        self.assertEqual(code,200)
        self.assertEqual(data['models'],['fake-kernel:latest'])
        p = self.new_proposal('ollama')
        self.assertEqual(p['engine'],'ollama')
        self.assertIn('generated sample',p['new_content'])
        self.assertEqual(DEMO_FILE.read_bytes(),self.original)

    def test_06_initial_setup_is_required(self):
        ax.CONFIG_FILE.unlink()
        code, data = self.api('/api/workspace', {'path': str(ax.DEMO)})
        self.assertEqual(code, 200)
        self.assertFalse(data['configured'])
        self.assertEqual(data['files'], [])
        self.assertTrue(data['config']['build_command'], 'example prefilled in form')
        code, _ = self.api('/api/file', {'workspace': str(ax.DEMO), 'target': self.target})
        self.assertEqual(code, 409)
        code, _ = self.api('/api/propose', {'workspace': str(ax.DEMO), 'target': self.target,
                                          'prompt': '전류 입력을 검증해줘', 'engine': 'demo'})
        self.assertEqual(code, 409)

    def test_07_profile_save_restricts_paths_and_persists(self):
        current = ax.profile_for(ax.DEMO.resolve())
        config = {key: current[key] for key in ax.PROFILE_FIELDS}
        config['editable_paths'] = 'drivers/power/supply/*.c'
        config['blocked_paths'] = '**/ax_ifpmic_charger.c'
        code, data = self.api('/api/config/save', {'workspace': str(ax.DEMO), 'config': config,
                                                  'expected_revision': current['revision']})
        self.assertEqual(code, 200, data)
        self.assertEqual(data['editable_files'], 0)
        code, _ = self.api('/api/file', {'workspace': str(ax.DEMO), 'target': self.target})
        self.assertEqual(code, 403)
        self.assertFalse(any(f['path'] == self.target for f in self.api(
            '/api/workspace', {'path': str(ax.DEMO)})[1]['files']))
        self.assertEqual(os.stat(ax.CONFIG_FILE).st_mode & 0o777, 0o600)
        self.assertNotIn('profiles.json', str(ax.DEMO))
        saved = ax.profile_for(ax.DEMO.resolve())
        self.assertEqual(saved['editable_paths'], config['editable_paths'])
        self.assertNotEqual(saved['revision'], current['revision'])

    def test_08_changed_profile_invalidates_review_proposal(self):
        proposal = self.new_proposal()
        current = ax.profile_for(ax.DEMO.resolve())
        config = {key: current[key] for key in ax.PROFILE_FIELDS}
        config['build_command'] += ' # new reference command'
        code, data = self.api('/api/config/save', {'workspace': str(ax.DEMO), 'config': config,
                                                  'expected_revision': current['revision']})
        self.assertEqual(code, 200, data)
        code, data = self.api('/api/apply', {'id': proposal['id']})
        self.assertEqual(code, 409)
        self.assertEqual(DEMO_FILE.read_bytes(), self.original)
        code, _ = self.api('/api/config/save', {'workspace': str(ax.DEMO), 'config': config,
                                               'expected_revision': current['revision']})
        self.assertEqual(code, 409, 'stale config editors must not overwrite a newer version')

    def test_09_build_recipe_is_saved_only_never_executed(self):
        marker = Path(self.config_tempdir.name) / 'should-not-exist'
        current = ax.profile_for(ax.DEMO.resolve())
        config = {key: current[key] for key in ax.PROFILE_FIELDS}
        config['build_command'] = f'touch {marker}'
        code, data = self.api('/api/config/save', {'workspace': str(ax.DEMO), 'config': config,
                                                  'expected_revision': current['revision']})
        self.assertEqual(code, 200, data)
        self.assertEqual(ax.profile_for(ax.DEMO.resolve())['build_command'], config['build_command'])
        proposal = self.new_proposal('ollama')
        self.assertEqual(proposal['status'], 'review')
        self.assertFalse(marker.exists(), 'build recipe should never run during proposing')
        self.api('/api/apply', {'id': proposal['id']})
        self.assertFalse(marker.exists(), 'build recipe should never run when applying code')

    def test_10_invalid_build_directory_is_rejected(self):
        current = ax.profile_for(ax.DEMO.resolve())
        config = {key: current[key] for key in ax.PROFILE_FIELDS}
        config['build_dir'] = '../outside'
        code, _ = self.api('/api/config/save', {'workspace': str(ax.DEMO), 'config': config,
                                               'expected_revision': current['revision']})
        self.assertEqual(code, 400)
        config['build_dir'] = '.'
        config['editable_paths'] = '../*'
        code, _ = self.api('/api/config/save', {'workspace': str(ax.DEMO), 'config': config,
                                               'expected_revision': current['revision']})
        self.assertEqual(code, 400)

    def test_11_undo_remains_possible_after_scope_changes(self):
        proposal = self.new_proposal()
        self.assertEqual(self.api('/api/apply', {'id': proposal['id']})[0], 200)
        current = ax.profile_for(ax.DEMO.resolve())
        config = {key: current[key] for key in ax.PROFILE_FIELDS}
        config['editable_paths'] = 'include/linux/power/**'
        self.assertEqual(self.api('/api/config/save', {'workspace': str(ax.DEMO), 'config': config,
                                                     'expected_revision': current['revision']})[0], 200)
        self.assertEqual(self.api('/api/undo', {'id': proposal['id']})[0], 200)
        self.assertEqual(DEMO_FILE.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
