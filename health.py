"""Local action schedules with immutable historical revisions and explicit marks."""
from copy import deepcopy
from datetime import date, datetime, timedelta, time
import uuid

KINDS = ('Лекарство', 'Процедура', 'Уход', 'Другое')


def validate_schedule(value):
    if not isinstance(value, dict) or not isinstance(value.get('name'), str) or not value['name'].strip():
        raise ValueError('Укажите название действия.')
    if value.get('kind') not in KINDS or not isinstance(value.get('description', ''), str):
        raise ValueError('Неверный тип или описание.')
    days = value.get('weekdays')
    if not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d <= 6 for d in days) or len(set(days)) != len(days):
        raise ValueError('Выберите дни недели.')
    count = value.get('count')
    if type(count) is not int or not 1 <= count <= 12:
        raise ValueError('Количество выполнений: от 1 до 12.')
    start = date.fromisoformat(value['start'])
    if value.get('end') and date.fromisoformat(value['end']) < start:
        raise ValueError('Окончание не может быть раньше начала.')
    times = value.get('times')
    if not isinstance(times, list) or len(times) not in (0, count):
        raise ValueError('Укажите время для каждого выполнения либо оставьте поле пустым.')
    for item in times:
        if not isinstance(item, str) or len(item) != 5 or time.fromisoformat(item).strftime('%H:%M') != item:
            raise ValueError('Время должно иметь вид ЧЧ:ММ.')
    if type(value.get('remind')) is not bool:
        raise ValueError('Неверная настройка напоминания.')


class HealthLedger:
    def __init__(self, store, now=None):
        self.store = store
        self.now = now or (lambda: datetime.now().astimezone())
        raw = store.data.get('health', {'version': 1, 'actions': [], 'marks': {}, 'notified': {}, 'reminders': False})
        if not isinstance(raw, dict) or type(raw.get('version')) is not int or raw['version'] != 1 or not isinstance(raw.get('actions'), list) or not isinstance(raw.get('marks'), dict) or not isinstance(raw.get('notified'), dict) or type(raw.get('reminders')) is not bool:
            raise ValueError('Неверный формат истории здоровья; данные не изменены.')
        self.data = deepcopy(raw)
        ids = set()
        for action in self.data['actions']:
            if not isinstance(action.get('id'), str) or action['id'] in ids or not isinstance(action.get('revisions'), list) or not action['revisions']:
                raise ValueError('Неверная история расписания.')
            ids.add(action['id'])
            dates = []
            for revision in action['revisions']:
                validate_schedule(revision)
                dates.append(date.fromisoformat(revision['effective']))
                if type(revision.get('archived', False)) is not bool:
                    raise ValueError('Неверная версия действия.')
            if dates != sorted(set(dates)):
                raise ValueError('Версии расписания не упорядочены.')
        for day, actions in self.data['marks'].items():
            date.fromisoformat(day)
            if not isinstance(actions, dict):
                raise ValueError('Неверный формат отметок.')
            for aid, slots in actions.items():
                if aid not in ids or not isinstance(slots, dict) or any(k not in {str(i) for i in range(12)} or not isinstance(v, dict) or v.get('state') not in ('done', 'skipped') for k, v in slots.items()):
                    raise ValueError('Неверные отметки выполнения.')

    def transaction(self, action):
        previous = deepcopy(self.data)
        existed, old = 'health' in self.store.data, deepcopy(self.store.data.get('health'))
        try:
            result = action()
            self.store.data['health'] = self.data
            self.store.save()
            return result
        except Exception:
            self.data = previous
            if existed:
                self.store.data['health'] = old
            else:
                self.store.data.pop('health', None)
            raise

    def add(self, schedule):
        validate_schedule(schedule)
        def change():
            aid = uuid.uuid4().hex
            self.data['actions'].append({'id': aid, 'revisions': [dict(deepcopy(schedule), effective=schedule['start'], archived=False)]})
            return aid
        return self.transaction(change)

    def revise(self, aid, schedule, effective=None, archived=False):
        validate_schedule(schedule)
        effective = effective or (self.now().date() + timedelta(days=1))
        if effective <= self.now().date():
            raise ValueError('Изменения существующего расписания действуют не раньше завтрашнего дня.')
        def change():
            action = self.action(aid)
            revision = dict(deepcopy(schedule), effective=effective.isoformat(), archived=archived)
            action['revisions'] = sorted([r for r in action['revisions'] if r['effective'] < revision['effective']] + [revision], key=lambda r: r['effective'])
        self.transaction(change)

    def action(self, aid):
        return next(a for a in self.data['actions'] if a['id'] == aid)

    def schedule(self, aid, day):
        revisions = [r for r in self.action(aid)['revisions'] if r['effective'] <= day.isoformat()]
        return revisions[-1] if revisions else None

    def planned(self, aid, day):
        s = self.schedule(aid, day)
        return bool(s and not s.get('archived') and s['start'] <= day.isoformat() and (not s.get('end') or day.isoformat() <= s['end']) and day.weekday() in s['weekdays'])

    def slots(self, day, aid=None):
        result = []
        for action in self.data['actions']:
            if aid is not None and action['id'] != aid:
                continue
            if not self.planned(action['id'], day):
                continue
            schedule = self.schedule(action['id'], day)
            marks = self.data['marks'].get(day.isoformat(), {}).get(action['id'], {})
            for slot in range(schedule['count']):
                result.append({'action': action['id'], 'slot': slot, 'schedule': schedule, 'time': schedule['times'][slot] if schedule['times'] else None, 'state': marks.get(str(slot), {}).get('state', 'unmarked')})
        return result

    def mark(self, day, aid, slot, state):
        if day > self.now().date() or state not in ('done', 'skipped', 'unmarked') or type(slot) is not int or not any(s['action'] == aid and s['slot'] == slot for s in self.slots(day)):
            raise ValueError('Отметка недоступна для этой даты или выполнения.')
        def change():
            slots = self.data['marks'].setdefault(day.isoformat(), {}).setdefault(aid, {})
            if state == 'unmarked':
                slots.pop(str(slot), None)
            else:
                slots[str(slot)] = {'state': state, 'at': self.now().isoformat()}
        self.transaction(change)

    def day_status(self, day):
        states = [s['state'] for s in self.slots(day)]
        if not states:
            return 'none'
        if all(s == 'done' for s in states):
            return 'full'
        if 'skipped' in states:
            return 'skipped'
        if 'done' in states:
            return 'partial'
        return 'empty'

    def statistics(self, start, end, aid=None):
        end = min(end, self.now().date())
        result = {'planned': 0, 'done': 0, 'skipped': 0, 'unmarked': 0, 'full_days': 0}
        day = start
        while day <= end:
            slots = self.slots(day, aid)
            result['planned'] += len(slots)
            for slot in slots:
                result[slot['state']] += 1
            if slots and all(s['state'] == 'done' for s in slots):
                result['full_days'] += 1
            day += timedelta(days=1)
        result['percent'] = 100 * result['done'] / result['planned'] if result['planned'] else None
        return result

    def reminders(self, enabled):
        self.transaction(lambda: self.data.update(reminders=bool(enabled)))

    def due(self):
        if not self.data['reminders']:
            return []
        now = self.now()
        day = now.date()
        due = [s for s in self.slots(day) if s['state'] == 'unmarked' and s['schedule']['remind'] and s['time'] and s['time'] <= now.strftime('%H:%M') and f"{day}:{s['action']}:{s['slot']}" not in self.data['notified']]
        if not due:
            return []
        def change():
            for slot in due:
                self.data['notified'][f"{day}:{slot['action']}:{slot['slot']}"] = now.isoformat()
            return due
        return self.transaction(change)
