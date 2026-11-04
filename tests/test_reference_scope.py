"""Read reference sources across Project Root without widening edit permissions."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ax_readscope_app', ROOT / 'app.py')
ax = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ax)


class ReferenceScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'kernel'
        self.root.mkdir()
        self.driver = 'drivers/power/supply/charger.c'
        self.source = '#include <linux/power_supply.h>\nint charger_power_supply_mode(void) { return 1; }\n'
        self.write(self.driver, self.source)
        self.header = 'include/linux/power_supply.h'
        self.header_text = 'struct power_supply { int charger_power_supply_mode; };\n'
        self.write(self.header, self.header_text)
        self.profile = ax.default_profile(self.root)
        self.profile['editable_paths'] = 'drivers/power/supply/**'
        self.profile['blocked_paths'] = '**/*.key\n**/.env\n**/secrets/**'
        self.profile['revision'] = 'fixture'

    def write(self, path, data):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(data, encoding='utf-8')
        return file

    def test_reference_outside_edit_scope_is_read_only(self):
        references = ax.discover_readonly_references(self.root, {self.driver: self.source}, 'Improve charger')
        self.assertIn(self.header, references)
        self.assertIn('struct power_supply', references[self.header])
        self.assertFalse(ax.editable(self.profile, self.header))
        self.assertTrue(ax.editable(self.profile, self.driver))
        self.assertEqual((self.root / self.header).read_text(), self.header_text)

    def test_modified_proposal_receives_noneditable_header_context(self):
        captured = []
        revised = self.source + '\n/* validated */\n'
        def fake_claude(task, schema, on_event=None):
            captured.append(task)
            return {'summary':'ok', 'rationale':'uses header', 'risk':'review',
                    'checks':['inspect'], 'new_content':revised}
        with patch.object(ax, 'require_profile', return_value=self.profile), \
             patch.object(ax, 'run_claude_task', side_effect=fake_claude):
            p = ax.propose({'workspace':str(self.root), 'prompt':'Improve charger power-supply handling'})
        self.assertEqual(p['status'], 'review')
        self.assertEqual(p['files'][0]['path'], self.driver)
        self.assertIn('Reference source: '+self.header, captured[-1])
        self.assertIn('struct power_supply', captured[-1])
        self.assertIn('Reference context START', captured[-1])
        self.assertEqual((self.root / self.header).read_text(), self.header_text)
        self.assertEqual((self.root / self.driver).read_text(), self.source)

    def test_untrusted_symlink_and_sensitive_reference_skipped(self):
        outside = Path(self.tmp.name) / 'outside.h'
        outside.write_text('int charger_power_supply_secret = 1;\n')
        alias = self.root / 'include/linux/alias.h'
        alias.symlink_to(outside)
        self.write('secrets/charger_password.c','int charger_power_supply_secret = 1;\n')
        self.write('include/linux/.env','secret=123456\n')
        references = ax.discover_readonly_references(self.root, {self.driver:self.source}, 'charger power supply')
        self.assertNotIn('include/linux/alias.h', references)
        self.assertNotIn('secrets/charger_password.c', references)
        self.assertNotIn('include/linux/.env', references)
        self.assertNotIn('charger_power_supply_secret', str(references))

    def test_other_driver_symbol_reference_outside_editable(self):
        other = 'drivers/usb/typec/typec_reference.c'
        self.write(other,'int charger_power_supply_mode(void) { return 2; }\n')
        references = ax.discover_readonly_references(self.root, {self.driver:self.source}, 'charger power_supply_mode')
        self.assertIn(other, references)
        self.assertFalse(ax.editable(self.profile, other))

    def test_reading_noneditable_does_not_allow_writing(self):
        self.assertFalse(ax.editable(self.profile, self.header))
        with patch.object(ax, 'require_profile', return_value=self.profile):
            with self.assertRaises(ax.ApiError):
                ax.require_editable(self.root, self.header)


if __name__ == '__main__':
    unittest.main()
