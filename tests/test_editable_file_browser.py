"""Regression coverage for the editable-file manifest shown in both GUI views."""

import importlib.util
import json
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, build_opener, ProxyHandler
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ax_editable_browser_app", ROOT / "app.py")
ax = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ax)
HTTP = build_opener(ProxyHandler({}))


class ElementIndex(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.elements[attributes["id"]] = (tag, attributes)


class EditableFileBrowserTest(unittest.TestCase):
    def test_both_views_contain_searchable_file_manifest(self):
        markup = (ROOT / "web/index.html").read_text(encoding="utf-8")
        document = ElementIndex()
        document.feed(markup)
        self.assertNotIn("targetFile", document.elements)
        for prefix in ("code", "env"):
            self.assertEqual(document.elements[prefix + "EditablePanel"][0], "details")
            self.assertEqual(document.elements[prefix + "EditableSearch"][0], "input")
            self.assertEqual(document.elements[prefix + "EditableList"][0], "ul")
            self.assertEqual(document.elements[prefix + "EditableMore"][0], "button")
            self.assertEqual(document.elements[prefix + "EditableTotal"][0], "span")
            self.assertIn("aria-label", document.elements[prefix + "EditableList"][1])

    def test_workspace_api_includes_allowed_file_paths_and_sizes(self):
        # This is the existing HTTP contract the GUI uses; no new read endpoint
        # or broader filesystem permissions are needed for file-list display.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "linux"
            allowed = root / "drivers/power/supply"
            allowed.mkdir(parents=True)
            (allowed / "charger.c").write_text("int charger(void);\n", encoding="utf-8")
            (allowed / "fuelgauge.c").write_text("int gauge(void);\n", encoding="utf-8")
            (allowed / "secret.c").write_text("int blocked(void);\n", encoding="utf-8")
            (root / "arch").mkdir()
            (root / "arch" / "uneditable.c").write_text("int forbidden(void);\n")
            ax.CONFIG_FILE = Path(temp) / "profiles.json"
            profile = ax.default_profile(root)
            profile["build_command"] = "make Image"
            profile["editable_paths"] = "drivers/power/supply/**"
            profile["blocked_paths"] = "drivers/power/supply/secret.c"
            ax.save_profile(root, profile)
            server = ThreadingHTTPServer(("127.0.0.1", 0), ax.Handler)
            ax.PORT = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                payload = json.dumps({"path": str(root)}).encode()
                req = Request(
                    f"http://127.0.0.1:{ax.PORT}/api/workspace",
                    data=payload,
                    headers={"Content-Type": "application/json", "X-AX-Token": ax.CSRF},
                )
                with HTTP.open(req, timeout=10) as response:
                    self.assertEqual(response.status, 200)
                    result = json.load(response)
                self.assertTrue(result["ok"])
                self.assertTrue(result["configured"])
                self.assertEqual(result["scan"]["editable_files"], 2)
                self.assertEqual(
                    {item["path"] for item in result["files"]},
                    {"drivers/power/supply/charger.c", "drivers/power/supply/fuelgauge.c"},
                )
                self.assertTrue(all(item["size"] > 0 for item in result["files"]))
            finally:
                server.shutdown()
                server.server_close()

    def test_incomplete_manifest_is_identifiable_by_scan_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "linux"
            folder = root / "drivers/power/supply"
            folder.mkdir(parents=True)
            for i in range(4):
                (folder / f"charger{i}.c").write_text("int x;\n")
            profile = ax.default_profile(root)
            profile["editable_paths"] = "drivers/power/supply/**"
            profile["blocked_paths"] = ""
            with patch.object(ax, "MAX_FILES", 2):
                scan = ax.scan_workspace(root, profile)
            self.assertTrue(scan["stats"]["truncated"])
            self.assertEqual(scan["stats"]["editable_files"], 2)
            self.assertTrue(scan["stats"]["limit_reason"])


if __name__ == "__main__":
    unittest.main()
