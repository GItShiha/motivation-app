"""Manual shift ledger with atomic transactions and durable reminder watermarks."""
from copy import deepcopy
from datetime import datetime, date, timedelta
import uuid

DEFAULTS = {'goal': 262, 'interval': 50, 'break_minutes': 5, 'reminders': True, 'track_excess': True}


def number(value, minimum=0):
    return type(value) is int and minimum <= value <= 1000000


class TicketLedger:
    def __init__(self, store, now=None):
        self.store = store
        self.now = now or (lambda: datetime.now().astimezone())
        raw = store.data.get('tickets', {'version': 1, 'settings': dict(DEFAULTS), 'shifts': [], 'active': None, 'window': {}})
        if not isinstance(raw, dict) or raw.get('version') != 1 or not isinstance(raw.get('settings'), dict) or not isinstance(raw.get('shifts'), list) or not isinstance(raw.get('window', {}), dict):
            raise ValueError('Неверный формат истории тикетов. Данные не изменены.')
        self.data = deepcopy(raw)
        self.validate_config(self.data['settings'])
        ids = set()
        for shift in self.data['shifts']:
            if not isinstance(shift, dict) or not isinstance(shift.get('id'), str) or shift['id'] in ids:
                raise ValueError('Повреждена история смен. Данные не изменены.')
            ids.add(shift['id'])
            self.validate_config(shift)
            for key in ('count', 'break_high'):
                if not number(shift.get(key)):
                    raise ValueError('Неверное значение счётчика.')
            date.fromisoformat(shift['date'])
            if not isinstance(shift.get('breaks'), list) or not isinstance(shift.get('goals_notified'), list):
                raise ValueError('Неверная история уведомлений.')
            datetime.fromisoformat(shift['started_at'])
            if shift.get('ended_at') is not None:
                datetime.fromisoformat(shift['ended_at'])
            self.recalculate(shift)
            for event in shift['breaks']:
                if not isinstance(event, dict) or event.get('state') not in ('pending', 'later', 'skipped', 'started') or not number(event.get('threshold')):
                    raise ValueError('Неверная история перерывов.')
        if self.data.get('active') is not None and self.data['active'] not in ids:
            raise ValueError('Не найдена активная смена.')

    @staticmethod
    def validate_config(config):
        for key in ('goal', 'interval', 'break_minutes'):
            if not number(config.get(key), 1):
                raise ValueError('Норма, интервал и длительность должны быть положительными числами.')
        for key in ('reminders', 'track_excess'):
            if type(config.get(key)) is not bool:
                raise ValueError('Неверные настройки счётчика.')

    @property
    def active(self):
        return next((s for s in self.data['shifts'] if s['id'] == self.data.get('active')), None)

    def transaction(self, action):
        previous = deepcopy(self.data)
        existed = 'tickets' in self.store.data
        old = deepcopy(self.store.data.get('tickets'))
        try:
            result = action()
            self.store.data['tickets'] = self.data
            self.store.save()
            return result
        except Exception:
            self.data = previous
            if existed:
                self.store.data['tickets'] = old
            else:
                self.store.data.pop('tickets', None)
            raise

    def configure(self, config):
        self.validate_config(config)
        def change():
            self.data['settings'] = dict(config)
            if self.active:
                self.active.update(config)
                self.recalculate(self.active)
        self.transaction(change)

    @staticmethod
    def recalculate(shift):
        shift['credited'] = min(shift['count'], shift['goal'])
        shift['percent'] = 100 * shift['credited'] / shift['goal']

    def start(self, initial=0):
        if not number(initial):
            raise ValueError('Неверное начальное количество.')
        def change():
            if self.active:
                self.active['ended_at'] = self.now().isoformat()
            config = self.data['settings']
            started = self.now()
            shift = dict(config, id=uuid.uuid4().hex, date=started.date().isoformat(), started_at=started.isoformat(), ended_at=None, count=initial, break_high=initial, breaks=[], goals_notified=[config['goal']] if initial >= config['goal'] else [])
            self.recalculate(shift)
            self.data['shifts'].append(shift)
            self.data['active'] = shift['id']
        self.transaction(change)

    def end(self):
        def change():
            if self.active:
                self.active['ended_at'] = self.now().isoformat()
                self.data['active'] = None
        self.transaction(change)

    def set_count(self, value):
        if not number(value):
            raise ValueError('Количество должно быть от 0 до 1 000 000.')
        def change():
            shift = self.active
            if shift is None:
                raise ValueError('Начните смену.')
            old, notices = shift['count'], []
            if old < shift['goal'] <= value and shift['goal'] not in shift['goals_notified']:
                shift['goals_notified'].append(shift['goal'])
                notices.append('goal')
            threshold = (value // shift['interval']) * shift['interval']
            if threshold > max(old, shift['break_high']) and shift['reminders']:
                shift['breaks'].append({'at': self.now().isoformat(), 'threshold': threshold, 'state': 'pending'})
                notices.append('break')
            shift['break_high'] = max(shift['break_high'], value)
            shift['count'] = value
            self.recalculate(shift)
            return notices
        return self.transaction(change)

    def step(self, amount):
        if not self.active:
            raise ValueError('Начните смену.')
        value = max(0, min(1000000, self.active['count'] + amount))
        if amount > 0 and not self.active['track_excess'] and self.active['count'] >= self.active['goal']:
            return []
        return self.set_count(value)

    def mark_break(self, state):
        if state not in ('later', 'skipped', 'started'):
            raise ValueError('Неверная отметка перерыва.')
        def change():
            if self.active:
                for event in self.active['breaks']:
                    if event['state'] in ('pending', 'later'):
                        event['state'] = state
                        event['responded_at'] = self.now().isoformat()
        self.transaction(change)

    def window_settings(self, settings):
        self.transaction(lambda: self.data.update(window=dict(settings)))

    def statistics(self, days=None, month=False):
        today = self.now().date()
        rows = [s for s in self.data['shifts'] if (date.fromisoformat(s['date']).year, date.fromisoformat(s['date']).month) == (today.year, today.month)] if month else [s for s in self.data['shifts'] if today - timedelta(days=(days or 1) - 1) <= date.fromisoformat(s['date']) <= today]
        count = sum(s['count'] for s in rows)
        credited = sum(min(s['count'], s['goal']) for s in rows)
        goal = sum(s['goal'] for s in rows)
        return {'shifts': len(rows), 'count': count, 'credited': credited, 'percent': 100 * credited / goal if goal else None}
