from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from main import Store, Window
from sleep import SleepLedger, daily, duration, analytics, correlation, clock_mean


def period(bed='2024-02-28T23:00:00+03:00', onset='2024-02-28T23:30:00+03:00', wake='2024-02-29T07:30:00+03:00', **changes):
    result = dict(bed=bed, onset=onset, wake=wake, day=wake[:10], quality=7, energy=6, sleepiness=None, awakenings=None, note='Моя запись')
    result.update(changes)
    return result


class SleepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'data.json')
        self.ledger = SleepLedger(self.store, now=lambda: datetime.fromisoformat('2024-03-15T12:00:00+03:00'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_midnight_dst_and_unknown_onset(self):
        self.assertEqual(duration(period()), 8)
        self.assertIsNone(duration(period(onset=None)))
        # Absolute timestamps handle the spring-forward hour correctly.
        self.assertEqual(duration(period(bed='2024-03-30T23:00:00+01:00', onset='2024-03-31T01:00:00+01:00', wake='2024-03-31T08:00:00+02:00')), 6)
        self.assertAlmostEqual(clock_mean([23, 1]) % 24, 0, places=5)

    def test_multiple_periods_wake_day_link_and_overlap(self):
        l = self.ledger
        pid = l.save_period(period())
        l.save_period(period(bed='2024-02-29T13:00:00+03:00', onset='2024-02-29T13:00:00+03:00', wake='2024-02-29T14:00:00+03:00', quality=5))
        d = daily(l.data['periods'])
        self.assertEqual(d['2024-02-29']['hours'], 9)
        self.assertEqual(d['2024-02-29']['quality'], 6)
        self.assertNotIn('2024-02-28', d)
        with self.assertRaises(ValueError):
            l.save_period(period())
        l.save_period(period(day='2024-03-01'), pid)
        self.assertIn('2024-03-01', daily(l.data['periods']))
        l.delete('periods', pid)
        self.assertEqual(len(l.data['periods']), 1)

    def test_missing_is_not_zero_and_correlation_requires_pairs(self):
        rows = [dict(period(), id='x'), dict(period(bed='2024-02-29T12:00:00+03:00', onset=None, wake='2024-02-29T13:00:00+03:00'), id='y')]
        self.assertIsNone(daily(rows)['2024-02-29']['hours'])
        stats = analytics(rows, {'2024-02-29': {'mood': 0}}, date(2024, 2, 1), date(2024, 2, 29))
        self.assertEqual(stats['days'], 1)
        self.assertEqual(stats['mood'], 0)
        self.assertEqual(stats['duration_days'], 0)
        self.assertEqual(correlation([(i, i) for i in range(9)]), (None, 9))
        self.assertEqual(correlation([(i, i) for i in range(10)]), (1, 10))
        self.assertEqual(correlation([(2, i) for i in range(10)]), (None, 10))

    def test_ritual_thoughts_delete_and_io_failure(self):
        l = self.ledger
        l.add_text('thoughts', 'Оставить на завтра')
        self.assertEqual(l.data['thought_draft'], '')
        l.add_text('ritual', 'Мой вечерний шаг')
        rid = l.data['ritual'][0]['id']
        l.ritual_mark(date(2024, 2, 29), rid, True)
        self.assertTrue(l.data['ritual_marks']['2024-02-29'][rid])
        l.delete('thoughts', l.data['thoughts'][0]['id'])
        self.assertEqual(SleepLedger(Store(self.store.path)).data['thoughts'], [])
        with patch.object(self.store, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                l.save_period(period())
        self.assertEqual(l.data['periods'], [])
        self.assertEqual(self.store.data['sleep']['periods'], [])

    def test_ui_form_roundtrip_practice_once_and_concurrent_guard(self):
        w = Window(self.store)
        p = w.sleep
        p.save_form()
        self.assertEqual(len(p.ledger.data['periods']), 1)
        p.load_period(1)
        self.assertIsNotNone(p.editing)
        p.note.setPlainText('Изменено')
        p.save_form()
        self.assertEqual(len(p.ledger.data['periods']), 1)
        practice = p.practice
        practice.sound.setChecked(True)
        practice.start()
        self.assertIsNotNone(practice.exercise)
        w.start_focus()
        self.assertEqual(w.remaining, 0)
        w.recovery.start()
        self.assertIsNone(w.recovery.exercise)
        with patch.object(w.sounds, 'play') as play:
            with patch.object(practice.exercise, 'clock', return_value=practice.exercise.deadline + 1):
                practice.tick()
            practice.tick()
            play.assert_called_once_with('sleep')
        practice.kind.setCurrentIndex(1)
        practice.start()
        practice.next_step()
        self.assertIn('Плечи', practice.step.text())
        practice.finish(False)
        self.assertFalse(p.ledger.data['practice'][-1]['completed'])
        w.navigate(8)
        w.show()
        self.app.processEvents()
        self.assertFalse(w.grab().isNull())
        w.close()
        restored = Window(Store(self.store.path))
        self.assertEqual(restored.sleep.ledger.data['periods'][0]['note'], 'Изменено')
        restored.close()

    def test_update_recovery_keeps_sleep_and_wellbeing(self):
        from update_bootstrap import atomic, recover
        self.ledger.save_period(period())
        self.store.data['entries']['2024-02-29'] = {'mood': 0, 'fatigue': 4, 'note': 'keep'}
        self.store.save()
        before = self.store.path.read_bytes()
        folder = Path(self.tmp.name) / 'updates'
        atomic(folder / 'transaction.json', {'phase': 'launching', 'previous': {'code': '/old', 'python': '/old/python'}})
        recover(folder)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(SleepLedger(Store(self.store.path)).data['periods'][0]['day'], '2024-02-29')

    def test_invalid_data_and_future_are_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.save_period(period(wake='2024-03-16T08:00:00+03:00'))
        self.store.data['sleep'] = {'version': 99}
        self.store.save()
        before = self.store.path.read_bytes()
        w = Window(self.store)
        self.assertIsNone(w.sleep.ledger)
        self.assertEqual(self.store.path.read_bytes(), before)
        w.close()
