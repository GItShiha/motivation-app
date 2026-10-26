import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QApplication
from main import Window, Store
from updater import check, UpdateError, install, run
from update_bootstrap import atomic, read_json, recover


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True, stderr=subprocess.DEVNULL).strip()


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def repo(self, folder):
        root = Path(folder) / 'repo'
        root.mkdir()
        git(root, 'init', '-b', 'main')
        git(root, 'config', 'user.name', 'Fixture')
        git(root, 'config', 'user.email', 'fixture@example.invalid')
        git(root, 'remote', 'add', 'origin', 'https://github.com/GItShiha/motivation-app.git')
        (root / 'file').write_text('one')
        (root / 'main.py').write_text('# fixture launcher')
        git(root, 'add', 'file', 'main.py')
        git(root, 'commit', '-m', 'one')
        old = git(root, 'rev-parse', 'HEAD')
        (root / 'file').write_text('two')
        git(root, 'commit', '-am', 'two')
        target = git(root, 'rev-parse', 'HEAD')
        git(root, 'update-ref', 'refs/remotes/origin/main', target)
        git(root, 'checkout', '--detach', old)
        return root, old, target

    def test_graph_comparison_dirty_wrong_remote_and_divergence(self):
        with tempfile.TemporaryDirectory() as folder:
            root, old, target = self.repo(folder)
            result = check(root, fetch=False)
            self.assertTrue(result['available'])
            self.assertEqual(result['target'], target)
            (root / 'untracked').write_text('preserve')
            with self.assertRaisesRegex(UpdateError, 'незакоммиченные'):
                check(root, fetch=False)
            (root / 'untracked').unlink()
            (root / 'file').write_text('local')
            git(root, 'commit', '-am', 'local')
            with self.assertRaisesRegex(UpdateError, 'расходится'):
                check(root, fetch=False)
            git(root, 'remote', 'set-url', 'origin', 'https://example.invalid/repo')
            with self.assertRaisesRegex(UpdateError, 'Источник'):
                check(root, fetch=False)

    def test_power_failure_restores_pointer_without_touching_new_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            data = folder / 'data.json'
            atomic(data, {'new_schema': ['new records']})
            previous = {'code': '/old', 'python': '/old/python'}
            for phase in ('preparing', 'testing', 'launching'):
                atomic(folder / 'active.json', {'code': '/new'})
                atomic(folder / 'transaction.json', {'phase': phase, 'previous': previous})
                self.assertEqual(recover(folder)['phase'], 'failed')
                self.assertEqual(read_json(folder / 'active.json'), previous)
                self.assertEqual(read_json(data), {'new_schema': ['new records']})
            self.assertEqual(recover(folder)['phase'], 'failed')

    def test_install_failure_keeps_code_env_and_live_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, old, target = self.repo(tmp)
            data = Path(tmp) / 'data.json'
            atomic(data, {'plans': [], 'entries': {}, 'sessions': []})
            folder = Path(tmp) / 'updates'
            with patch('updater.check', return_value={'target': target, 'available': True}), patch('updater.launch') as launch, patch('updater.shutil.disk_usage', return_value=MagicMock(free=10 * 1024**3)):
                # Old fixture lacks protocol; installer must return to old code.
                self.assertFalse(install(root, target, data, folder=folder))
            self.assertEqual(git(root, 'rev-parse', 'HEAD'), old)
            self.assertEqual((root / 'file').read_text(), 'one')
            self.assertEqual(read_json(folder / 'transaction.json')['phase'], 'failed')
            self.assertEqual(read_json(folder / 'active.json')['revision'], old)
            self.assertEqual(read_json(data)['plans'], [])
            self.assertEqual(launch.call_count, 1)
            self.assertTrue(list((folder / 'releases').glob('*/data-before.json')))

    def test_network_errors_do_not_leak_command_output(self):
        fake = subprocess.CompletedProcess([], 1, '', 'TOKEN_SECRET')
        with patch('updater.subprocess.run', return_value=fake):
            with self.assertRaises(UpdateError) as caught:
                run(['git', 'fetch'])
        self.assertNotIn('TOKEN_SECRET', str(caught.exception))

    def test_ui_later_manual_check_and_focus_deferral(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Store(Path(tmp) / 'data.json'))
            panel = window.updates
            panel.target = 'a' * 40
            panel.banner.show()
            panel.later()
            self.assertEqual(panel.settings['dismissed'], panel.target)
            self.assertTrue(panel.banner.isHidden())
            window.duration.setValue(1)
            window.start_focus()
            panel.update_focus()
            self.assertFalse(panel.install_button.isEnabled())
            with patch.object(panel, 'install') as install_mock:
                panel.confirm()
                install_mock.assert_not_called()
            window.stop_focus()
            panel.update_focus()
            self.assertTrue(panel.install_button.isEnabled())
            self.assertTrue(panel.banner.isHidden())
            window.close()

    def test_dependency_failure_launch_failure_and_success(self):
        for failure in ('pip', 'launch', None):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root, old, target = self.repo(tmp)
                git(root, 'checkout', '--detach', target)
                (root / 'update_bootstrap.py').write_text('# protocol fixture')
                git(root, 'add', '.')
                git(root, 'commit', '-m', 'protocol')
                target = git(root, 'rev-parse', 'HEAD')
                git(root, 'update-ref', 'refs/remotes/origin/main', target)
                git(root, 'checkout', '--detach', old)
                folder = Path(tmp) / 'updates'
                data = Path(tmp) / 'data.json'
                atomic(data, {'plans': [{'id': 1}], 'entries': {}, 'sessions': []})
                import updater
                real_run = updater.run
                def commands(args, **kwargs):
                    if str(args[0]) == 'git':
                        return real_run(args, **kwargs)
                    if failure == 'pip' and 'install' in args:
                        raise UpdateError('Ошибка установки зависимостей')
                    return ''
                process = MagicMock()
                process.poll.return_value = None
                def launching(version, data_path, state, trial=False):
                    if trial and failure == 'launch':
                        # Simulate a new version writing data before failing.
                        atomic(data_path, {'plans': [{'id': 1}, {'id': 2}], 'entries': {}, 'sessions': []})
                        raise UpdateError('Неудачный запуск')
                    return process
                with patch('updater.run', side_effect=commands), patch('updater.check', return_value={'target': target, 'available': True}), patch('updater.launch', side_effect=launching) as launch_mock, patch('updater.shutil.disk_usage', return_value=MagicMock(free=10 * 1024**3)):
                    self.assertEqual(install(root, target, data, folder=folder), failure is None)
                self.assertEqual(git(root, 'rev-parse', 'HEAD'), old)
                journal = read_json(folder / 'transaction.json')
                self.assertEqual(journal['phase'], 'failed' if failure else 'complete')
                active = read_json(folder / 'active.json')
                self.assertEqual(active['revision'], old if failure else target)
                self.assertEqual(len(read_json(data)['plans']), 2 if failure == 'launch' else 1)
                if failure:
                    self.assertEqual(launch_mock.call_args.kwargs, {})  # fallback, not trial

    def test_disk_space_and_target_change_stop_before_dependencies(self):
        for changed in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                root, old, target = self.repo(tmp)
                folder = Path(tmp) / 'updates'
                with patch('updater.check', return_value={'target': 'b' * 40 if changed else target, 'available': True}), patch('updater.launch'), patch('updater.shutil.disk_usage', return_value=MagicMock(free=0)):
                    self.assertFalse(install(root, target, Path(tmp) / 'data.json', folder=folder))
                self.assertFalse((folder / 'releases').exists())
                self.assertEqual(git(root, 'rev-parse', 'HEAD'), old)

    def test_new_schema_is_not_overwritten_by_old_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.json'
            value = {'plans': [], 'entries': {}, 'sessions': [], 'schema_version': 99}
            atomic(path, value)
            with self.assertRaises(RuntimeError):
                Store(path)
            self.assertEqual(read_json(path), value)

    def test_real_offscreen_startup_handshake(self):
        import sys
        import time
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ready = folder / 'ready.json'
            data = folder / 'data.json'
            atomic(data, {'plans': [], 'entries': {}, 'sessions': [], 'updates': {'auto': False}})
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM='offscreen', XDG_DATA_HOME=tmp, TOCHKA_UPDATE_DATA=str(data), TOCHKA_UPDATE_TRIAL=str(ready))
            main = Path(__file__).resolve().parents[1] / 'main.py'
            process = subprocess.Popen([sys.executable, str(main)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertIsNone(process.poll())
                self.assertEqual(read_json(ready), {'ready': True})
                second = subprocess.run([sys.executable, str(main)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                self.assertNotEqual(second.returncode, 0)
                self.assertEqual(read_json(data)['plans'], [])
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_manual_rollback_keeps_data_and_launcher(self):
        from updater import rollback
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root, old, _ = self.repo(tmp)
            (root / 'main.py').write_text('# restored launcher')
            git(root, 'add', 'main.py')
            git(root, 'commit', '-m', 'launcher')
            folder = Path(tmp) / 'updates'
            previous = {'code': str(root), 'python': sys.executable, 'launcher': [sys.executable, str(root / 'main.py')]}
            atomic(folder / 'transaction.json', {'phase': 'complete', 'previous': previous})
            data = Path(tmp) / 'data.json'
            atomic(data, {'new_data': 'keep'})
            self.assertEqual(rollback(folder), previous)
            self.assertEqual(read_json(folder / 'active.json'), previous)
            self.assertEqual(read_json(data), {'new_data': 'keep'})
            self.assertEqual(read_json(folder / 'transaction.json')['phase'], 'rolled_back')
