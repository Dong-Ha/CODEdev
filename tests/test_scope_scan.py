"""Scope-first discovery regressions for large source trees."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ax_scope_app', ROOT / 'app.py')
ax = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ax)


class ScopeDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'linux-tree'
        self.root.mkdir()
        self.profile = ax.default_profile(self.root)
        self.profile['editable_paths'] = 'drivers/power/supply/**'
        self.profile['blocked_paths'] = ''

    def make_file(self, relative, contents='int example(void) { return 1; }\n'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding='utf-8')
        return path

    def test_scopes_before_file_budget_in_large_kernel_tree(self):
        # The old algorithm stopped after 1,500 arch files, before drivers/.
        for i in range(1505):
            self.make_file(f'arch/arm64/boot/dts/file_{i:04d}.c')
        target = 'drivers/power/supply/ifpmic.c'
        self.make_file(target)
        with patch.object(ax, 'MAX_FILES', 3):
            scan = ax.scan_workspace(self.root, self.profile)
            self.assertEqual([f['path'] for f in scan['files']], [target])
            self.assertEqual(scan['stats']['scanned_files'], 1)
            self.assertEqual(scan['stats']['editable_files'], 1)
            self.assertFalse(scan['stats']['truncated'])

    def test_deep_nested_allowed_path_beyond_nine_levels(self):
        target = 'drivers/power/supply/supplier/platform/v1/gauge/routines/calibration/legacy/soc/entry.c'
        self.assertGreater(len(Path(target).parts), 9)
        self.make_file(target)
        scan = ax.scan_workspace(self.root, self.profile)
        self.assertEqual([f['path'] for f in scan['files']], [target])
        self.assertFalse(scan['stats']['truncated'])

    def test_overlapping_allowlists_do_not_duplicate_files(self):
        self.make_file('drivers/power/supply/charger.c')
        self.make_file('drivers/power/supply/fuelgauge.c')
        self.profile['editable_paths'] = 'drivers/power/**\ndrivers/power/supply/**'
        scan = ax.scan_workspace(self.root, self.profile)
        self.assertEqual(scan['stats']['searched_roots'], 2)
        self.assertEqual(scan['stats']['scanned_files'], 2)
        self.assertEqual(scan['stats']['editable_files'], 2)
        self.assertEqual(len({f['path'] for f in scan['files']}), 2)

    def test_excluded_and_symlink_paths_are_not_discovered(self):
        self.make_file('drivers/power/supply/charger.c')
        self.make_file('drivers/power/supply/private.c')
        outside = self.make_file('archive/private.c')
        target_dir = self.root / 'drivers/power/supply'
        (target_dir / 'external.c').symlink_to(outside)
        self.profile['blocked_paths'] = 'drivers/power/supply/private.c'
        scan = ax.scan_workspace(self.root, self.profile)
        self.assertEqual([f['path'] for f in scan['files']], ['drivers/power/supply/charger.c'])

    def test_discovery_limit_is_visible_and_blocks_automatic_choice(self):
        for i in range(3):
            self.make_file(f'drivers/power/supply/charger_{i}.c')
        with patch.object(ax, 'MAX_FILES', 1):
            scan = ax.scan_workspace(self.root, self.profile)
            self.assertTrue(scan['stats']['truncated'])
            self.assertEqual(scan['stats']['editable_files'], 1)
            self.assertIn('1개 초과', scan['stats']['limit_reason'])
            with self.assertRaisesRegex(ax.ApiError, '탐색이 제한'):
                ax.select_target(self.root, '충전 전류를 검증해줘', self.profile, {})

    def test_missing_scoped_path_is_reported(self):
        scan = ax.scan_workspace(self.root, self.profile)
        self.assertEqual(scan['files'], [])
        self.assertEqual(scan['stats']['missing_paths'], ['drivers/power/supply/**'])
        self.assertFalse(scan['stats']['truncated'])

    def test_wildcard_pattern_filters_before_matched_file_limit(self):
        for i in range(10):
            self.make_file(f'arch/x/feature_{i}.c')
        target = 'drivers/power/supply/charger.c'
        self.make_file(target)
        self.profile['editable_paths'] = '**/charger.c'
        with patch.object(ax, 'MAX_FILES', 1):
            scan = ax.scan_workspace(self.root, self.profile)
        self.assertEqual([f['path'] for f in scan['files']], [target])
        self.assertEqual(scan['stats']['scanned_files'], 11)
        self.assertFalse(scan['stats']['truncated'])

    def test_directory_scan_budget_reported(self):
        self.make_file('drivers/power/supply/sub1/a.c')
        self.make_file('drivers/power/supply/sub2/b.c')
        with patch.object(ax, 'MAX_SCAN_DIRS', 1):
            scan = ax.scan_workspace(self.root, self.profile)
        self.assertTrue(scan['stats']['truncated'])
        self.assertIn('탐색 폴더', scan['stats']['limit_reason'])

    def test_explicit_file_allowlist_matches_file_itself(self):
        target='drivers/power/supply/charger.c'
        self.make_file(target)
        self.profile['editable_paths'] = target
        scan = ax.scan_workspace(self.root, self.profile)
        self.assertEqual([f['path'] for f in scan['files']], [target])


if __name__ == '__main__':
    unittest.main()
