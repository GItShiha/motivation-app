"""Russian calendar, historical editor and local charts; no extra dependencies."""
from datetime import date

from PySide6.QtCore import QDate, QLocale, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QTextCharFormat
from PySide6.QtWidgets import (QWidget, QCalendarWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QLabel, QSlider, QTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView)
from wellbeing import MONTHS, entries, score, month_stats, year_stats, month_series, change


def text(value):
    item = QLabel(value)
    item.setWordWrap(True)
    item.setTextFormat(Qt.TextFormat.PlainText)
    return item


def color(value):
    if value is None:
        return QColor('#252a35')
    return QColor.fromHsvF((value / 10) * .36, .5, .55)


class Calendar(QCalendarWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.setLocale(QLocale('ru_RU'))
        self.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setMinimumDate(QDate(1, 1, 1))
        self.setMaximumDate(QDate.currentDate())
        header = QTextCharFormat()
        header.setBackground(QColor('#252a35'))
        header.setForeground(QColor('#e8eaf0'))
        self.setHeaderTextFormat(header)
        for weekday in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.setWeekdayTextFormat(weekday, header)
        self.setNavigationBarVisible(False)
        self.setGridVisible(True)
        self.setMinimumHeight(340)
        self.records = entries(store.data['entries'])
        self.setAccessibleName('Календарь самочувствия')

    def reload(self):
        self.records = entries(self.store.data['entries'])
        self.setMaximumDate(QDate.currentDate())
        self.updateCells()

    def paintCell(self, painter, rect, day):
        if day.month() != self.monthShown() or day > self.maximumDate():
            super().paintCell(painter, rect, day)
            return
        value = self.records.get(day.toPython(), {}).get('mood')
        painter.save()
        painter.fillRect(rect.adjusted(1, 1, -1, -1), color(value))
        painter.setPen(QColor('#ffffff'))
        painter.drawText(rect.adjusted(3, 1, -3, -rect.height() // 2), Qt.AlignmentFlag.AlignCenter, str(day.day()))
        painter.drawText(rect.adjusted(2, rect.height() // 2, -2, -1), Qt.AlignmentFlag.AlignCenter, f'{value}/10' if value is not None else '—')
        if day == self.selectedDate() or day == QDate.currentDate():
            painter.setPen(QPen(QColor('#cfc4ff') if day == self.selectedDate() else QColor('#ffffff'), 2))
            painter.drawRect(rect.adjusted(2, 2, -2, -2))
        if day == QDate.currentDate():
            painter.setBrush(QColor('#ffffff'))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(rect.right() - 7, rect.top() + 7), 2, 2)
        painter.restore()


class CalendarNavigation(QWidget):
    """Public Qt controls, without relying on the native calendar's year editor."""
    def __init__(self, calendar):
        super().__init__()
        self.calendar = calendar
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.previous = QPushButton('‹')
        self.previous.setAccessibleName('Предыдущий месяц')
        self.previous.setToolTip('Предыдущий месяц')
        self.next = QPushButton('›')
        self.next.setAccessibleName('Следующий месяц')
        self.next.setToolTip('Следующий месяц')
        self.month = QComboBox()
        self.month.setAccessibleName('Месяц календаря')
        for month, name in enumerate(MONTHS, 1):
            self.month.addItem(name, month)
        self.year = QComboBox()
        self.year.setAccessibleName('Год календаря')
        self.year.setMaxVisibleItems(12)
        self.year.setStyleSheet('QComboBox { combobox-popup: 0; }')
        self.year.setToolTip('Выберите год из списка; можно искать год набором цифр')
        row.addWidget(self.previous)
        row.addWidget(self.month, 1)
        row.addWidget(self.year, 1)
        row.addWidget(self.next)
        self.previous.clicked.connect(calendar.showPreviousMonth)
        self.next.clicked.connect(calendar.showNextMonth)
        self.month.currentIndexChanged.connect(self.choose)
        self.year.currentIndexChanged.connect(self.choose)
        calendar.currentPageChanged.connect(self.sync)
        self.sync()

    def sync(self, *args):
        low, high = self.calendar.minimumDate(), self.calendar.maximumDate()
        year, month = self.calendar.yearShown(), self.calendar.monthShown()
        self.year.blockSignals(True)
        self.month.blockSignals(True)
        if self.year.count() != high.year() - low.year() + 1:
            self.year.clear()
            for y in range(high.year(), low.year() - 1, -1):
                self.year.addItem(str(y), y)
        self.year.setCurrentIndex(self.year.findData(year))
        self.month.setCurrentIndex(month - 1)
        for i in range(12):
            allowed = QDate(year, i + 1, 1) <= high and QDate(year, i + 1, 1).addMonths(1).addDays(-1) >= low
            self.month.model().item(i).setEnabled(allowed)
        self.previous.setEnabled((year, month) > (low.year(), low.month()))
        self.next.setEnabled((year, month) < (high.year(), high.month()))
        self.month.blockSignals(False)
        self.year.blockSignals(False)

    def choose(self, *args):
        year, month = self.year.currentData(), self.month.currentData()
        if year is None or month is None:
            return
        day = QDate(year, month, 1)
        day = max(self.calendar.minimumDate(), min(day, self.calendar.maximumDate()))
        self.calendar.setCurrentPage(day.year(), day.month())
        self.sync()


class MoodChart(QWidget):
    def __init__(self):
        super().__init__()
        self.values = []
        self.setMinimumHeight(200)
        self.setAccessibleName('График самочувствия по дням месяца, шкала от 0 до 10')

    def set_values(self, values):
        self.values = values
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, width, height = 35, 15, max(1, self.width() - 55), max(1, self.height() - 45)
        p.setPen(QColor('#939daf'))
        for value in (0, 5, 10):
            y = top + height * (1 - value / 10)
            p.drawText(2, int(y + 5), str(value))
            p.drawLine(left, int(y), left + width, int(y))
        previous = None
        for i, value in enumerate(self.values):
            x = left + width * i / max(1, len(self.values) - 1)
            if i % 5 == 0 or i == len(self.values) - 1:
                p.setPen(QColor('#939daf'))
                p.drawText(int(x - 5), int(top + height + 24), str(i + 1))
            if value is None:
                previous = None
                continue
            point = QPointF(x, top + height * (1 - value / 10))
            p.setPen(QPen(QColor('#b6a8ff'), 2))
            if previous is not None:
                p.drawLine(previous, point)
            p.setBrush(QColor('#b6a8ff'))
            p.drawEllipse(point, 4, 4)
            previous = point


class WellbeingPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.selected = date.today()
        self.loading = True
        self.dirty = False
        lay = QVBoxLayout(self)
        self.calendar = Calendar(window.store)
        self.calendar_navigation = CalendarNavigation(self.calendar)
        lay.addWidget(self.calendar_navigation)
        lay.addWidget(self.calendar)
        lay.addWidget(text('Шкала: 0–2 — тяжело · 3–4 — ниже среднего · 5–6 — средне · 7–8 — хорошо · 9–10 — отлично.\nЦвет от тёплого к зелёному; «—» — нет записи. Белая точка — сегодня, сиреневая — выбранный день.'))
        self.heading = text('')
        self.heading.setObjectName('section')
        lay.addWidget(self.heading)
        self.sliders = []
        self.labels = []
        for title in ('Самочувствие', 'Усталость'):
            label = text('')
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 10)
            slider.setValue(5)
            slider.setAccessibleName(title)
            self.labels.append(label)
            self.sliders.append(slider)
            slider.valueChanged.connect(self.edited)
            lay.addWidget(label)
            lay.addWidget(slider)
        lay.addWidget(text('Самочувствие: 0 — тяжело, 10 — отлично. Усталость: 0 — нет, 10 — очень сильная.'))
        self.note = QTextEdit()
        self.note.setMaximumHeight(110)
        self.note.setPlaceholderText('Что повлияло на состояние?')
        self.note.textChanged.connect(self.edited)
        lay.addWidget(self.note)
        self.status = text('')
        lay.addWidget(self.status)
        save = QPushButton('Сохранить выбранный день')
        save.clicked.connect(self.save)
        lay.addWidget(save)
        today = QPushButton('Сегодня')
        today.clicked.connect(lambda: self.calendar.setSelectedDate(QDate.currentDate()))
        lay.addWidget(today)
        self.month_summary = text('')
        lay.addWidget(self.month_summary)
        self.chart = MoodChart()
        lay.addWidget(self.chart)
        lay.addWidget(text('График: самочувствие по дням выбранного месяца. Пропуски не соединяются и не считаются нулями.'))
        self.year_summary = text('')
        lay.addWidget(self.year_summary)
        self.table = QTableWidget(12, 5)
        self.table.setHorizontalHeaderLabels(['Месяц', 'Дней', 'Среднее', 'Лучшая', 'Худшая'])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(410)
        self.table.cellActivated.connect(self.choose_month)
        self.table.cellClicked.connect(self.choose_month)
        lay.addWidget(self.table)
        lay.addWidget(text('Таблица сравнивает месяцы показанного года; выберите месяц для просмотра. Год можно изменить в заголовке календаря. Это самонаблюдение, а не медицинская оценка.'))
        self.calendar.selectionChanged.connect(self.select)
        self.calendar.currentPageChanged.connect(self.update_statistics)
        self.load()
        self.update_statistics()
        last = window.store.data.get('wellbeing_edit_date')
        try:
            day = date.fromisoformat(last)
            if day <= date.today() and last in self.drafts():
                self.calendar.setSelectedDate(QDate(day.year, day.month, day.day))
        except (ValueError, TypeError):
            pass

    def drafts(self):
        raw = self.window.store.data.get('wellbeing_drafts', {})
        return raw if isinstance(raw, dict) else {}

    def edited(self):
        for title, label, slider in zip(('Самочувствие', 'Усталость'), self.labels, self.sliders):
            label.setText(f'{title}: {slider.value()} / 10')
        if not self.loading:
            self.dirty = True
            drafts = dict(self.drafts())
            drafts[self.selected.isoformat()] = {'mood': self.sliders[0].value(), 'fatigue': self.sliders[1].value(), 'note': self.note.toPlainText()}
            self.window.store.data['wellbeing_drafts'] = drafts
            self.window.store.data['wellbeing_edit_date'] = self.selected.isoformat()
            self.window.persist()
            self.status.setText('Есть изменения. Нажмите «Сохранить выбранный день». При переходе к другой дате изменения будут сохранены.')

    def load(self):
        self.loading = True
        draft = self.drafts().get(self.selected.isoformat())
        record = draft if isinstance(draft, dict) else self.window.store.data['entries'].get(self.selected.isoformat(), {})
        record = record if isinstance(record, dict) else {}
        for key, slider in zip(('mood', 'fatigue'), self.sliders):
            slider.setValue(record[key] if score(record.get(key)) else 5)
        self.note.setPlainText(record.get('note', '') if isinstance(record.get('note', ''), str) else '')
        self.edited()
        self.heading.setText(self.selected.strftime('%d.%m.%Y'))
        self.status.setText('Запись сохранена.' if score(record.get('mood')) else 'Записи нет. Начальные значения ползунков не участвуют в статистике.')
        self.loading = False
        self.dirty = isinstance(draft, dict)
        if self.dirty:
            self.status.setText('Восстановлен черновик. Сохраните выбранный день, чтобы включить оценку в статистику.')

    def select(self):
        chosen = self.calendar.selectedDate().toPython()
        if chosen == self.selected:
            return
        if self.dirty and not self.save():
            self.calendar.blockSignals(True)
            self.calendar.setSelectedDate(QDate(self.selected.year, self.selected.month, self.selected.day))
            self.calendar.blockSignals(False)
            self.update_statistics()
            return
        self.selected = chosen
        self.load()

    def save(self):
        if self.selected > date.today():
            return False
        data = self.window.store.data['entries']
        key = self.selected.isoformat()
        old = data.get(key)
        record = dict(old) if isinstance(old, dict) else {}
        record.update(mood=self.sliders[0].value(), fatigue=self.sliders[1].value(), note=self.note.toPlainText().strip())
        data[key] = record
        drafts_before = self.window.store.data.get('wellbeing_drafts')
        drafts = dict(self.drafts())
        drafts.pop(key, None)
        self.window.store.data['wellbeing_drafts'] = drafts
        if not self.window.persist():
            if drafts_before is None:
                self.window.store.data.pop('wellbeing_drafts', None)
            else:
                self.window.store.data['wellbeing_drafts'] = drafts_before
            if old is None:
                data.pop(key, None)
            else:
                data[key] = old
            return False
        self.dirty = False
        self.status.setText('Сохранено для ' + self.selected.strftime('%d.%m.%Y'))
        self.window.refresh()
        return True

    def choose_month(self, row, column):
        year = self.calendar.yearShown()
        if date(year, row + 1, 1) <= date.today():
            self.calendar.setSelectedDate(QDate(year, row + 1, 1))
            self.calendar.setCurrentPage(year, row + 1)

    def update_statistics(self, *args):
        raw = self.window.store.data['entries']
        year, month = self.calendar.yearShown(), self.calendar.monthShown()
        stats = month_stats(raw, year, month)
        def describe(s):
            return (f"Дней с записью: {s['count']} · среднее {s['mean']:.2f}/10 · лучшая {s['best']} · худшая {s['worst']}" if s['count'] else 'Нет заполненных дней')
        delta = change(raw, year, month)
        comparison = f'Изменение среднего к прошлому месяцу: {delta:+.2f}.' if delta is not None else 'Для сравнения нужно хотя бы по 5 записей в каждом из двух месяцев.'
        valid = entries(raw)
        skipped = len(raw) - len(valid)
        warning = f'\nНе учитываются некорректные или будущие записи: {skipped}. Исходные данные сохранены.' if skipped else ''
        self.month_summary.setText(f'{MONTHS[month - 1]} {year}: {describe(stats)}\n{comparison}{warning}')
        self.chart.set_values(month_series(raw, year, month))
        self.year_summary.setText(f'Год {year}: {describe(year_stats(raw, year))}')
        for i in range(12):
            s = month_stats(raw, year, i + 1)
            values = [MONTHS[i], str(s['count']), f"{s['mean']:.2f}" if s['mean'] is not None else '—', str(s['best']) if s['best'] is not None else '—', str(s['worst']) if s['worst'] is not None else '—']
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
        self.calendar.reload()
        self.calendar_navigation.sync()
