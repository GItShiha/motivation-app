"""Optional evening practices and a local sleep diary, without diagnoses."""
from datetime import date, datetime, timedelta
import calendar as month_calendar
import time
from PySide6.QtCore import QDate, QDateTime, Qt, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QComboBox,
    QSpinBox, QCheckBox, QLineEdit, QTextEdit, QDateTimeEdit, QDateEdit, QCalendarWidget,
    QApplication, QMessageBox)
from sleep import SleepLedger, daily, analytics, duration
from wellbeing import entries
from wellbeing_ui import CalendarNavigation
from recovery import ExerciseTimer
from recovery_ui import Breath
from tickets_ui import text, button


class SleepChart(QWidget):
    def __init__(self, timing=False):
        super().__init__()
        self.timing = timing
        self.rows = []
        self.setMinimumHeight(210)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, width, height = 36, 15, max(1, self.width() - 78), max(1, self.height() - 42)
        hours_max = max(24, max((r.get('hours') or 0 for r in self.rows), default=0))
        for frac in (0, .5, 1):
            y = top + height * (1 - frac)
            p.setPen(QColor('#5a6273'))
            p.drawLine(left, int(y), left + width, int(y))
            p.drawText(1, int(y + 5), str(int(frac * (24 if self.timing else 10))))
            if not self.timing:
                p.drawText(left + width + 5, int(y + 5), str(round(frac * hours_max)))
        series = [('onset', '#b6a8ff', 24), ('wake', '#72c8ba', 24)] if self.timing else [('quality', '#b6a8ff', 10), ('mood', '#72c8ba', 10), ('hours', '#e8bf7a', hours_max)]
        for key, color, maximum in series:
            previous = None
            for i, row in enumerate(self.rows):
                value = row.get(key)
                if value is None:
                    previous = None
                    continue
                point = QPointF(left + width * i / max(1, len(self.rows) - 1), top + height * (1 - min(value, maximum) / maximum))
                p.setPen(QPen(QColor(color), 2))
                p.setBrush(QColor(color))
                if previous is not None:
                    p.drawLine(previous, point)
                p.drawEllipse(point, 3, 3)
                previous = point
        p.setPen(QColor('#939daf'))
        for i, row in enumerate(self.rows):
            if i % max(1, len(self.rows) // 6) == 0 or i == len(self.rows) - 1:
                p.drawText(int(left + width * i / max(1, len(self.rows) - 1)) - 15, top + height + 22, row['day'][8:10])


class SleepPractice(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.exercise = None
        self.step_index = 0
        lay = QVBoxLayout(self)
        lay.addWidget(text('Все практики добровольны. Можно выбрать одну, закончить раньше или ничего не выполнять. При дискомфорте или головокружении прекратите упражнение.'))
        self.kind = QComboBox()
        self.kind.addItems(['Спокойное дыхание', 'Постепенное расслабление мышц'])
        lay.addWidget(self.kind)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 30)
        self.minutes.setValue(3)
        self.minutes.setSuffix(' мин')
        lay.addWidget(self.minutes)
        self.tempo = QComboBox()
        for title, value in (('Вдох 4 с · выдох 6 с', (4, 6)), ('Вдох 3 с · выдох 4 с', (3, 4)), ('Вдох 5 с · выдох 6 с', (5, 6))):
            self.tempo.addItem(title, value)
        lay.addWidget(self.tempo)
        self.sound = QCheckBox('Тихий сигнал по завершении (с общей громкостью)')
        self.sound.setChecked(page.ledger.data.get('practice_sound', False) is True)
        self.sound.toggled.connect(lambda v: page.act(lambda: page.ledger.transaction(lambda: page.ledger.data.update(practice_sound=v)), refresh=False))
        lay.addWidget(self.sound)
        self.clock = text('')
        self.clock.setObjectName('section')
        lay.addWidget(self.clock)
        self.breath = Breath()
        self.breath.hide()
        lay.addWidget(self.breath)
        self.step = text('Дышите мягко, без задержек и форсированных глубоких вдохов. При боли или дискомфорте напряжение мышц нужно пропустить.')
        lay.addWidget(self.step)
        self.start_button = button('Начать практику', self.start)
        lay.addWidget(self.start_button)
        lay.addWidget(button('Следующая группа мышц', self.next_step))
        lay.addWidget(button('Закончить досрочно / отменить', lambda: self.finish(False)))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.ritual_day = date.today()
        self.kind.currentIndexChanged.connect(lambda: self.tempo.setVisible(self.kind.currentIndex() == 0))
        self.tempo.currentIndexChanged.connect(self.change_tempo)
        lay.addWidget(text('Выгрузка мыслей: запишите то, что хочется оставить до завтра.'))
        self.thought = QTextEdit()
        self.thought.setMaximumHeight(110)
        self.thought.setPlainText(page.ledger.data.get('thought_draft', '') if isinstance(page.ledger.data.get('thought_draft', ''), str) else '')
        self.thought.textChanged.connect(lambda: page.act(lambda: page.ledger.transaction(lambda: page.ledger.data.update(thought_draft=self.thought.toPlainText())), refresh=False))
        lay.addWidget(self.thought)
        lay.addWidget(button('Сохранить мысли', self.save_thought))
        self.thought_list = QVBoxLayout()
        lay.addLayout(self.thought_list)
        lay.addWidget(text('Мой вечерний ритуал · отметки на сегодня'))
        self.ritual = QLineEdit()
        self.ritual.setPlaceholderText('Одно спокойное действие перед сном')
        lay.addWidget(self.ritual)
        lay.addWidget(button('Добавить действие ритуала', self.add_ritual))
        self.ritual_list = QVBoxLayout()
        lay.addLayout(self.ritual_list)
        self.render_texts()

    def change_tempo(self):
        self.breath.inhale, self.breath.exhale = self.tempo.currentData()
        self.origin = time.monotonic()

    def start(self):
        w = self.page.window
        if self.exercise is not None or w.remaining or w.recovery.exercise is not None:
            self.page.status.setText('Сначала завершите текущую сессию или упражнение.')
            return
        self.timer.start(40)
        self.exercise = ExerciseTimer(self.minutes.value() * 60)
        self.step_index = 0
        self.active_kind = self.kind.currentIndex()
        self.kind.setEnabled(False)
        self.minutes.setEnabled(False)
        self.start_button.setEnabled(False)
        self.breath.setVisible(self.active_kind == 0)
        self.change_tempo()
        self.update_step()
        self.tick()

    def update_step(self):
        steps = ['Устройтесь удобно. Дышите мягко, без задержек; не пытайтесь дышать глубже обычного.', 'Кисти и предплечья: можно слегка напрячь, затем отпустить напряжение. При боли пропустите напряжение.', 'Плечи и лицо: мягко отпустите напряжение, не сжимая челюсти.', 'Живот и спина: расслабьте доступные мышцы, не прогибайтесь через дискомфорт.', 'Ноги и стопы: мягко отпустите напряжение. Можно только наблюдать ощущения.', 'Почувствуйте опору и спокойно отдохните. Продолжать необязательно.']
        self.step.setText(steps[0] if self.active_kind == 0 else steps[min(self.step_index + 1, len(steps) - 1)])

    def next_step(self):
        if self.exercise is not None:
            self.step_index += 1
            self.update_step()

    def tick(self):
        if self.ritual_day != date.today():
            self.ritual_day = date.today()
            self.render_texts()
        if self.exercise is None:
            return
        value = self.exercise.remaining
        self.clock.setText(f'{value // 60:02}:{value % 60:02}')
        self.breath.phase = time.monotonic() - self.origin
        self.breath.update()
        if not value:
            self.finish(True)

    def finish(self, completed):
        if self.exercise is None:
            return True
        seconds = round(self.exercise.elapsed, 2)
        if not self.page.act(lambda: self.page.ledger.practice(self.kind.itemText(self.active_kind), seconds, completed), refresh=False):
            self.timer.stop()
            return False
        self.exercise = None
        self.timer.start(1000)
        self.kind.setEnabled(True)
        self.minutes.setEnabled(True)
        self.start_button.setEnabled(True)
        self.breath.hide()
        self.clock.setText('Практика завершена.' if completed else 'Практика остановлена. Можно отдохнуть без упражнения.')
        if completed:
            if self.sound.isChecked():
                self.page.window.sounds.play('sleep')
            QApplication.alert(self.page.window, 0)
        return True

    def save_thought(self):
        if self.page.act(lambda: self.page.ledger.add_text('thoughts', self.thought.toPlainText()), refresh=False):
            self.thought.blockSignals(True)
            self.thought.clear()
            self.thought.blockSignals(False)
            self.render_texts()

    def add_ritual(self):
        if self.page.act(lambda: self.page.ledger.add_text('ritual', self.ritual.text()), refresh=False):
            self.ritual.clear()
            self.render_texts()

    def remove_text(self, collection, rid):
        if self.page.act(lambda: self.page.ledger.delete(collection, rid), refresh=False):
            self.render_texts()

    def mark_ritual(self, rid, value):
        if not self.page.act(lambda: self.page.ledger.ritual_mark(date.today(), rid, value), refresh=False):
            self.render_texts()

    def render_texts(self):
        for layout in (self.thought_list, self.ritual_list):
            while layout.count():
                w = layout.takeAt(0).widget()
                w.hide()
                w.deleteLater()
        for thought in reversed(self.page.ledger.data['thoughts']):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.addWidget(text(thought.get('at', '') + '\n' + thought['text']))
            lay.addWidget(button('Удалить запись мыслей', lambda checked=False, rid=thought['id']: self.remove_text('thoughts', rid)))
            self.thought_list.addWidget(box)
        for item in self.page.ledger.data['ritual']:
            box = QWidget()
            lay = QHBoxLayout(box)
            check = QCheckBox(item['text'])
            check.setChecked(self.page.ledger.data['ritual_marks'].get(date.today().isoformat(), {}).get(item['id'], False) is True)
            check.toggled.connect(lambda value, rid=item['id']: self.mark_ritual(rid, value))
            lay.addWidget(check)
            lay.addWidget(button('Удалить', lambda checked=False, rid=item['id']: self.remove_text('ritual', rid)))
            self.ritual_list.addWidget(box)


class SleepPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.editing = None
        root = QVBoxLayout(self)
        self.status = text()
        root.addWidget(self.status)
        try:
            self.ledger = SleepLedger(window.store)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            self.ledger = None
            root.addWidget(text('Дневник сна недоступен; исходные данные не изменены. ' + str(exc)))
            return
        tabs = QTabWidget()
        root.addWidget(tabs)
        self.practice = SleepPractice(self)
        tabs.addTab(self.practice, 'Подготовка ко сну')
        diary = QWidget()
        lay = QVBoxLayout(diary)
        tabs.addTab(diary, 'Дневник и аналитика')
        lay.addWidget(text('Это приблизительные самооценки, а не медицинские измерения. Несколько периодов сна за сутки сохраняются отдельно.'))
        self.form_toggle = QCheckBox('Добавить / редактировать период сна')
        lay.addWidget(self.form_toggle)
        self.form = QWidget()
        form = QVBoxLayout(self.form)
        self.form.hide()
        self.form_toggle.toggled.connect(self.form.setVisible)
        lay.addWidget(self.form)
        self.bed = self.datetime_field(form, 'Отход ко сну')
        self.known_onset = QCheckBox('Указать приблизительное время засыпания')
        self.known_onset.setChecked(True)
        form.addWidget(self.known_onset)
        self.onset = self.datetime_field(form, 'Засыпание')
        self.known_onset.toggled.connect(self.onset.setEnabled)
        self.wake = self.datetime_field(form, 'Пробуждение')
        self.custom_day = QCheckBox('Другой день связи с самочувствием (нестандартный режим)')
        form.addWidget(self.custom_day)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setDisplayFormat('dd.MM.yyyy')
        self.day.setEnabled(False)
        self.custom_day.toggled.connect(self.day.setEnabled)
        self.wake.dateTimeChanged.connect(lambda dt: self.day.setDate(dt.date()) if not self.custom_day.isChecked() else None)
        form.addWidget(self.day)
        self.quality = self.score_field(form, 'Качество сна: 0 — очень плохое, 10 — отличное')
        self.energy = self.score_field(form, 'Утренняя бодрость: 0 — нет, 10 — высокая')
        self.sleepiness = self.score_field(form, 'Дневная сонливость: 0 — нет, 10 — сильная (необязательно)')
        self.awakenings = self.score_field(form, 'Ночные пробуждения (необязательно)', maximum=100)
        self.note = QTextEdit()
        self.note.setMaximumHeight(90)
        self.note.setPlaceholderText('Комментарий')
        form.addWidget(self.note)
        form.addWidget(button('Сохранить период сна', self.save_form))
        form.addWidget(button('Новый период (не менять выбранный)', self.new_period))
        form.addWidget(button('Удалить выбранный период', self.delete_period))
        self.calendar = QCalendarWidget()
        from PySide6.QtCore import QLocale
        from PySide6.QtGui import QTextCharFormat
        self.calendar.setLocale(QLocale('ru_RU'))
        self.calendar.setMinimumDate(QDate(1, 1, 1))
        self.calendar.setMaximumDate(QDate.currentDate())
        self.calendar.setNavigationBarVisible(False)
        self.calendar.setMinimumHeight(300)
        header = QTextCharFormat()
        header.setForeground(QColor('#e8eaf0'))
        header.setBackground(QColor('#252a35'))
        self.calendar.setHeaderTextFormat(header)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, header)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, header)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.nav = CalendarNavigation(self.calendar)
        lay.addWidget(self.nav)
        lay.addWidget(self.calendar)
        lay.addWidget(text('Сиреневым отмечены дни с записями сна. По умолчанию это день пробуждения.'))
        self.records = QComboBox()
        self.records.addItem('Выберите период для просмотра', None)
        self.records.activated.connect(self.load_period)
        lay.addWidget(self.records)
        self.day_info = text()
        lay.addWidget(self.day_info)
        self.month_info = text()
        lay.addWidget(self.month_info)
        self.range = QComboBox()
        self.range.addItem('7 дней до выбранной даты включительно', 7)
        self.range.addItem('30 дней до выбранной даты включительно', 30)
        self.range.addItem('Выбранный месяц', 0)
        self.range.setCurrentIndex(1)
        lay.addWidget(self.range)
        self.chart = SleepChart()
        lay.addWidget(self.chart)
        lay.addWidget(text('Сиреневый — качество сна, зелёный — самочувствие (левая шкала 0–10); жёлтый — длительность (правая шкала, часы). Пропуски — разрывы.'))
        self.timing_chart = SleepChart(timing=True)
        lay.addWidget(self.timing_chart)
        lay.addWidget(text('Время суток 0–24: сиреневый — засыпание, зелёный — пробуждение. Переход через полночь может выглядеть скачком; среднее время рассчитано по круговой шкале.'))
        self.relation = text()
        lay.addWidget(self.relation)
        lay.addWidget(text('Статистическая связь не доказывает причинно-следственную зависимость. Дневник не ставит диагнозы. Для нескольких периодов — сумма известных длительностей только при наличии всех; оценки усредняются по периодам, затем по дням.'))
        self.calendar.selectionChanged.connect(self.render)
        self.calendar.currentPageChanged.connect(self.render)
        self.range.currentIndexChanged.connect(self.render)
        self.new_period()
        self.render()

    def datetime_field(self, lay, title):
        lay.addWidget(text(title))
        field = QDateTimeEdit(QDateTime.currentDateTime())
        field.setDisplayFormat('dd.MM.yyyy HH:mm')
        lay.addWidget(field)
        return field

    def score_field(self, lay, title, maximum=10):
        lay.addWidget(text(title))
        field = QSpinBox()
        field.setRange(-1, maximum)
        field.setSpecialValueText('Не указано')
        field.setValue(-1)
        lay.addWidget(field)
        return field

    def act(self, action, refresh=True):
        try:
            result = action()
        except (OSError, ValueError) as exc:
            self.status.setText('Не удалось сохранить: ' + str(exc))
            return False
        self.status.setText('Сохранено локально.')
        if refresh:
            self.render()
        return True

    def new_period(self):
        self.editing = None
        wake = datetime.now().astimezone().replace(second=0, microsecond=0)
        bed = wake - timedelta(hours=8)
        self.bed.setDateTime(QDateTime(bed))
        self.onset.setDateTime(QDateTime(bed + timedelta(minutes=20)))
        self.wake.setDateTime(QDateTime(wake))
        self.known_onset.setChecked(True)
        self.custom_day.setChecked(False)
        self.day.setDate(self.wake.date())
        self.note.clear()
        for score in (self.quality, self.energy, self.sleepiness, self.awakenings):
            score.setValue(-1)

    def save_form(self):
        value = {'bed': self.bed.dateTime().toPython().astimezone().isoformat(), 'wake': self.wake.dateTime().toPython().astimezone().isoformat(),
                 'onset': self.onset.dateTime().toPython().astimezone().isoformat() if self.known_onset.isChecked() else None,
                 'day': (self.day.date() if self.custom_day.isChecked() else self.wake.date()).toString('yyyy-MM-dd'), 'note': self.note.toPlainText()}
        for key, field in (('quality', self.quality), ('energy', self.energy), ('sleepiness', self.sleepiness), ('awakenings', self.awakenings)):
            value[key] = field.value() if field.value() >= 0 else None
        def save():
            self.editing = self.ledger.save_period(value, self.editing)
        if self.act(save):
            self.calendar.setSelectedDate(QDate.fromString(value['day'], 'yyyy-MM-dd'))

    def load_period(self, index):
        pid = self.records.itemData(index)
        if not pid:
            return
        record = next(p for p in self.ledger.data['periods'] if p['id'] == pid)
        self.editing = pid
        self.bed.setDateTime(QDateTime(datetime.fromisoformat(record['bed']).astimezone()))
        self.wake.setDateTime(QDateTime(datetime.fromisoformat(record['wake']).astimezone()))
        self.known_onset.setChecked(bool(record.get('onset')))
        if record.get('onset'):
            self.onset.setDateTime(QDateTime(datetime.fromisoformat(record['onset']).astimezone()))
        self.custom_day.setChecked(record['day'] != self.wake.date().toString('yyyy-MM-dd'))
        self.day.setDate(QDate.fromString(record['day'], 'yyyy-MM-dd'))
        for key, field in (('quality', self.quality), ('energy', self.energy), ('sleepiness', self.sleepiness), ('awakenings', self.awakenings)):
            field.setValue(record[key] if record.get(key) is not None else -1)
        self.note.setPlainText(record.get('note', ''))
        self.form_toggle.setChecked(True)

    def delete_period(self):
        if not self.editing:
            return
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle('Удалить период сна?')
        dialog.setText('Будет удалён только выбранный период.')
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Yes).setText('Удалить')
        dialog.button(QMessageBox.StandardButton.Cancel).setText('Отмена')
        pid = self.editing
        dialog.finished.connect(lambda result: self.new_period() if result == QMessageBox.StandardButton.Yes and self.act(lambda: self.ledger.delete('periods', pid)) else None)
        self.dialog = dialog
        dialog.open()

    def render(self, *args):
        from PySide6.QtGui import QTextCharFormat
        periods = self.ledger.data['periods']
        days = daily(periods)
        mood = {d.isoformat(): v['mood'] for d, v in entries(self.window.store.data['entries']).items()}
        selected = self.calendar.selectedDate().toPython()
        self.calendar.setMaximumDate(QDate.currentDate())
        self.records.clear()
        self.records.addItem('Выберите период для просмотра/редактирования', None)
        for p in sorted(periods, key=lambda p: p['wake']):
            if p['day'] == selected.isoformat():
                hours = duration(p)
                self.records.addItem(p['bed'][:16] + ' → ' + p['wake'][:16] + (f' · {hours:.2f} ч' if hours is not None else ' · длительность неизвестна'), p['id'])
        def number(value):
            return '—' if value is None else f'{value:.2f}'
        row = days.get(selected.isoformat(), {})
        self.day_info.setText(f"{selected:%d.%m.%Y}: периодов {row.get('periods', 0)}, сон {number(row.get('hours'))} ч, качество {number(row.get('quality'))}, самочувствие {number(mood.get(selected.isoformat()))}")
        year, month = self.calendar.yearShown(), self.calendar.monthShown()
        start, end = date(year, month, 1), date(year, month, month_calendar.monthrange(year, month)[1])
        stats = analytics(periods, self.window.store.data['entries'], start, end)
        def clock(value):
            if value is None:
                return '—'
            minutes = round(value * 60) % 1440
            return f'{minutes // 60:02}:{minutes % 60:02}'
        self.month_info.setText(f"Месяц {month:02}.{year}: дней с записями {stats['days']}, периодов {stats['periods']}, средний сон {number(stats['hours'])} ч (дней с полной длительностью {stats['duration_days']}), качество {number(stats['quality'])}, самочувствие в связанные дни {number(stats['mood'])}.\nСреднее засыпание {clock(stats['onset'])}, пробуждение {clock(stats['wake'])}.")
        count = self.range.currentData()
        chart_start, chart_end = (max(date.min, selected - timedelta(days=min(count - 1, selected.toordinal() - 1))), selected) if count else (start, min(end, date.today()))
        rows = []
        day = chart_start
        while day <= chart_end:
            rows.append(dict(days.get(day.isoformat(), {}), day=day.isoformat(), mood=mood.get(day.isoformat())))
            day += timedelta(days=1)
        self.chart.rows = self.timing_chart.rows = rows
        self.chart.update()
        self.timing_chart.update()
        lines = ['Связь за выбранный месяц (минимум 10 парных дней):']
        for title, (r, n) in (('Качество ↔ самочувствие', stats['quality_relation']), ('Длительность ↔ самочувствие', stats['duration_relation'])):
            lines.append(title + (f': r={r:+.2f}, n={n}' if r is not None else f': недостаточно данных или разнообразия, n={n}'))
        self.relation.setText('\n'.join(lines))
        fmt = QTextCharFormat()
        fmt.setBackground(QColor('#4b426b'))
        # Only refresh the visible month; old formats outside it are harmless cached marks.
        for d in range(1, month_calendar.monthrange(year, month)[1] + 1):
            day = date(year, month, d)
            self.calendar.setDateTextFormat(QDate(year, month, d), fmt if day.isoformat() in days else QTextCharFormat())
        self.nav.sync()

    def shutdown(self):
        if self.ledger is None:
            return True
        if not self.practice.finish(False):
            return False
        self.practice.timer.stop()
        return True
