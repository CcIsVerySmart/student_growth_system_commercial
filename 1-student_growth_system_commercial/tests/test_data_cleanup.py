"""Synthetic temporary data only; no production configuration or data is imported."""
import ast
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = types.ModuleType('cleanup_test_package.config')
        for name in ('STUDENTS_DB', 'COMPANIES_DB', 'POLICY_DB', 'QUERY_CACHE_DB', 'IMPORTED_FILES_DB'):
            setattr(config, name, self.root / 'data' / (name + '.json'))
        config.UPLOAD_DIR = self.root / 'data/uploads'
        config.CACHE_DIR = self.root / 'data/cache'
        config.DEFAULT_POLICY_SUMMARY = {'rule': 'default'}
        package = types.ModuleType('cleanup_test_package')
        package.__path__ = []
        self.modules = patch.dict(sys.modules, {
            'cleanup_test_package': package, 'cleanup_test_package.config': config,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location('cleanup_test_package.storage', ROOT / 'student_growth_system/storage.py')
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        self.config = config
        self.originals = []
        for kind in ('students', 'companies', 'policy'):
            upload = types.SimpleNamespace(name='synthetic.txt', getvalue=lambda: b'synthetic only')
            self.originals.append(Path(self.s.save_uploaded_file(upload, kind, kind)))
        self.s.save_students([{'name': 'synthetic', 'source_id': 'students'}])
        self.s.save_companies([{'name': 'synthetic'}])
        self.s.save_policy({'rule': 'synthetic'})
        self.s.save_cache({'synthetic': 'derived'})
        self.s.save_imported_files([{'source_id': 'students', 'saved_path': str(self.originals[0])}])

    def test_full_clear_removes_orphans_nested_hidden_and_cache(self):
        orphan = self.config.UPLOAD_DIR / 'nested/.orphan'
        orphan.parent.mkdir()
        orphan.write_text('synthetic')
        self.config.CACHE_DIR.mkdir()
        (self.config.CACHE_DIR / 'derived.bin').write_bytes(b'synthetic')
        keep = self.root / 'assets/forms/template.txt'
        keep.parent.mkdir(parents=True)
        keep.write_text('template')
        env = self.root / '.env'
        env.write_text('SYNTHETIC_CONFIG=1')
        result = self.s.clear_all_data()
        self.assertTrue(result['cleared'], result)
        self.assertEqual(result['removed_files'], 5)
        self.assertEqual(self.s.load_students(), [])
        self.assertEqual(self.s.load_companies(), [])
        self.assertEqual(self.s.load_policy(), self.config.DEFAULT_POLICY_SUMMARY)
        self.assertEqual(self.s.load_cache(), {})
        self.assertEqual(self.s.load_imported_files(), [])
        for directory in (self.config.UPLOAD_DIR, self.config.CACHE_DIR):
            self.assertTrue(directory.is_dir())
            self.assertFalse(any(p.is_file() or p.is_symlink() for p in directory.rglob('*')))
        self.assertTrue(orphan.parent.is_dir())
        self.assertEqual(keep.read_text(), 'template')
        self.assertEqual(env.read_text(), 'SYNTHETIC_CONFIG=1')
        self.assertTrue(self.s.clear_all_data()['cleared'])

    def test_missing_directories_are_recreated(self):
        import shutil
        shutil.rmtree(self.config.UPLOAD_DIR)
        self.assertTrue(self.s.clear_all_data()['cleared'])
        self.assertTrue(self.config.UPLOAD_DIR.is_dir())
        self.assertTrue(self.config.CACHE_DIR.is_dir())

    def test_symlinks_do_not_delete_external_targets(self):
        outside = self.root / 'outside'
        outside.mkdir()
        sentinel = outside / 'keep.txt'
        sentinel.write_text('keep')
        (self.config.UPLOAD_DIR / 'linked_dir').symlink_to(outside, target_is_directory=True)
        (self.config.UPLOAD_DIR / 'linked_file').symlink_to(sentinel)
        self.assertTrue(self.s.clear_all_data()['cleared'])
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_symlink_root_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.root / 'linked_uploads'
        link.symlink_to(outside, target_is_directory=True)
        self.s.UPLOAD_DIR = link
        self.assertFalse(self.s.clear_all_data()['cleared'])
        self.assertTrue(self.s.load_imported_files())

    def test_delete_failure_reports_partial_progress_and_keeps_provenance(self):
        original = Path.unlink
        def failing(path, *args, **kwargs):
            if path == self.originals[0]:
                raise PermissionError('synthetic permission failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', failing):
            result = self.s.clear_all_data()
        self.assertFalse(result['cleared'])
        self.assertTrue(result['errors'])
        self.assertTrue(self.originals[0].exists())
        self.assertTrue(self.s.load_imported_files())
        self.assertTrue(self.s.clear_all_data()['cleared'])

    def test_json_write_failure_is_not_success(self):
        with patch.object(self.s, 'save_json', side_effect=OSError('synthetic disk full')):
            result = self.s.clear_all_data()
        self.assertFalse(result['cleared'])
        self.assertTrue(self.s.load_imported_files())
        self.assertTrue(self.s.clear_all_data()['cleared'])


class SettingsConfirmationTests(unittest.TestCase):
    def run_settings(self, acknowledged, text, submitted=True):
        class State(dict):
            pass
        class UI:
            session_state = State(admin_ok=True, draft_profile={'synthetic': 1}, last_result={'synthetic': 1}, chat_messages=['synthetic'])
            def __getattr__(self, name):
                return lambda *args, **kwargs: None
            def button(self, *args, **kwargs): return False
            def checkbox(self, *args): return acknowledged
            def text_input(self, *args): return text
            def form_submit_button(self, *args, **kwargs): return submitted
            def form(self, *args): return self
            def __enter__(self): return self
            def __exit__(self, *args): pass
        ui = UI()
        ui.cache_data = types.SimpleNamespace(clear=lambda: None)
        calls = []
        node = next(n for n in ast.parse((ROOT / 'app.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'page_settings')
        namespace = dict(st=ui, hero=lambda *a: None, admin_login=lambda: True,
                         card_start=lambda *a: None, card_end=lambda: None,
                         SiliconFlowClient=lambda: types.SimpleNamespace(model='test', available=False),
                         save_cache=lambda _: None,
                         clear_all_data=lambda: calls.append(True) or {'cleared': True, 'removed_files': 0, 'message': 'ok', 'errors': []})
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), namespace)
        namespace['page_settings']()
        return calls, ui.session_state

    def test_confirmation_and_session_cleanup(self):
        for acknowledged, text in [(False, '清空全部数据'), (True, ''), (True, '清空')]:
            calls, state = self.run_settings(acknowledged, text)
            self.assertFalse(calls)
            self.assertIn('last_result', state)
        calls, state = self.run_settings(True, '清空全部数据', submitted=False)
        self.assertFalse(calls)
        calls, state = self.run_settings(True, '清空全部数据')
        self.assertEqual(calls, [True])
        self.assertEqual(set(state), {'admin_ok', 'clear_all_result'})
        self.assertTrue(state['clear_all_result']['cleared'])


if __name__ == '__main__':
    unittest.main()
