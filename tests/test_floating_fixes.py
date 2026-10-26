from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess
from main import Window, Store, STYLE
from kwin_pin import script_source


class FloatingFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.window = Window(Store(Path(self.tmp.name) / 'data.json'))
        self.page = self.window.work
        self.page.initial.setValue(149)
        self.page.start()
        self.page.open_counter()
        self.float = self.page.floating
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_break_text_has_room_and_small_window_can_scroll(self):
        with patch.object(self.window.sounds, 'play'):
            self.page.act(lambda: self.page.ledger.set_count(150))
        self.app.processEvents()
        label = self.float.view.break_text
        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
        self.float.resize(330, 300)
        self.app.processEvents()
        self.assertGreater(self.float.scroll.verticalScrollBar().maximum(), 0)
        self.float.scroll.ensureWidgetVisible(label)
        self.app.processEvents()
        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))

    def test_kwin_script_only_targets_our_pid_and_caption(self):
        source = script_source(1234, 'Точка опоры · Тикеты', True, 'local.Test')
        self.assertIn('w.pid === 1234', source)
        self.assertIn('w.caption ===', source)
        self.assertIn('w.keepAbove = true', source)
        self.assertIn('confirmed = (w.keepAbove === true)', source)
        self.assertIn('w.keepAbove = false', script_source(1234, 'caption', False, 'local.Test'))

    def test_kwin_failure_rolls_back_checkbox_and_does_not_claim_success(self):
        # A real isolated process exercises the same failure protocol without requiring KWin.
        class MissingKwin(QProcess):
            def setArguments(self, args):
                super().setArguments(['-c', 'print(\'{"ok": false}\')'])
        with patch('tickets_ui.QGuiApplication.platformName', return_value='wayland'), patch('tickets_ui.QProcess', MissingKwin):
            self.float.top.setChecked(True)
            self.assertFalse(self.float.top.isEnabled())
            from PySide6.QtTest import QTest
            for _ in range(100):
                if self.float.pin_process is None:
                    break
                QTest.qWait(20)
            self.assertIsNone(self.float.pin_process)
            self.assertFalse(self.float.top.isChecked())
            self.assertIn('Alt+F3', self.float.help.text())

    def test_kwin_success_preserves_confirmed_state(self):
        class KwinSuccess(QProcess):
            def setArguments(self, args):
                super().setArguments(['-c', 'print(\'{"ok": true}\')'])
        with patch('tickets_ui.QGuiApplication.platformName', return_value='wayland'), patch('tickets_ui.QProcess', KwinSuccess):
            self.float.top.setChecked(True)
            from PySide6.QtTest import QTest
            for _ in range(100):
                if self.float.pin_process is None:
                    break
                QTest.qWait(20)
            self.assertTrue(self.float.top.isChecked())
            self.assertIn('KWin подтвердил', self.float.help.text())

    def test_real_session_bus_callback_protocol(self):
        import json
        import shutil
        import subprocess
        import sys
        if not shutil.which('dbus-run-session'):
            self.skipTest('Нет dbus-run-session')
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['dbus-run-session', '--', sys.executable, str(root / 'tests/fixtures/kwin_bus.py'), str(root / 'kwin_pin.py')], capture_output=True, text=True, timeout=15)
        if result.returncode == 127 and 'Operation not permitted' in result.stderr:
            self.skipTest('Среда запрещает локальные D-Bus-сокеты')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])
