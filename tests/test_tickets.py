import copy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from main import Store, Window
from tickets import TicketLedger, DEFAULTS


class TicketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'data.json'
        self.store = Store(self.path)
        self.clock = [datetime.fromisoformat('2026-01-31T23:58:00+03:00')]
        self.ledger = TicketLedger(self.store, now=lambda: self.clock[0])

    def tearDown(self):
        self.tmp.cleanup()

    def test_thresholds_once_after_decrement_correction_and_restart(self):
        l = self.ledger
        l.start(49)
        self.assertEqual(l.step(1), ['break'])
        self.assertEqual(l.step(-1), [])
        self.assertEqual(l.step(1), [])
        restored = TicketLedger(Store(self.path))
        self.assertEqual(restored.active['count'], 50)
        self.assertEqual(restored.set_count(49), [])
        self.assertEqual(restored.step(1), [])
        self.assertEqual(restored.set_count(155), ['break'])
        self.assertEqual(len(restored.active['breaks']), 2)
        restored.mark_break('later')
        self.assertTrue(all(e['state'] == 'later' for e in restored.active['breaks']))
        self.assertEqual(restored.set_count(100), [])
        self.assertEqual(restored.set_count(155), [])

    def test_goal_actual_and_capped_progress(self):
        l = self.ledger
        l.start(261)
        self.assertEqual(l.step(1), ['goal'])
        l.step(1)
        self.assertEqual((l.active['count'], l.active['credited'], l.active['percent']), (263, 262, 100))
        l.set_count(260)
        self.assertEqual(l.set_count(263), [])
        l.configure(dict(DEFAULTS, track_excess=False))
        self.assertEqual(l.step(1), [])
        self.assertEqual(l.active['count'], 263)
        l.set_count(0)
        l.step(-1)
        self.assertEqual(l.active['count'], 0)

    def test_reminders_disabled_do_not_replay_and_interval_can_change(self):
        l = self.ledger
        l.configure(dict(DEFAULTS, reminders=False))
        l.start()
        self.assertEqual(l.set_count(151), [])
        l.configure(dict(DEFAULTS, interval=25))
        self.assertEqual(l.set_count(150), [])
        self.assertEqual(l.set_count(151), [])
        self.assertEqual(l.set_count(175), ['break'])

    def test_shift_survives_midnight_and_history_is_explicit(self):
        l = self.ledger
        l.start(73)
        first_id = l.active['id']
        self.clock[0] = datetime.fromisoformat('2026-02-01T01:00:00+03:00')
        l.step(1)
        self.assertEqual(l.active['id'], first_id)
        self.assertEqual(l.active['date'], '2026-01-31')
        self.assertEqual(l.statistics(1)['count'], 0)
        self.assertEqual(l.statistics(7)['count'], 74)
        l.start(2)
        self.assertEqual(len(l.data['shifts']), 2)
        self.assertIsNotNone(l.data['shifts'][0]['ended_at'])
        self.assertEqual(l.statistics(month=True)['count'], 2)
        l.end()
        self.assertIsNone(l.active)
        self.assertEqual(len(TicketLedger(Store(self.path)).data['shifts']), 2)

    def test_io_failure_rolls_back_counts_and_watermark(self):
        l = self.ledger
        l.start(49)
        before = copy.deepcopy(l.data)
        with patch.object(self.store, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                l.step(1)
        self.assertEqual(l.data, before)
        self.assertEqual(self.store.data['tickets'], before)
        self.assertEqual(l.step(1), ['break'])
        self.assertEqual(TicketLedger(Store(self.path)).active['count'], 50)

    def test_invalid_data_is_not_overwritten(self):
        self.store.data['tickets'] = {'version': 99}
        self.store.save()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            TicketLedger(self.store)
        self.assertEqual(self.path.read_bytes(), before)

    def test_ui_sync_compact_geometry_and_no_sound_replay(self):
        w = Window(self.store)
        p = w.work
        p.initial.setValue(49)
        p.start()
        p.open_counter()
        with patch.object(w.sounds, 'play') as play:
            p.floating.view.plus.click()
            play.assert_called_once_with('tickets_break')
            self.assertEqual(p.ledger.active['count'], 50)
            self.assertEqual(p.view.count.text(), p.floating.view.count.text())
            self.assertTrue(p.floating.view.break_box.isVisible())
            p.act(lambda: p.ledger.mark_break('skipped'))
            p.floating.view.minus.click()
            p.floating.view.plus.click()
            self.assertEqual(play.call_count, 1)
        p.floating.compact.setChecked(True)
        self.assertTrue(p.floating.view.details.isHidden())
        p.floating.top.setChecked(True)
        self.assertTrue(p.floating.save_state())
        w.close()
        w = Window(Store(self.path))
        with patch.object(w.sounds, 'play') as play:
            w.work.open_counter()
            self.assertEqual(w.work.ledger.active['count'], 50)
            self.assertTrue(w.work.floating.compact.isChecked())
            self.assertTrue(w.work.floating.top.isChecked())
            play.assert_not_called()
        w.close()

    def test_goal_tone_and_other_user_data_survive(self):
        self.store.data['entries']['2024-02-29'] = {'mood': 0, 'fatigue': 3, 'note': 'keep'}
        w = Window(self.store)
        p = w.work
        p.initial.setValue(261)
        p.start()
        with patch.object(w.sounds, 'play') as play:
            p.view.plus.click()
            play.assert_called_once_with('tickets_goal', tone='bell')
        w.close()
        loaded = Store(self.path)
        self.assertEqual(loaded.data['entries']['2024-02-29']['mood'], 0)
        self.assertEqual(loaded.data['tickets']['shifts'][0]['count'], 262)

    def test_update_recovery_preserves_ledger_and_other_data(self):
        from update_bootstrap import atomic, recover, read_json
        l = self.ledger
        l.start(49)
        l.step(1)
        self.store.data['entries']['2024-02-29'] = {'mood': 0, 'fatigue': 4, 'note': 'keep'}
        self.store.save()
        before = self.path.read_bytes()
        folder = Path(self.tmp.name) / 'updates'
        atomic(folder / 'backup.json', self.store.data)
        atomic(folder / 'transaction.json', {'phase': 'launching', 'previous': {'code': '/old', 'python': '/old/python'}})
        recover(folder)
        self.assertEqual(self.path.read_bytes(), before)
        restored = TicketLedger(Store(self.path))
        self.assertEqual(restored.active['count'], 50)
        self.assertEqual(restored.set_count(49), [])
        self.assertEqual(restored.step(1), [])
        self.assertEqual(read_json(folder / 'backup.json')['entries']['2024-02-29']['mood'], 0)
