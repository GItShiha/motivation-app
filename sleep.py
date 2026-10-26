"""Self-reported sleep periods, conservative daily aggregation and paired statistics."""
from copy import deepcopy
from datetime import datetime, date, timedelta
import math
import uuid
from wellbeing import entries


def optional_score(value):
    return value is None or (type(value) is int and 0 <= value <= 10)


def validate_period(value):
    bed = datetime.fromisoformat(value['bed'])
    wake = datetime.fromisoformat(value['wake'])
    onset = datetime.fromisoformat(value['onset']) if value.get('onset') else None
    for stamp in (bed, wake, onset):
        if stamp is not None and stamp.tzinfo is None:
            raise ValueError('У времени должен быть указан часовой пояс.')
    if not 0 < wake.timestamp() - bed.timestamp() <= 72 * 3600:
        raise ValueError('Пробуждение должно быть позже отхода ко сну (не более 72 часов).')
    if onset and not bed.timestamp() <= onset.timestamp() <= wake.timestamp():
        raise ValueError('Засыпание должно быть между отходом ко сну и пробуждением.')
    date.fromisoformat(value['day'])
    for key in ('quality', 'energy', 'sleepiness'):
        if not optional_score(value.get(key)):
            raise ValueError('Оценки должны быть от 0 до 10 либо пропущены.')
    if value.get('awakenings') is not None and (type(value['awakenings']) is not int or not 0 <= value['awakenings'] <= 100):
        raise ValueError('Неверное количество пробуждений.')
    if not isinstance(value.get('note', ''), str):
        raise ValueError('Неверный комментарий.')
    return bed, onset, wake


def duration(period):
    _, onset, wake = validate_period(period)
    return (wake.timestamp() - onset.timestamp()) / 3600 if onset is not None else None


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def clock_mean(hours):
    if not hours:
        return None
    x = mean([math.cos(h / 24 * math.tau) for h in hours])
    y = mean([math.sin(h / 24 * math.tau) for h in hours])
    if math.hypot(x, y) < 1e-8:
        return None
    return (math.atan2(y, x) / math.tau * 24) % 24


def hour(stamp):
    stamp = datetime.fromisoformat(stamp)
    return stamp.hour + stamp.minute / 60


def daily(periods):
    groups = {}
    for p in periods:
        groups.setdefault(p['day'], []).append(p)
    result = {}
    for day, rows in groups.items():
        durations = [duration(r) for r in rows]
        result[day] = {'hours': sum(durations) if all(v is not None for v in durations) else None,
                       'quality': mean([r.get('quality') for r in rows]), 'energy': mean([r.get('energy') for r in rows]),
                       'onset': clock_mean([hour(r['onset']) for r in rows if r.get('onset')]),
                       'wake': clock_mean([hour(r['wake']) for r in rows]), 'periods': len(rows)}
    return result


def correlation(pairs, minimum=10):
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    if len(pairs) < minimum:
        return None, len(pairs)
    a, b = zip(*pairs)
    ma, mb = mean(a), mean(b)
    denominator = math.sqrt(sum((x - ma)**2 for x in a) * sum((y - mb)**2 for y in b))
    return (sum((x - ma) * (y - mb) for x, y in pairs) / denominator if denominator else None), len(pairs)


def analytics(periods, wellbeing, start, end):
    days = {d: v for d, v in daily(periods).items() if start <= date.fromisoformat(d) <= end}
    mood = {d.isoformat(): v['mood'] for d, v in entries(wellbeing).items()}
    return {'days': len(days), 'periods': sum(v['periods'] for v in days.values()),
            'hours': mean([v['hours'] for v in days.values()]), 'duration_days': sum(v['hours'] is not None for v in days.values()),
            'quality': mean([v['quality'] for v in days.values()]), 'mood': mean([mood.get(d) for d in days]),
            'onset': clock_mean([v['onset'] for v in days.values() if v['onset'] is not None]),
            'wake': clock_mean([v['wake'] for v in days.values() if v['wake'] is not None]),
            'quality_relation': correlation([(v['quality'], mood.get(d)) for d, v in days.items()]),
            'duration_relation': correlation([(v['hours'], mood.get(d)) for d, v in days.items()])}


class SleepLedger:
    def __init__(self, store, now=None):
        self.store = store
        self.now = now or (lambda: datetime.now().astimezone())
        raw = store.data.get('sleep', {'version': 1, 'periods': [], 'thoughts': [], 'ritual': [], 'ritual_marks': {}, 'practice': []})
        if not isinstance(raw, dict) or type(raw.get('version')) is not int or raw['version'] != 1 or any(not isinstance(raw.get(k), list) for k in ('periods', 'thoughts', 'ritual', 'practice')) or not isinstance(raw.get('ritual_marks'), dict):
            raise ValueError('Неверный формат дневника сна; данные не изменены.')
        self.data = deepcopy(raw)
        ids = set()
        for p in self.data['periods']:
            validate_period(p)
            if not isinstance(p.get('id'), str) or p['id'] in ids:
                raise ValueError('Неверный идентификатор периода сна.')
            ids.add(p['id'])
        for day, marks in self.data['ritual_marks'].items():
            date.fromisoformat(day)
            if not isinstance(marks, dict) or any(not isinstance(k, str) or type(v) is not bool for k, v in marks.items()):
                raise ValueError('Неверные отметки вечернего ритуала.')
        for key in ('thoughts', 'ritual'):
            for item in self.data[key]:
                if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not isinstance(item.get('text'), str) or not isinstance(item.get('at', ''), str):
                    raise ValueError('Неверный формат записей подготовки ко сну.')

    def transaction(self, action):
        previous = deepcopy(self.data)
        existed, old = 'sleep' in self.store.data, deepcopy(self.store.data.get('sleep'))
        try:
            result = action()
            self.store.data['sleep'] = self.data
            self.store.save()
            return result
        except Exception:
            self.data = previous
            if existed:
                self.store.data['sleep'] = old
            else:
                self.store.data.pop('sleep', None)
            raise

    def save_period(self, value, pid=None):
        bed, _, wake = validate_period(value)
        if wake.timestamp() > self.now().timestamp() or date.fromisoformat(value['day']) > self.now().date():
            raise ValueError('Запись о завершённом сне не может относиться к будущему.')
        for p in self.data['periods']:
            if p['id'] != pid and max(bed.timestamp(), datetime.fromisoformat(p['bed']).timestamp()) < min(wake.timestamp(), datetime.fromisoformat(p['wake']).timestamp()):
                raise ValueError('Период пересекается с уже сохранённой записью.')
        if pid is not None and not any(p['id'] == pid for p in self.data['periods']):
            raise ValueError('Редактируемая запись не найдена.')
        def change():
            record = dict(next((p for p in self.data['periods'] if p['id'] == pid), {}))
            record.update(deepcopy(value), id=pid or uuid.uuid4().hex)
            self.data['periods'] = [p for p in self.data['periods'] if p['id'] != pid] + [record]
            return record['id']
        return self.transaction(change)

    def delete(self, collection, item_id):
        if collection not in ('periods', 'thoughts', 'ritual'):
            raise ValueError('Неверная коллекция.')
        self.transaction(lambda: self.data.update({collection: [p for p in self.data[collection] if p['id'] != item_id]}))

    def add_text(self, collection, value):
        if collection not in ('thoughts', 'ritual') or not value.strip():
            raise ValueError('Введите текст.')
        def change():
            self.data[collection].append({'id': uuid.uuid4().hex, 'text': value.strip(), 'at': self.now().isoformat()})
            if collection == 'thoughts':
                self.data['thought_draft'] = ''
        self.transaction(change)

    def ritual_mark(self, day, rid, done):
        def change():
            marks = self.data['ritual_marks'].setdefault(day.isoformat(), {})
            marks[rid] = bool(done)
        self.transaction(change)

    def practice(self, kind, seconds, completed):
        self.transaction(lambda: self.data['practice'].append({'kind': kind, 'seconds': seconds, 'completed': completed, 'at': self.now().isoformat()}))
