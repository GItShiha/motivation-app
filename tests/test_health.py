import copy
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication
from main import Store, Window
from health import HealthLedger


def schedule(**changes):
    return dict(dict(name='Моё действие', kind='Уход', description='Описание', weekdays=list(range(7)), count=1, times=['08:00'], remind=False, start='2024-02-28', end=None), **changes)


class HealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'data.json'
        self.store = Store(self.path)
        self.clock = [datetime.fromisoformat('2024-02-29T09:00:00+03:00')]
        self.ledger = HealthLedger(self.store, now=lambda: self.clock[0])

    def tearDown(self):
        self.tmp.cleanup()

    def test_weekday_range_repetitions_and_no_defaults(self):
        l = self.ledger
        self.assertEqual(l.data['actions'], [])
        aid = l.add(schedule(weekdays=[3], count=2, times=['08:00', '20:00'], end='2024-03-07'))
        self.assertFalse(l.planned(aid, date(2024, 2, 28)))
        self.assertEqual(len(l.slots(date(2024, 2, 29))), 2)
        self.assertFalse(l.planned(aid, date(2024, 3, 1)))
        self.assertTrue(l.planned(aid, date(2024, 3, 7)))
        self.assertFalse(l.planned(aid, date(2024, 3, 14)))
        with self.assertRaises(ValueError):
            l.add(schedule(count=2, times=['08:00']))

    def test_explicit_skip_distinct_from_no_mark_and_clear(self):
        l = self.ledger
        aid = l.add(schedule(count=2, times=[]))
        d = date(2024, 2, 29)
        self.assertEqual(l.day_status(d), 'empty')
        l.mark(d, aid, 0, 'done')
        self.assertEqual(l.day_status(d), 'partial')
        l.mark(d, aid, 1, 'skipped')
        self.assertEqual(l.day_status(d), 'skipped')
        stats = l.statistics(d, d)
        self.assertEqual((stats['percent'], stats['skipped'], stats['unmarked']), (50, 1, 0))
        l.mark(d, aid, 1, 'unmarked')
        self.assertEqual(l.statistics(d, d)['unmarked'], 1)
        l.mark(d, aid, 1, 'done')
        self.assertEqual(l.day_status(d), 'full')
        self.assertEqual(l.statistics(d, d)['full_days'], 1)
        with self.assertRaises(ValueError):
            l.mark(date(2024, 3, 1), aid, 0, 'done')

    def test_revisions_do_not_rewrite_history(self):
        l = self.ledger
        aid = l.add(schedule())
        d = date(2024, 2, 29)
        l.mark(d, aid, 0, 'done')
        l.revise(aid, schedule(name='Новое имя', count=2, times=[]))
        self.assertEqual(len(l.slots(d)), 1)
        self.assertEqual(l.slots(d)[0]['schedule']['name'], 'Моё действие')
        self.assertEqual(l.statistics(d, d)['percent'], 100)
        self.assertEqual(len(l.slots(date(2024, 3, 1))), 2)
        with self.assertRaises(ValueError):
            l.revise(aid, schedule(), effective=d)
        l.revise(aid, schedule(), effective=date(2024, 3, 1), archived=True)
        self.assertEqual(l.day_status(date(2024, 3, 1)), 'none')
        self.assertEqual(l.day_status(d), 'full')

    def test_reminders_once_restart_no_mark_and_missed_dates(self):
        l = self.ledger
        aid = l.add(schedule(remind=True, count=2, times=['08:00', '20:00']))
        self.assertEqual(l.due(), [])
        l.reminders(True)
        self.assertEqual(len(l.due()), 1)
        self.assertEqual(l.due(), [])
        restored = HealthLedger(Store(self.path), now=lambda: self.clock[0])
        self.assertEqual(restored.due(), [])
        self.assertEqual(restored.day_status(date(2024, 2, 29)), 'empty')
        l.mark(date(2024, 2, 29), aid, 1, 'done')
        self.clock[0] = datetime.fromisoformat('2024-02-29T21:00:00+03:00')
        self.assertEqual(l.due(), [])
        self.clock[0] = datetime.fromisoformat('2024-03-02T09:00:00+03:00')
        self.assertEqual(len(l.due()), 1)  # Only today, not all missed days.

    def test_atomic_failure_and_restore_keep_user_data(self):
        l = self.ledger
        aid = l.add(schedule())
        self.store.data['entries']['2024-02-29'] = {'mood': 0, 'fatigue': 3, 'note': 'keep'}
        self.store.save()
        old = copy.deepcopy(l.data)
        with patch.object(self.store, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                l.mark(date(2024, 2, 29), aid, 0, 'done')
        self.assertEqual(l.data, old)
        self.assertEqual(self.store.data['health'], old)
        l.mark(date(2024, 2, 29), aid, 0, 'done')
        loaded = Store(self.path)
        self.assertEqual(HealthLedger(loaded).day_status(date(2024, 2, 29)), 'full')
        from update_bootstrap import atomic, recover
        folder = Path(self.tmp.name) / 'updates'
        before = self.path.read_bytes()
        atomic(folder / 'transaction.json', {'phase': 'testing', 'previous': {'code': '/old', 'python': '/old/python'}})
        recover(folder)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(loaded.data['entries']['2024-02-29']['mood'], 0)

    def test_ui_add_mark_history_edit_and_russian_navigation(self):
        w = Window(self.store)
        p = w.health
        w.navigate(7)
        p.name.setText('Моя процедура')
        p.start.setDate(QDate.currentDate())
        p.save_form()
        self.assertEqual(len(p.ledger.data['actions']), 1)
        aid = p.ledger.data['actions'][0]['id']
        p.act(lambda: p.ledger.mark(date.today(), aid, 0, 'done'))
        self.assertIn('выполнено', p.history.text())
        p.picker.setCurrentIndex(1)
        p.name.setText('Новое название')
        p.save_form()
        self.assertEqual(p.ledger.schedule(aid, date.today())['name'], 'Моя процедура')
        w.show()
        self.app.processEvents()
        self.assertFalse(w.grab().isNull())
        w.close()
        restored = Window(Store(self.path))
        self.assertEqual(restored.health.ledger.day_status(date.today()), 'full')
        restored.close()

    def test_bad_history_stays_untouched(self):
        self.store.data['health'] = {'version': 99}
        self.store.save()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            HealthLedger(self.store)
        w = Window(self.store)
        self.assertIsNone(w.health.ledger)
        self.assertEqual(self.path.read_bytes(), before)
        w.close()

    def test_failed_reminder_save_can_retry_and_does_not_mark_execution(self):
        l = self.ledger
        l.add(schedule(remind=True))
        l.reminders(True)
        with patch.object(self.store, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                l.due()
        self.assertEqual(l.data['notified'], {})
        self.assertEqual(len(l.due()), 1)
        self.assertEqual(l.day_status(date(2024, 2, 29)), 'empty')

    def test_new_revision_supersedes_planned_future_but_not_past(self):
        l = self.ledger
        aid = l.add(schedule())
        l.revise(aid, schedule(name='Будущий план'), effective=date(2024, 4, 1))
        l.revise(aid, schedule(name='Замена'), effective=date(2024, 3, 1))
        self.assertEqual(l.schedule(aid, date(2024, 2, 29))['name'], 'Моё действие')
        self.assertEqual(l.schedule(aid, date(2024, 4, 1))['name'], 'Замена')
