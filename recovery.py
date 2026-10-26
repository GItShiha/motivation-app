"""Local recovery catalogue, transparent recommendations and subjective statistics."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import time

STATES = ['Умственная усталость', 'Сонливость', 'Стресс и раздражение', 'Нет желания начинать', 'Общее снижение энергии']
METRICS = {'focus': 'Концентрация', 'energy': 'Бодрость', 'fatigue': 'Усталость', 'readiness': 'Готовность начать'}

@dataclass(frozen=True)
class Method:
    key: str
    name: str
    minimum: int
    maximum: int
    mechanism: str
    steps: tuple[str, ...]
    caution: str
    states: tuple[int, ...]

METHODS = [
    Method('move', 'Активный перерыв', 3, 10, 'Движение после сидения может уменьшить субъективную усталость и повысить бодрость.', ('Встаньте из-за стола.', 'Пройдитесь, мягко разомните плечи и шею.', 'Смените положение тела и оцените готовность вернуться.'), 'Выбирайте комфортную нагрузку без боли; при ограничениях двигайтесь доступным способом.', (0, 1, 2, 4)),
    Method('rest', 'Отдых без экрана', 3, 10, 'Прекращение обработки информации может снизить ощущение усталости и напряжение.', ('Отойдите от компьютера.', 'Спокойно посидите или посмотрите вдаль.', 'Не заменяйте работу социальными сетями.'), 'Эффект индивидуален; перерыв не компенсирует хронический недосып.', (0, 2, 4)),
    Method('nap', 'Короткий дневной сон', 20, 30, 'Короткий сон может уменьшать сонливость и улучшать бдительность при недосыпе.', ('Подготовьте тихое место: около 5 минут.', 'Отведите до 20 минут на сон; таймер включает подготовку и пробуждение.', 'Оставьте около 5 минут, чтобы окончательно проснуться.'), 'Всего нужно около 30 минут. Возможна временная заторможенность; не приступайте сразу к опасной работе. Сон подходит не всем.', (1,)),
    Method('light', 'Дневной свет', 5, 15, 'Дневной свет может временно повышать бодрость и поддерживать циркадные ритмы.', ('Подойдите к окну или выйдите на улицу.', 'Побудьте при дневном свете в комфортных условиях.'), 'Не смотрите на солнце. Учитывайте погоду и чувствительность к свету.', (0, 1, 4)),
    Method('breath', 'Спокойное дыхание', 3, 5, 'Спокойное дыхание с немного удлинённым выдохом может уменьшать напряжение и стресс.', ('Устройтесь удобно.', 'Дышите мягко в комфортном темпе по подсказке.', 'Без задержек и форсированных глубоких вдохов.'), 'При головокружении прекратите упражнение и вернитесь к обычному дыханию.', (2,)),
    Method('water', 'Вода', 1, 3, 'Вода может помочь при жажде и недостатке жидкости.', ('Оцените, есть ли жажда.', 'При необходимости выпейте воды в комфортном количестве.'), 'Не универсальный стимулятор концентрации. Учитывайте индивидуальные ограничения жидкости.', (4,)),
    Method('snack', 'Лёгкий перекус', 5, 10, 'Устранение голода может убрать отвлекающий фактор.', ('Оцените наличие голода.', 'При необходимости выберите небольшой привычный перекус.'), 'Большие порции не являются способом быстрого повышения энергии. Учитывайте пищевые ограничения.', (4,)),
    Method('caffeine', 'Кофеин', 2, 5, 'Кофеин временно повышает бодрость; эффект обычно наступает в течение десятков минут.', ('При желании выберите кофе или чай.', 'Учтите переносимость, время суток и суммарное потребление.'), 'Время таймера — перерыв, а не ожидание эффекта. Возможны тревожность, сердцебиение и нарушение сна. Не заменяет сон; универсальной дозировки нет.', (1,)),
    Method('audio', 'Звуки природы или спокойная музыка', 3, 10, 'Комфортный звуковой фон может помогать расслабиться и переключиться.', ('Выберите собственный локальный аудиофайл, если хотите.', 'Включите его вручную с комфортной громкостью.', 'Спокойно отдохните.'), 'Влияние на концентрацию индивидуально. Звуки не включаются автоматически.', (2, 0)),
    Method('action', 'Правило одного действия', 1, 3, 'Уменьшение масштаба задачи может снизить сопротивление началу.', ('Выберите минимальное действие: например, откройте один тикет.', 'Выполните только его без обязательства продолжать.', 'Решите, делать ли следующий шаг.'), 'Это помощь с началом, а не замена отдыха при усталости.', (3,)),
    Method('plan', 'План возвращения к работе', 1, 2, 'Конкретный следующий шаг может облегчить возвращение после переключения внимания.', ('Запишите одно действие в поле плана.', 'При желании используйте существующий план «Если → то».', 'После перерыва вернитесь к записанному шагу.'), 'Выбирайте посильное действие; продолжать работу необязательно.', (3, 0)),
]
BY_KEY = {m.key: m for m in METHODS}

def valid_scores(value):
    return {k: v for k, v in value.items() if k in METRICS and type(v) is int and 0 <= v <= 10} if isinstance(value, dict) else {}

def delta(record):
    before, after = valid_scores(record.get('before')), valid_scores(record.get('after'))
    changes = [(after[k] - before[k]) * (-1 if k == 'fatigue' else 1) for k in before.keys() & after.keys()]
    return sum(changes) / len(changes) if changes else None

def history(data):
    raw = data.get('recovery', [])
    return [r for r in raw if isinstance(r, dict) and r.get('method') in BY_KEY] if isinstance(raw, list) else []

def statistics(records, days=None, state=None, now=None):
    now = now or datetime.now().astimezone()
    groups = {}
    for r in records:
        try:
            stamp = datetime.fromisoformat(r['started_at'])
            if stamp.tzinfo is None:
                stamp = stamp.astimezone()
            if stamp > now or (days and stamp < now - timedelta(days=days)):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if r.get('method') not in BY_KEY or (state is not None and r.get('state') != state):
            continue
        g = groups.setdefault(r['method'], {'uses': 0, 'changes': []})
        g['uses'] += 1
        d = delta(r)
        if r.get('status') == 'completed' and d is not None:
            g['changes'].append(d)
    return {key: {'uses': g['uses'], 'rated': len(g['changes']), 'mean': sum(g['changes']) / len(g['changes']) if g['changes'] else None, 'improved': sum(d > 0 for d in g['changes']) / len(g['changes']) if g['changes'] else None} for key, g in groups.items()}

def recommend(state, minutes, records=()):
    stats = statistics(records, state=state)
    eligible = [m for m in METHODS if state in m.states and (30 if m.key == 'nap' else m.minimum) <= minutes]
    # Personal ordering only after five completed paired observations for a method.
    eligible.sort(key=lambda m: -(stats.get(m.key, {}).get('mean') or 0) if stats.get(m.key, {}).get('rated', 0) >= 5 else 0)
    return eligible

class ExerciseTimer:
    def __init__(self, seconds, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.seconds = seconds
        self.deadline = self.started + seconds

    @property
    def remaining(self):
        return max(0, math.ceil(self.deadline - self.clock()))

    @property
    def elapsed(self):
        return max(0, min(self.seconds, self.clock() - self.started))
