"""Real HTTP coverage for the default, execution-free request workflow."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from request_intake import RequestIntake

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ax_intake_test_app", ROOT / "app.py")
ax = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ax)


class RequestIntakeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ax.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project"
        self.root.mkdir()
        (self.root / "driver.c").write_text("int current;\n")
        (self.root / "blocked.c").write_text("int excluded;\n")
        self.config_path = Path(temp.name) / "config" / "profiles.json"
        ax.CONFIG_FILE = self.config_path
        ax.ENABLE_LEGACY_CLAUDE = False
        ax.AGENT_TOKEN = "intake-test-token"
        env = patch.dict("os.environ", {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        # Tests must never use a developer's explicit store override.
        import os
        os.environ.pop("AX_REQUESTS_FILE", None)
        profile = ax.default_profile(self.root)
        profile.update(build_command="make all", editable_paths="*.c", blocked_paths="blocked.c",
                       development_environment="WSL Ubuntu 24.04", target_environment="Android 16 arm64",
                       toolchain="Clang test version")
        self.profile = ax.save_profile(self.root, profile)
        self.body = {"workspace": str(self.root), "instruction": "Reject negative charging current.",
                     "source_kind": "sdd", "source_ref": "SDD-014", "source_content": "Keep normal behavior.",
                     "expected_revision": self.profile["revision"]}

    def api(self, route, body=None, agent=None, csrf=True, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-AX-Token"] = ax.CSRF
        if agent is not None:
            headers["X-AX-Agent-Token"] = agent
        if origin:
            headers["Origin"] = origin
        connection.request("POST" if body is not None else "GET", route,
                           body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw) if route.startswith("/api/") else raw

    def create(self, **updates):
        body = dict(self.body, **updates)
        status, data = self.api("/api/requests", body)
        self.assertEqual(status, 202, data)
        return data["task"]

    def test_bootstrap_and_default_gui_do_not_require_claude(self):
        status, data = self.api("/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertFalse(data["code_dev_agent"]["implemented"])
        self.assertFalse(data["legacy_claude_enabled"])
        status, html = self.api("/")
        self.assertEqual(status, 200)
        self.assertIn(b"/intake.js", html)
        self.assertEqual(self.api("/legacy")[0], 404)

    def test_snapshot_is_durable_and_execution_free(self):
        with patch.object(ax, "run_claude_task", side_effect=AssertionError("No model")), \
             patch.object(ax, "atomic_write", side_effect=AssertionError("No source writes")), \
             patch.object(ax, "start_job", side_effect=AssertionError("No worker")):
            task = self.create()
        payload = task["payload"]
        self.assertEqual(task["status"], "waiting_for_agent")
        self.assertFalse(task["agent_available"])
        self.assertEqual(payload["schema_version"], "ax.code-dev.request.v1")
        self.assertEqual(payload["recipient"], "code-dev")
        self.assertEqual(payload["environment"]["development_environment"], "WSL Ubuntu 24.04")
        self.assertEqual([file["path"] for file in payload["scope"]["editable_files"]], ["driver.c"])
        self.assertEqual(payload["request"]["source_content"], "Keep normal behavior.")
        self.assertFalse(payload["execution"]["build_executed"])
        self.assertEqual((self.root / "driver.c").read_text(), "int current;\n")
        # Recreate the service to simulate losing all in-memory state.
        service = RequestIntake(vars(ax))
        self.assertEqual(service.get(task["id"])["payload"], payload)
        self.assertEqual(service.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("payload", service.list()[0])
        self.assertEqual(len(service.list()), 1)

    def test_all_source_kinds_share_contract(self):
        for kind in sorted(ax.SOURCE_KINDS):
            self.assertEqual(self.create(source_kind=kind)["payload"]["request"]["source_kind"], kind)

    def test_agent_intake_provenance_and_authentication(self):
        body = dict(self.body, source_agent="SW Design", upstream_run_id="run-14")
        body.pop("expected_revision")
        for token in (None, "wrong"):
            self.assertEqual(self.api("/api/agent/requests", body, agent=token)[0], 403)
        status, data = self.api("/api/agent/requests", body, agent=ax.AGENT_TOKEN, csrf=False)
        self.assertEqual(status, 202, data)
        task = data["task"]
        self.assertEqual((task["origin"], task["source_agent"], task["upstream_run_id"]), ("agent", "SW Design", "run-14"))
        path = "/api/agent/requests/" + task["id"]
        self.assertEqual(self.api(path)[0], 403)
        self.assertEqual(self.api(path, agent=ax.AGENT_TOKEN)[1]["task"]["payload"], task["payload"])
        self.assertEqual(self.api("/api/agent/requests", agent=ax.AGENT_TOKEN)[0], 200)
        ax.AGENT_TOKEN = ""
        self.assertEqual(self.api(path, agent="")[0], 403)

    def test_compatibility_alias_queues_without_execution(self):
        body = dict(self.body, source_agent="SQE", auto_generate=False)
        status, data = self.api("/api/agent/handoffs", body, agent=ax.AGENT_TOKEN)
        self.assertEqual(status, 202, data)
        self.assertEqual(data["task"]["status"], "waiting_for_agent")
        self.assertEqual(self.api("/api/agent/handoffs/"+data["task"]["id"], agent=ax.AGENT_TOKEN)[0], 200)
        self.assertEqual(self.api("/api/agent/handoffs", dict(body, auto_generate=True), agent=ax.AGENT_TOKEN)[0], 409)
        self.assertEqual(len(ax.INTAKE.list()), 1)

    def test_csrf_cross_origin_and_impersonation(self):
        self.assertEqual(self.api("/api/requests", self.body, csrf=False)[0], 403)
        self.assertEqual(self.api("/api/requests", self.body, origin="https://evil.invalid")[0], 403)
        task = self.create(source_agent="Forged", upstream_run_id="spoofed")
        self.assertEqual(task["source_agent"], "")
        self.assertEqual(task["upstream_run_id"], "")
        self.assertEqual(task["origin"], "human")

    def test_retry_idempotency_and_conflict(self):
        first = self.create(idempotency_key="retry-1")
        second = self.create(idempotency_key="retry-1")
        self.assertEqual(first["id"], second["id"])
        status, _ = self.api("/api/requests", dict(self.body, idempotency_key="retry-1", instruction="A different task"))
        self.assertEqual(status, 409)
        self.assertEqual(len(ax.INTAKE.list()), 1)

    def test_concurrent_retries_create_one_record(self):
        results = []
        def submit():
            results.append(self.api("/api/requests", dict(self.body, idempotency_key="parallel")))
        threads = [threading.Thread(target=submit) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(all(status == 202 for status, _ in results))
        self.assertEqual(len({data["task"]["id"] for _, data in results}), 1)
        self.assertEqual(len(ax.INTAKE.list()), 1)

    def test_environment_change_preserves_snapshot_but_blocks_agent_consumption(self):
        task = self.create()
        updated = {key: self.profile[key] for key in ax.PROFILE_FIELDS}
        updated["build_command"] = "make changed"
        ax.save_profile(self.root, updated, self.profile["revision"])
        status, data = self.api("/api/requests/" + task["id"])
        self.assertEqual(status, 200)
        self.assertTrue(data["task"]["configuration_stale"])
        self.assertEqual(data["task"]["payload"]["environment"]["build_command"], "make all")
        self.assertEqual(self.api("/api/agent/requests/" + task["id"], agent=ax.AGENT_TOKEN)[0], 409)
        self.assertEqual(self.api("/api/requests", self.body)[0], 409)

    def test_invalid_payloads_are_not_saved(self):
        for update in ({"instruction": ""}, {"source_kind": "unknown"}, {"instruction": "a\x00long"},
                       {"expected_revision": "old"}, {"target": "../secret"}, {"target": "blocked.c"},
                       {"target": ["driver.c"]}, {"auto_generate": True}, {"execute": True},
                       {"idempotency_key": ["bad"]}, {"source_content": "x"*12001}):
            with self.subTest(update=update):
                status, _ = self.api("/api/requests", dict(self.body, **update))
                self.assertIn(status, {400, 403, 409})
        self.assertEqual(ax.INTAKE.list(), [])

    def test_exact_file_scope_and_missing_profile(self):
        self.assertEqual(self.create(target="driver.c")["target"], "driver.c")
        self.config_path.unlink()
        self.assertEqual(self.api("/api/requests", self.body)[0], 409)

    def test_incomplete_or_empty_scope_rejects_intake(self):
        with patch.object(ax, "MAX_FILES", 0):
            self.assertEqual(self.api("/api/requests", self.body)[0], 409)
        (self.root / "driver.c").unlink()
        self.assertEqual(self.api("/api/requests", self.body)[0], 409)
        self.assertEqual(ax.INTAKE.list(), [])

    def test_legacy_execution_endpoints_are_disabled(self):
        for route in ("/api/propose", "/api/jobs", "/api/jobs/handoff", "/api/handoff/generate",
                      "/api/apply", "/api/reject", "/api/undo"):
            self.assertEqual(self.api(route, self.body)[0], 409, route)

    def test_store_capacity_and_failure_do_not_succeed(self):
        with patch.object(ax.INTAKE, "MAX_RECORDS", 0):
            self.assertEqual(self.api("/api/requests", self.body)[0], 429)
        with patch.object(ax.INTAKE, "write", side_effect=OSError("disk unavailable")):
            self.assertEqual(self.api("/api/requests", self.body)[0], 500)
        self.assertEqual(ax.INTAKE.list(), [])

    def test_corrupt_store_and_symlink_fail_closed(self):
        ax.INTAKE.path.parent.mkdir(exist_ok=True)
        ax.INTAKE.path.write_text("{broken")
        self.assertEqual(self.api("/api/requests")[0], 409)
        ax.INTAKE.path.unlink()
        ax.INTAKE.path.symlink_to(self.root / "driver.c")
        self.assertEqual(self.api("/api/requests", self.body)[0], 409)
        self.assertEqual((self.root / "driver.c").read_text(), "int current;\n")

    def test_unknown_request_returns_404(self):
        self.assertEqual(self.api("/api/requests/missing")[0], 404)


if __name__ == "__main__":
    unittest.main()
