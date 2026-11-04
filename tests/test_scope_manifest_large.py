"""Regression coverage: path matching is not a file-size gate."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ax_manifest_app", ROOT / "app.py")
ax = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ax)


class ScopeManifestLargeFileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "kernel"
        self.root.mkdir()
        self.scope = "drivers/power/supply"
        (self.root / self.scope).mkdir(parents=True)
        self.config_patch = patch.object(ax, "CONFIG_FILE", Path(self.temp.name) / "cfg.json")
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.profile = ax.default_profile(self.root)
        self.profile["editable_paths"] = self.scope + "/**/*abc*"
        self.profile["blocked_paths"] = ""

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_matching_files_include_64kb_plus_and_unknown_extensions(self):
        self.write(self.scope + "/abc1.c", "int first(void);\n")
        big = self.write(self.scope + "/abc2.c", "/* charger */\n" * 5600)
        self.write(self.scope + "/sub/myabc.rules", "rule := x\n")
        scan = ax.scan_workspace(self.root, self.profile)
        found = {entry["path"]: entry["size"] for entry in scan["files"]}
        self.assertGreater(big.stat().st_size, 64 * 1024)
        self.assertEqual(set(found), {self.scope + "/abc1.c", self.scope + "/abc2.c",
                                       self.scope + "/sub/myabc.rules"})
        self.assertEqual(found[self.scope + "/abc2.c"], big.stat().st_size)
        self.assertFalse(scan["stats"]["truncated"])

    def test_matching_binary_and_over_host_cap_are_still_in_inventory(self):
        self.write(self.scope + "/abc1.c", "int x;\n")
        big = self.root / (self.scope + "/abc2.c")
        with big.open("wb") as f:
            f.truncate(ax.MAX_EDIT_SOURCE_BYTES + 1)
        with (self.root / (self.scope + "/abc3.bin")).open("wb") as f:
            f.write(b"\x00\x01")
        names = {x["path"] for x in ax.scan_workspace(self.root, self.profile)["files"]}
        self.assertEqual(names, {self.scope + "/abc1.c", self.scope + "/abc2.c",
                                 self.scope + "/abc3.bin"})
        with self.assertRaisesRegex(ax.ApiError, "처리 한도"):
            ax.read_utf8(big)
        with self.assertRaisesRegex(ax.ApiError, "바이너리"):
            ax.read_utf8(self.root / (self.scope + "/abc3.bin"))

    def test_explicit_blocked_scope_still_prevents_edits(self):
        self.write(self.scope + "/abc1.c", "int first;\n")
        self.write(self.scope + "/abc2.c", "int second;\n")
        self.profile["blocked_paths"] = self.scope + "/abc2.c"
        files = [x["path"] for x in ax.scan_workspace(self.root, self.profile)["files"]]
        self.assertEqual(files, [self.scope + "/abc1.c"])
        with self.assertRaises(ax.ApiError):
            ax.require_editable(self.root, self.scope + "/abc2.c", self.profile)

    def test_all_manifest_batches_reach_the_model_in_korean_only_request(self):
        # The old implementation discarded filenames after the top-400 rank
        # and skipped Claude entirely for Korean-only prompts.
        for i in range(9):
            self.write(self.scope + f"/abc{i}.c", "int a;\n")
        self.profile["editable_paths"] = self.scope + "/**/*abc*"
        seen = []
        desired = self.scope + "/abc8.c"

        def mocked(task, schema, on_event=None):
            manifest = task.split("Allowlisted relative paths (filenames only; no source contents yet):\n", 1)[1]
            paths = json.loads(manifest.split("\nReturn targets", 1)[0])
            seen.extend(paths)
            return {"targets": [desired] if desired in paths else [],
                    "reason": "검토 완료", "question": ""}

        with patch.object(ax, "MAX_AUTO_TARGET_FILES", 3), patch.object(ax, "run_claude_task", side_effect=mocked):
            result = ax.choose_targets(self.root, "충전 전류를 수정해줘", self.profile, {})
        self.assertEqual(result["targets"], [desired])
        self.assertCountEqual(seen, [self.scope + f"/abc{i}.c" for i in range(9)])

    def test_large_file_patch_proposal_apply_and_undo(self):
        marker = "int abc2_charge_limit(void) { return 100; }"
        original = ("/* header */\n" +
                    "".join("static int filler_%04d = %d;\n" % (i, i) for i in range(5000)) +
                    marker + "\n")
        self.assertGreater(len(original.encode()), 64 * 1024)
        big = self.write(self.scope + "/abc2.c", original)
        self.write(self.scope + "/abc1.c", "int x;\n")
        profile = {k: self.profile[k] for k in ax.PROFILE_FIELDS}
        ax.save_profile(self.root, profile)
        chosen = self.scope + "/abc2.c"
        calls = []
        def mocked(task, schema, on_event=None):
            calls.append((task, schema))
            if "targets" in schema["properties"]:
                return {"targets": [chosen], "reason": "matched", "question": ""}
            self.assertIn("edits", schema["properties"])
            self.assertIn(marker, task)
            return {"summary": "Increase charge limit", "rationale": "requested update",
                    "risk": "review impact", "checks": ["Check battery charging"],
                    "edits": [{"old_string": marker,
                               "new_string": "int abc2_charge_limit(void) { return 200; }"}]}
        events = []
        with patch.object(ax, "run_claude_task", side_effect=mocked):
            proposal = ax.propose({"workspace": str(self.root), "prompt": "abc2 충전 limit 변경해주세요"},
                                  on_event=lambda role,text,stage: events.append((role,text,stage)))
        self.assertEqual(proposal["status"], "review")
        self.assertEqual(proposal["target"], chosen)
        self.assertEqual(big.read_text(), original)
        self.assertEqual(proposal["files"][0]["new_content"].count("return 200"), 1)
        self.assertTrue(any("구간 교체" in text for _,text,_ in events))
        self.assertEqual(len(calls), 2)
        ident = proposal["id"]
        applied = ax.change_status({"id": ident}, "apply")
        self.assertEqual(applied["status"], "applied")
        self.assertIn("return 200", big.read_text())
        undone = ax.change_status({"id": ident}, "undo")
        self.assertEqual(undone["status"], "undone")
        self.assertEqual(big.read_text(), original)

    def test_large_patch_is_exact_unique_and_non_overlapping(self):
        base = "one\nfoo\nbar\nqux\n"
        self.assertEqual(ax.apply_exact_edits(base, [{"old_string": "foo", "new_string": "FOO"}]),
                         "one\nFOO\nbar\nqux\n")
        self.assertEqual(ax.apply_exact_edits(base, []), base)
        with self.assertRaises(ax.ApiError):
            ax.apply_exact_edits(base, [{"old_string": "none", "new_string": "a"}])
        with self.assertRaises(ax.ApiError):
            ax.apply_exact_edits("foo foo", [{"old_string": "foo", "new_string": "bar"}])
        with self.assertRaises(ax.ApiError):
            ax.apply_exact_edits(base, [
                {"old_string": "foo\nbar", "new_string": "x"},
                {"old_string": "bar", "new_string": "y"},
            ])


if __name__ == "__main__":
    unittest.main()
