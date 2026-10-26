import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QApplication
from main import Store, Window
from sounds import TimerSounds, preferences, TONES


class SoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_completion_once_even_when_hidden_and_cancel_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Window(Store(Path(tmp) / 'data.json'))
            with patch.object(w.sounds, 'play') as play:
                w.start_focus()
                w.hide()
                w.deadline = time.monotonic() - 1
                w.tick()
                w.tick()
                w.stop_focus(completed=True)
                play.assert_called_once_with('focus')
                self.assertEqual(len(w.store.data['sessions']), 1)
                play.reset_mock()
                w.start_focus()
                w.stop_focus()
                play.assert_not_called()
                w.recovery.start()
                with patch.object(w.recovery.exercise, 'clock', return_value=w.recovery.exercise.deadline + 1):
                    w.recovery.tick()
                w.recovery.tick()
                w.recovery.finish('completed')
                play.assert_called_once_with('recovery')
                for status in ('interrupted', 'cancelled'):
                    play.reset_mock()
                    w.recovery.new_method()
                    w.recovery.start()
                    w.recovery.finish(status)
                    play.assert_not_called()
            w.close()

    def test_settings_roundtrip_and_old_data_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.json'
            store = Store(path)
            store.data['unknown_future_key'] = {'keep': True}
            w = Window(store)
            settings = w.sound_settings
            settings.volume.setValue(17)
            settings.tone.setCurrentIndex(2)
            settings.categories['focus'].setChecked(False)
            settings.enabled.setChecked(False)
            loaded = Store(path)
            self.assertEqual(loaded.data['sounds'], w.sounds.settings)
            self.assertEqual(loaded.data['unknown_future_key'], {'keep': True})
            self.assertFalse(settings.preview.isEnabled())
            w.close()
            w = Window(Store(path))
            self.assertEqual(w.sound_settings.volume.value(), 17)
            self.assertEqual(w.sound_settings.tone.currentData(), 'two_notes')
            self.assertFalse(w.sound_settings.enabled.isChecked())
            w.close()

    def test_muting_preview_and_worker_failure_are_safe(self):
        store = MagicMock(data={})
        process = MagicMock()
        factory = MagicMock(return_value=process)
        sounds = TimerSounds(store, process_factory=factory)
        sounds.apply({'enabled': False})
        sounds.play('focus')
        factory.assert_not_called()
        sounds.apply({'volume': 0})
        sounds.play()
        factory.assert_not_called()
        sounds.apply({'categories': {'focus': False}, 'tone': 'bell', 'volume': 42})
        sounds.play('focus')
        factory.assert_not_called()
        with patch.object(sounds, 'watch'):
            sounds.play()  # Explicit preview bypasses category filtering only.
        process.start.assert_called_once()
        args = process.setArguments.call_args.args[0]
        self.assertEqual(args[1:], ['bell', '42'])
        statuses = []
        sounds.status_changed.connect(statuses.append)
        sounds.failed(process, QProcess.ProcessError.Crashed)
        sounds.finished(process, 1)
        self.assertIsNone(sounds.process)
        self.assertTrue(statuses[-1])
        self.assertEqual(preferences({'volume': 'bad', 'tone': [], 'categories': 1})['volume'], 35)

    def test_navigation_bottom_scroll_and_keyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Window(Store(Path(tmp) / 'data.json'))
            w.resize(850, 650)
            w.show()
            self.app.processEvents()
            side = w.centralWidget().layout().itemAt(0).widget()
            self.assertIs(side.layout().itemAt(side.layout().count() - 1).widget(), w.navs[4])
            self.assertTrue(w.navs[4].isVisible())
            self.assertLess(w.nav_scroll.geometry().bottom(), w.navs[4].geometry().top())
            w.navs[4].click()
            self.assertEqual(w.stack.currentIndex(), 4)
            self.assertEqual(w.navs[4].focusPolicy(), Qt.FocusPolicy.StrongFocus)
            w.resize(1140, 900)
            self.app.processEvents()
            self.assertLessEqual(side.height() - w.navs[4].geometry().bottom(), 30)
            w.close()

    def test_bundled_tones_are_finite_pcm(self):
        root = Path(__file__).resolve().parents[1] / 'assets/sounds'
        for tone in TONES:
            with wave.open(str(root / (tone + '.wav'))) as source:
                self.assertEqual(source.getnchannels(), 1)
                self.assertEqual(source.getsampwidth(), 2)
                self.assertGreater(source.getnframes(), 0)
                self.assertLess(source.getnframes() / source.getframerate(), 1)
