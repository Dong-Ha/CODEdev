"""Portable installation and archive checks, without a Claude account or model."""
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "agents" / "code-dev-standalone"


def load(name):
    spec = importlib.util.spec_from_file_location(name, BUNDLE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load("install")
builder = load("build_zip")


class StandaloneBundleTests(unittest.TestCase):
    def test_archive_can_be_extracted_and_installed_without_repo_or_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = builder.build(root / "bundle.zip")
            with ZipFile(archive) as bundle:
                self.assertIsNone(bundle.testzip())
                self.assertEqual(len(bundle.namelist()), 10)
                bundle.extractall(root / "extract")
            extracted = root / "extract" / "code-dev-standalone"
            project = root / "프로젝트 with spaces"
            project.mkdir()
            command = [sys.executable, str(extracted / "install.py"), "--project", str(project)]
            subprocess.run(command + ["--check"], check=True, capture_output=True)
            self.assertFalse((project / ".claude").exists())
            subprocess.run(command, check=True, capture_output=True)
            for name in installer.NAMES:
                self.assertEqual((project / ".claude/agents" / f"{name}.md").read_bytes(),
                                 (BUNDLE / ".claude/agents" / f"{name}.md").read_bytes())
            self.assertEqual((project / ".claude/agents/ax-code-dev-LICENSE.txt").read_bytes(),
                             (BUNDLE / "LICENSE").read_bytes())
            self.assertEqual(installer.install(project), [])

    def test_conflict_is_preflighted_before_any_agent_is_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / ".claude/agents"
            target.mkdir(parents=True)
            conflict = target / "ax-code-reviewer.md"
            conflict.write_text("existing user configuration")
            with self.assertRaisesRegex(ValueError, "Existing file differs"):
                installer.install(project)
            self.assertEqual(list(target.iterdir()), [conflict])
            self.assertEqual(conflict.read_text(), "existing user configuration")

    def test_symlink_configuration_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            outside = Path(directory) / "outside"
            project.mkdir()
            outside.mkdir()
            try:
                (project / ".claude").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable")
            with self.assertRaises(ValueError):
                installer.install(project)
            self.assertEqual(list(outside.iterdir()), [])

    def test_zip_is_reproducible_and_matches_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            first = builder.build(Path(directory) / "first.zip")
            second = builder.build(Path(directory) / "second.zip")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with ZipFile(first) as archive:
                for relative in builder.FILES:
                    self.assertEqual(archive.read("code-dev-standalone/" + relative),
                                     (BUNDLE / relative).read_bytes())
            self.assertEqual(first.read_bytes(),
                             (REPO / "downloads/code-dev-standalone.zip").read_bytes())

    def test_local_delegate_names_resolve_and_wiki_precedes_code(self):
        agents = BUNDLE / ".claude/agents"
        main = (agents / "ax-code-dev.md").read_text()
        self.assertNotIn("feature-dev:", main)
        declared = set(re.findall(r"ax-(?:wiki-explorer|code-explorer|code-architect|code-reviewer)",
                                  main.split("---", 2)[1]))
        self.assertEqual(declared, set(installer.NAMES) - {"ax-code-dev"})
        for name in declared:
            text = (agents / f"{name}.md").read_text()
            self.assertIn(f"name: {name}\n", text)
            self.assertIn("tools: Read, Grep, Glob\n", text)
        phases = re.findall(r"^## (\d+)\. ([^—]+)", main, re.M)
        self.assertEqual([n for n, _ in phases], list("12345678"))
        self.assertIn("Wiki Exploration", phases[1][1])
        self.assertIn("Codebase Exploration", phases[2][1])
        for field in ("environment.wiki_link", "wiki_context", "not_configured",
                      "scope.editable_files", "task.payload", "W ID"):
            self.assertIn(field, main)


if __name__ == "__main__":
    unittest.main()
