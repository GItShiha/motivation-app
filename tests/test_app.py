import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
import time
from PySide6.QtWidgets import QApplication
from main import Store, Window, STYLE


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def test_workflow_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.json'
            w = Window(Store(path))
            w.show()
            self.app.processEvents()
            w.add_plan()
            self.assertEqual(w.store.data['plans'], [])
            w.trigger.setText('Открою ленту')
            w.action.setText('Сделаю вдох')
            w.add_plan()
            pid = w.store.data['plans'][0]['id']
            w.plan_action(pid)
            w.sliders[0].setValue(7)
            w.sliders[1].setValue(4)
            w.note.setPlainText('Прогулка помогла')
            w.save_entry()
            w.duration.setValue(1)
            w.start_focus()
            w.pause_focus()
            self.assertIsNone(w.deadline)
            w.pause_focus()
            self.assertIsNotNone(w.deadline)
            w.deadline = time.monotonic() - 1
            w.tick()
            self.assertEqual(w.metrics[1].text(), '1')
            w.start_focus()
            w.stop_focus()
            self.assertEqual(len(w.store.data['sessions']), 1)
            restored = Store(path)
            self.assertEqual(restored.data['plans'][0]['done'], 1)
            self.assertEqual(next(iter(restored.data['entries'].values()))['mood'], 7)
            self.assertEqual(len(restored.data['sessions']), 1)
            for i in range(4):
                w.navigate(i)
                self.app.processEvents()
            w.grab().save('/tmp/motivation-app.png')
            w.close()

    def test_corrupt_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.json'
            path.write_text('broken', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                Store(path)
            self.assertEqual(path.read_text(), 'broken')


if __name__ == '__main__':
    unittest.main()
