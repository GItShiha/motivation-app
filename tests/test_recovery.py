import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from main import Store, Window
from recovery import ExerciseTimer, recommend, statistics, history, delta


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_recommendations_respect_time_and_state(self):
        for state in range(5):
            for minutes in (2, 5, 10, 20):
                for m in recommend(state, minutes):
                    self.assertIn(state, m.states)
                    self.assertLessEqual(30 if m.key == 'nap' else m.minimum, minutes)
        self.assertIn('breath', [m.key for m in recommend(2, 5)])
        self.assertNotIn('nap', [m.key for m in recommend(1, 20)])

    def test_timer_uses_deadline_not_event_count(self):
        clock = [10.0]
        timer = ExerciseTimer(120, clock=lambda: clock[0])
        clock[0] += 90.2
        self.assertEqual(timer.remaining, 30)
        clock[0] += 50
        self.assertEqual(timer.remaining, 0)
        self.assertEqual(timer.elapsed, 120)

    def test_statistics_handles_missing_invalid_and_reverse_fatigue(self):
        now = datetime.now().astimezone()
        record = dict(method='rest', state=0, started_at=now.isoformat(), status='completed', before={'fatigue': 8, 'focus': 3}, after={'fatigue': 4, 'focus': 5})
        self.assertEqual(delta(record), 3)
        cancelled = dict(record, status='cancelled')
        result = statistics([record, cancelled, {}, dict(record, started_at='invalid')], days=7, now=now)['rest']
        self.assertEqual(result, dict(uses=2, rated=1, mean=3, improved=1))
        self.assertIsNone(delta({'before': {'energy': True}, 'after': {'energy': 10}}))
        self.assertEqual(history({'recovery': [None, {}, record]}), [record])
        self.assertEqual(history({'recovery': {}}), [])
        self.assertEqual(statistics([record], state=1), {})

    def test_personalization_requires_five_pairs(self):
        record = dict(method='rest', state=0, started_at=datetime.now().astimezone().isoformat(), status='completed', before={'energy': 1}, after={'energy': 9})
        self.assertEqual(recommend(0, 5, [record] * 4)[0].key, 'move')
        self.assertEqual(recommend(0, 5, [record] * 5)[0].key, 'rest')

    def test_ui_roundtrip_cancel_and_focus_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'data.json')
            window = Window(store)
            page = window.recovery
            window.navigate(5)
            page.plan.setText('Открыть тикет')
            page.before.mode.setCurrentIndex(1)
            page.before.fields['energy'][1].setValue(3)
            page.start()
            with patch.object(page.exercise, 'clock', return_value=page.exercise.deadline + 1):
                page.tick()
            self.assertEqual(page.pages.currentIndex(), 2)
            self.assertEqual(window.remaining, 0)
            page.after.fields['energy'][1].setValue(7)
            page.save_result()
            page.save_result()
            loaded = Store(store.path)
            self.assertEqual(len(loaded.data['recovery']), 1)
            self.assertEqual(delta(loaded.data['recovery'][0]), 4)
            self.assertEqual(loaded.data['plans'], [])
            page.new_method()
            page.start()
            page.finish('cancelled')
            self.assertEqual(store.data['recovery'][-1]['status'], 'cancelled')
            page.focus()
            self.assertGreater(window.remaining, 0)
            window.stop_focus()
            window.close()

    def test_invalid_recovery_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'data.json')
            store.data['recovery'] = {'unknown': 'preserve'}
            window = Window(store)
            window.recovery.start()
            window.recovery.finish('interrupted')
            self.assertFalse(window.recovery.save_result())
            self.assertEqual(store.data['recovery'], {'unknown': 'preserve'})
            window.recovery.record = None
            window.close()
