import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import copy
import unittest
from pathlib import Path
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from main import Store, Window, STYLE
from guide import EXAMPLES


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

    def test_guide_examples_are_editable_and_not_autosaved(self):
        with tempfile.TemporaryDirectory() as folder:
            w = Window(Store(Path(folder) / 'data.json'))
            w.show()
            w.navigate(1)
            self.app.processEvents()
            self.assertFalse(w.guide.toggle.isChecked())
            w.guide.toggle.click()
            w.guide.sections['examples'][0].click()
            for btn, (_, trigger, action) in zip(w.guide.example_buttons, EXAMPLES):
                btn.click()
                self.assertEqual(w.trigger.text(), trigger)
                self.assertEqual(w.action.text(), action)
                self.assertEqual(w.store.data['plans'], [])
            w.action.setText('Закрываю ленту и открываю свой тикет')
            w.add_plan()
            saved = Store(w.store.path).data['plans']
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]['action'], 'Закрываю ленту и открываю свой тикет')
            w.close()

    def test_guide_state_survives_restart_and_preserves_old_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.json'
            old = Store(path)
            old.data['plans'].append({'id': 1, 'trigger': 'Сигнал', 'action': 'Действие', 'done': 2})
            old.data['entries']['2026-01-01'] = {'mood': 7, 'fatigue': 3, 'note': 'Отдых'}
            old.data['sessions'].append({'date': '2026-01-01', 'minutes': 15})
            original = copy.deepcopy(old.data)
            old.save()
            w = Window(Store(path))
            w.show()
            w.navigate(1)
            w.guide.toggle.click()
            w.guide.sections['how'][0].click()
            w.guide.sections['what'][0].click()
            self.app.processEvents()
            for _ in range(5):
                self.app.processEvents()
            QTest.qWait(50)
            self.assertGreater(w.plan_list.geometry().top(), w.guide.geometry().bottom())
            w.grab().save('/tmp/motivation-guide.png')
            w.close()
            restored = Store(path)
            for key, value in original.items():
                self.assertEqual(restored.data[key], value)
            w = Window(restored)
            self.assertTrue(w.guide.toggle.isChecked())
            self.assertTrue(w.guide.sections['how'][0].isChecked())
            self.assertFalse(w.guide.sections['what'][0].isChecked())
            w.guide.toggle.click()
            self.assertTrue(w.guide.contents.isHidden())
            w.close()
            w = Window(Store(path))
            self.assertFalse(w.guide.toggle.isChecked())
            self.assertTrue(w.guide.sections['how'][0].isChecked())
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
