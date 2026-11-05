"""Direct prompt transport through a real subprocess and HTTP, with a fake CLI."""
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

import test_request_intake as intake_tests
from cli_dispatch import ClaudeDispatch

ax = intake_tests.ax


class ClaudeDispatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        intake_tests.RequestIntakeTest.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        intake_tests.RequestIntakeTest.tearDownClass.__func__(cls)

    def setUp(self):
        intake_tests.RequestIntakeTest.setUp(self)
        self.binary = self.root.parent / "claude"
        fixture = Path(__file__).parent / "fixtures" / "claude_prompt_stub.py"
        self.binary.write_text(f"#!{sys.executable} -S\n" + fixture.read_text(), encoding="utf-8")
        self.binary.chmod(0o700)
        self.log = self.root.parent / "cli.jsonl"
        self.patch = patch.object(ax.shutil, "which", return_value=str(self.binary))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.env = patch.dict(os.environ, {"AX_PROMPT_TEST_MODE": "success", "AX_PROMPT_TEST_LOG": str(self.log)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.assertFalse(ax.CLI_DISPATCH.active)

    api = intake_tests.RequestIntakeTest.api
    create = intake_tests.RequestIntakeTest.create

    def dispatch(self, task, key="send-1", route="/api/requests/dispatch", **kwargs):
        return self.api(route, {"id": task["id"], "idempotency_key": key}, **kwargs)

    def complete(self, task):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = self.api("/api/requests/" + task["id"])[1]["task"]
            if data["status"] not in {"cli_queued", "cli_running"} and not ax.CLI_DISPATCH.active:
                return data
            time.sleep(0.03)
        self.fail("CLI request did not terminate")

    def test_dispatch_plain_prompt_and_persist_response(self):
        task = self.create(instruction="음수 입력을 검증해줘. $(touch SHOULD_NOT_RUN)")
        preview = self.api("/api/requests/" + task["id"])[1]["task"]["cli_prompt"]
        status, data = self.dispatch(task)
        self.assertEqual(status, 202, data)
        done = self.complete(task)
        self.assertEqual(done["status"], "cli_complete")
        run = done["cli_runs"][-1]
        self.assertIn("음수 입력", run["response"])
        actual = json.loads(self.log.read_text().splitlines()[0])
        self.assertEqual(actual["prompt"], preview)
        self.assertEqual(run["prompt"], preview)
        for text in ("WSL Ubuntu 24.04", "Android 16", "Clang test version", "make all", "driver.c", "blocked.c", "SDD-014"):
            self.assertIn(text, actual["prompt"])
        self.assertNotIn("int current", actual["prompt"])
        self.assertNotIn("--json-schema", actual["args"])
        self.assertNotIn("--system-prompt-file", actual["args"])
        self.assertEqual(actual["args"][actual["args"].index("--tools") + 1], "")
        self.assertIn("mcp__*", actual["args"])
        self.assertNotEqual(actual["cwd"], str(self.root))
        self.assertFalse((self.root / "SHOULD_NOT_RUN").exists())
        self.assertEqual((self.root / "driver.c").read_text(), "int current;\n")
        self.assertEqual(ax.INTAKE.get(task["id"])["cli_runs"][-1]["response"], run["response"])
        self.assertNotIn("PRIVATE_THINKING", json.dumps(run))

    def test_concurrent_duplicate_dispatch_starts_only_once(self):
        os.environ["AX_PROMPT_TEST_MODE"] = "delay"
        task = self.create()
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.dispatch(task))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(all(code == 202 for code, _ in results), results)
        done = self.complete(task)
        self.assertEqual(len(done["cli_runs"]), 1)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        self.assertEqual(self.dispatch(task)[0], 202)  # Completed retry is not rerun.
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_project_concurrency_and_explicit_retry(self):
        os.environ["AX_PROMPT_TEST_MODE"] = "delay"
        first, second = self.create(), self.create()
        self.assertEqual(self.dispatch(first)[0], 202)
        self.assertEqual(self.dispatch(second)[0], 409)
        self.assertEqual(self.dispatch(first, key="different")[0], 409)
        self.complete(first)
        self.assertEqual(self.dispatch(first, key="explicit-retry")[0], 202)
        self.assertEqual(len(self.complete(first)["cli_runs"]), 2)

    def test_authentication_boundaries(self):
        task = self.create()
        self.assertEqual(self.dispatch(task, csrf=False)[0], 403)
        self.assertEqual(self.dispatch(task, origin="https://evil.invalid")[0], 403)
        self.assertEqual(self.dispatch(task, route="/api/agent/requests/dispatch")[0], 403)
        self.assertEqual(self.dispatch(task, route="/api/agent/requests/dispatch", agent=ax.AGENT_TOKEN, csrf=False)[0], 202)
        self.assertEqual(self.complete(task)["status"], "cli_complete")

    def test_missing_cli_does_not_create_attempt(self):
        task = self.create()
        with patch.object(ax.shutil, "which", return_value=None):
            self.assertEqual(self.dispatch(task)[0], 503)
        self.assertEqual(ax.INTAKE.get(task["id"])["cli_runs"], [])

    def test_changed_profile_or_manifest_blocks_delivery(self):
        task = self.create()
        (self.root / "new.c").write_text("int other;")
        self.assertEqual(self.dispatch(task)[0], 409)
        (self.root / "new.c").unlink()
        new_profile = {key: self.profile[key] for key in ax.PROFILE_FIELDS}
        new_profile["build_command"] = "make changed"
        ax.save_profile(self.root, new_profile, self.profile["revision"])
        self.assertEqual(self.dispatch(task)[0], 409)
        self.assertFalse(self.log.exists())

    def test_errors_are_visible_and_private_streams_are_not(self):
        for mode in ("exit_error", "result_error", "malformed", "empty", "oversized"):
            with self.subTest(mode=mode):
                os.environ["AX_PROMPT_TEST_MODE"] = mode
                task = self.create()
                self.assertEqual(self.dispatch(task)[0], 202)
                done = self.complete(task)
                self.assertEqual(done["status"], "cli_failed")
                self.assertTrue(done["cli_runs"][-1]["error"])
                self.assertNotIn("PRIVATE_STDERR", json.dumps(done))
                self.assertNotIn("PRIVATE_THINKING", json.dumps(done))

    def test_timeout_is_recorded_and_does_not_leak_process(self):
        os.environ["AX_PROMPT_TEST_MODE"] = "silent"
        task = self.create()
        with patch.object(ax, "CLAUDE_IDLE_TIMEOUT_SECONDS", 0.2):
            self.assertEqual(self.dispatch(task)[0], 202)
            done = self.complete(task)
        self.assertEqual(done["status"], "cli_failed")
        self.assertIn("response stopped", done["cli_runs"][-1]["error"])
        self.assertFalse(ax.CLI_DISPATCH.active)

    def test_large_stdin_cannot_block_startup_watchdog(self):
        os.environ["AX_PROMPT_TEST_MODE"] = "no_stdin"
        start = time.monotonic()
        with patch.object(ax, "CLAUDE_STARTUP_TIMEOUT_SECONDS", 0.2):
            with self.assertRaises(ax.ApiError) as caught:
                ax.run_claude_task("x" * 500000, None)
        self.assertEqual(caught.exception.status, 504)
        self.assertLess(time.monotonic() - start, 2)

    def test_restart_marks_uncertain_run_without_auto_resending(self):
        task = self.create()
        with patch("cli_dispatch.threading.Thread.start"):
            ax.CLI_DISPATCH.start({"id": task["id"], "idempotency_key": "send-1"})
        ax.CLI_DISPATCH.active.clear()
        ClaudeDispatch(vars(ax)).recover_interrupted()
        saved = ax.INTAKE.get(task["id"])
        self.assertEqual(saved["status"], "cli_interrupted")
        self.assertFalse(self.log.exists())
        self.assertEqual(self.dispatch(task)[0], 202)
        self.assertFalse(self.log.exists())  # Same key preserves uncertain result.

    def test_storage_failure_prevents_launch(self):
        task = self.create()
        with patch.object(ax.INTAKE, "write", side_effect=OSError("disk full")):
            self.assertEqual(self.dispatch(task)[0], 500)
        self.assertFalse(self.log.exists())
        self.assertFalse(ax.CLI_DISPATCH.active)

    def test_prompt_limit_preserves_request_detail_access(self):
        task = self.create()
        with patch.object(ax.CLI_DISPATCH, "MAX_PROMPT_BYTES", 10):
            status, data = self.api("/api/requests/" + task["id"])
            self.assertEqual(status, 200)
            self.assertTrue(data["task"]["cli_prompt_error"])
            self.assertEqual(self.dispatch(task)[0], 413)
        self.assertFalse(self.log.exists())

    def test_invalid_key_and_attempt_limit(self):
        task = self.create()
        for key in ("", [], "x" * 161):
            self.assertEqual(self.dispatch(task, key=key)[0], 400)
        with patch.object(ax.CLI_DISPATCH, "MAX_ATTEMPTS", 0):
            self.assertEqual(self.dispatch(task)[0], 429)


if __name__ == "__main__":
    unittest.main()
