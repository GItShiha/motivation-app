import copy
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication
from main import Store, Window
from wellbeing import entries, month_stats, year_stats, month_series, change


def entry(mood):
    return {'mood': mood, 'fatigue': 4, 'note': 'Старая запись'}


class WellbeingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_calendar_lengths_leap_years_and_missing_zero(self):
        for year, month, days in ((2024, 2, 29), (2023, 2, 28), (1900, 2, 28), (2000, 2, 29), (2024, 4, 30), (2024, 12, 31)):
            self.assertEqual(len(month_series({}, year, month)), days)
        raw = {'2024-02-01': entry(0), '2024-02-29': entry(10)}
        stats = month_stats(raw, 2024, 2)
        self.assertEqual(stats, {'count': 2, 'mean': 5, 'best': 10, 'worst': 0})
        values = month_series(raw, 2024, 2)
        self.assertEqual(values[0], 0)
        self.assertIsNone(values[1])
        self.assertEqual(month_stats({}, 2024, 2)['mean'], None)

    def test_comparison_year_boundary_weighted_year_and_invalid(self):
        raw = {f'2023-12-{d:02}': entry(2) for d in range(1, 6)}
        raw.update({f'2024-01-{d:02}': entry(8) for d in range(1, 6)})
        self.assertEqual(change(raw, 2024, 1), 6)
        self.assertIsNone(change(raw, 2024, 2))
        raw['2024-02-01'] = entry(2)
        self.assertEqual(year_stats(raw, 2024)['mean'], 7)
        raw.update({'bad-date': entry(9), '2024-02-30': entry(4), '2024-02-02': entry(True), '2024-02-03': None, '9999-01-01': entry(10)})
        self.assertEqual(len(entries(raw, today=date(2024, 3, 1))), 11)
        self.assertEqual(year_stats(raw, 2024)['count'], 6)

    def test_old_history_identity_and_edit_preserves_other_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.json'
            store = Store(path)
            raw = {'2000-02-29': dict(entry(3), extra='keep'), '2023-12-31': entry(9)}
            store.data['entries'] = copy.deepcopy(raw)
            store.data['custom'] = {'keep': True}
            store.save()
            original = path.read_bytes()
            loaded = Store(path)
            self.assertEqual(loaded.data['entries'], raw)
            self.assertEqual(path.read_bytes(), original)  # No destructive migration at load.
            window = Window(loaded)
            calendar = window.wellbeing.calendar
            calendar.setSelectedDate(QDate(2000, 2, 29))
            self.assertEqual(window.sliders[0].value(), 3)
            window.sliders[0].setValue(0)
            window.note.setPlainText('Обновлено')
            window.save_entry()
            saved = Store(path).data
            self.assertEqual(saved['entries']['2000-02-29']['mood'], 0)
            self.assertEqual(saved['entries']['2000-02-29']['extra'], 'keep')
            self.assertEqual(saved['entries']['2023-12-31'], raw['2023-12-31'])
            self.assertEqual(saved['custom'], {'keep': True})
            self.assertEqual(calendar.maximumDate(), QDate.currentDate())
            window.close()

    def test_browsing_does_not_create_records_and_draft_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.json'
            window = Window(Store(path))
            for day in (QDate(2024, 2, 29), QDate(2023, 12, 31)):
                window.wellbeing.calendar.setSelectedDate(day)
            window.close()
            window = Window(Store(path))
            self.assertFalse(window.wellbeing.dirty)
            self.assertEqual(window.store.data['entries'], {})
            window.wellbeing.calendar.setSelectedDate(QDate(2024, 2, 29))
            window.note.setPlainText('Черновик до отключения питания')
            snapshot = Store(path)  # Reopen before normal close: simulate process loss.
            restored = Window(snapshot)
            self.assertEqual(restored.wellbeing.selected, date(2024, 2, 29))
            self.assertEqual(restored.note.toPlainText(), 'Черновик до отключения питания')
            self.assertTrue(restored.wellbeing.dirty)
            self.assertEqual(snapshot.data['entries'], {})
            restored.save_entry()
            self.assertEqual(Store(path).data['wellbeing_drafts'], {})
            restored.close()
            window.wellbeing.dirty = False
            window.close()

    def test_save_failure_keeps_history_and_selected_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(Store(Path(tmp) / 'data.json'))
            window.wellbeing.calendar.setSelectedDate(QDate(2024, 2, 29))
            window.note.setPlainText('Не потерять')
            before = copy.deepcopy(window.store.data['entries'])
            with patch.object(window, 'persist', return_value=False):
                window.wellbeing.calendar.setSelectedDate(QDate(2024, 3, 1))
                self.assertEqual(window.wellbeing.selected, date(2024, 2, 29))
                self.assertEqual(window.wellbeing.calendar.selectedDate(), QDate(2024, 2, 29))
                self.assertEqual(window.store.data['entries'], before)
                self.assertEqual(window.note.toPlainText(), 'Не потерять')
                self.assertIn('Февраль 2024', window.wellbeing.month_summary.text())
            window.close()

    def test_invalid_records_are_preserved_and_calendar_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.json'
            store = Store(path)
            store.data['entries'] = {'bad': {'mood': 'x'}, '2024-02-29': entry(0)}
            window = Window(store)
            window.show()
            window.navigate(3)
            window.wellbeing.calendar.setSelectedDate(QDate(2024, 2, 29))
            self.app.processEvents()
            self.assertFalse(window.grab().isNull())
            self.assertIn('Дней с записью: 1', window.wellbeing.month_summary.text())
            window.close()
            self.assertEqual(Store(path).data['entries']['bad'], {'mood': 'x'})

    def test_clear_day_removes_record_and_draft_without_recreating_on_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.json'
            store = Store(path)
            store.data['entries'] = {'2024-02-29': entry(0), '2024-02-28': entry(8)}
            window = Window(store)
            window.wellbeing.calendar.setSelectedDate(QDate(2024, 2, 29))
            window.note.setPlainText('Черновик')
            self.assertTrue(window.wellbeing.clear_day())
            self.assertFalse(window.wellbeing.dirty)
            self.assertNotIn('2024-02-29', window.wellbeing.calendar.records)
            self.assertEqual(month_stats(store.data['entries'], 2024, 2)['mean'], 8)
            window.close()
            restored = Window(Store(path))
            self.assertNotIn('2024-02-29', restored.store.data['entries'])
            self.assertNotIn('2024-02-29', restored.wellbeing.drafts())
            self.assertFalse(restored.wellbeing.dirty)
            restored.close()

    def test_clear_failure_preserves_record_and_editor(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'data.json')
            store.data['entries'] = {'2024-02-29': entry(7)}
            window = Window(store)
            window.wellbeing.calendar.setSelectedDate(QDate(2024, 2, 29))
            with patch.object(window, 'persist', return_value=False):
                self.assertFalse(window.wellbeing.clear_day())
            self.assertEqual(store.data['entries']['2024-02-29']['mood'], 7)
            self.assertEqual(window.sliders[0].value(), 7)
            window.close()
