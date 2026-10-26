"""Date-based wellbeing history, compatible with the original entries mapping."""
import calendar
from datetime import date

MONTHS = ('Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь')


def score(value):
    return type(value) is int and 0 <= value <= 10


def entries(raw, today=None):
    today = today or date.today()
    result = {}
    if not isinstance(raw, dict):
        return result
    for key, value in raw.items():
        try:
            day = date.fromisoformat(key)
            if day.isoformat() != key or day > today:
                continue
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and score(value.get('mood')):
            result[day] = value
    return result


def summary(records):
    values = [record['mood'] for record in records]
    return {'count': len(values), 'mean': sum(values) / len(values) if values else None,
            'best': max(values) if values else None, 'worst': min(values) if values else None}


def month_stats(raw, year, month, today=None):
    return summary(v for day, v in entries(raw, today).items() if day.year == year and day.month == month)


def year_stats(raw, year, today=None):
    return summary(v for day, v in entries(raw, today).items() if day.year == year)


def month_series(raw, year, month, today=None):
    valid = entries(raw, today)
    return [valid.get(date(year, month, d), {}).get('mood') for d in range(1, calendar.monthrange(year, month)[1] + 1)]


def change(raw, year, month, today=None, minimum=5):
    current = month_stats(raw, year, month, today)
    previous_year, previous_month = (year, month - 1) if month > 1 else (year - 1, 12)
    if previous_year < 1:
        return None
    previous = month_stats(raw, previous_year, previous_month, today)
    if min(current['count'], previous['count']) < minimum:
        return None
    return current['mean'] - previous['mean']
