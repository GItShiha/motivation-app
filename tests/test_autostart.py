import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from autostart import Autostart
from main import Store, Window
from PySide6.QtWidgets import QApplication


class AutostartTest(unittest.TestCase):
    def test_linux_registration_is_repeatable_and_removable(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Autostart('linux', folder, {}, ['/a b/python', '/app $x/100%.py'])
            self.assertFalse(manager.enabled())
            manager.set_enabled(True)
            original = manager.path.read_text()
            self.assertIn('Exec="/a b/python" "/app \\\\$x/100%%.py"', original)
            manager.set_enabled(True)
            self.assertEqual(manager.path.read_text(), original)
            self.assertTrue(manager.enabled())
            manager.set_enabled(False)
            manager.set_enabled(False)
            self.assertFalse(manager.enabled())

    def test_linux_uses_xdg_config(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'custom'
            manager = Autostart('linux', folder, {'XDG_CONFIG_HOME': str(config)})
            self.assertEqual(manager.path.parent, config / 'autostart')

    def test_macos_launch_agent(self):
        with tempfile.TemporaryDirectory() as folder:
            command = ['/python path/python', '/app path/main.py']
            manager = Autostart('darwin', folder, {}, command)
            manager.set_enabled(True)
            data = plistlib.loads(manager.path.read_bytes())
            self.assertEqual(data['ProgramArguments'], command)
            self.assertTrue(data['RunAtLoad'])
            self.assertIn('Library/LaunchAgents', str(manager.path))
            manager.set_enabled(False)
            self.assertFalse(manager.enabled())

    def test_windows_current_user_registry(self):
        registry = Mock()
        registry.CreateKey.return_value.__enter__ = Mock(return_value='key')
        registry.CreateKey.return_value.__exit__ = Mock(return_value=False)
        registry.OpenKey.return_value.__enter__ = Mock(return_value='key')
        registry.OpenKey.return_value.__exit__ = Mock(return_value=False)
        manager = Autostart('win32', command=['C:\\Python Dir\\python.exe', 'C:\\App Dir\\main.py'])
        with patch.dict('sys.modules', winreg=registry):
            manager.set_enabled(True)
            self.assertEqual(registry.SetValueEx.call_args.args[-1],
                             '"C:\\Python Dir\\python.exe" "C:\\App Dir\\main.py"')
            self.assertTrue(manager.enabled())
            manager.set_enabled(False)
            registry.DeleteValue.assert_called_once_with('key', 'TochkaOpory')
            registry.OpenKey.side_effect = FileNotFoundError
            self.assertFalse(manager.enabled())
            manager.set_enabled(False)

    def test_settings_persist_and_revert_on_error(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            manager = Autostart('linux', folder, {})
            window = Window(Store(Path(folder) / 'data.json'), manager)
            window.autostart_toggle.setChecked(True)
            self.assertTrue(manager.enabled())
            window.close()
            window = Window(Store(Path(folder) / 'data.json'), manager)
            self.assertTrue(window.autostart_toggle.isChecked())
            with patch.object(manager, 'set_enabled', side_effect=PermissionError('denied')):
                window.autostart_toggle.setChecked(False)
            self.assertTrue(window.autostart_toggle.isChecked())
            self.assertIn('Не удалось', window.autostart_status.text())
            self.assertTrue(manager.enabled())
            window.autostart_toggle.setChecked(False)
            self.assertFalse(manager.enabled())
            window.close()
