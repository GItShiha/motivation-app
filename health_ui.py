"""Personal health action journal; no prescriptions or default medications."""
import calendar
from datetime import date, timedelta
from PySide6.QtCore import QDate, QLocale, Qt, QTimer
from PySide6.QtGui import QColor, QPen, QTextCharFormat
from PySide6.QtWidgets import (QWidget, QCalendarWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QLineEdit, QTextEdit, QSpinBox, QCheckBox, QDateEdit, QApplication)
from health import HealthLedger, KINDS
from wellbeing_ui import CalendarNavigation
from tickets_ui import text, button

STATES = {'none': ('—', '#252a35'), 'full': ('✓', '#366b50'), 'partial': ('Часть', '#726131'), 'skipped': ('Пропуск', '#70484c'), 'empty': ('Не отм.', '#3c485b')}


class HealthCalendar(QCalendarWidget):
    def __init__(self, ledger):
        super().__init__()
        self.ledger = ledger
        self.setLocale(QLocale('ru_RU'))
        self.setMinimumDate(QDate(1, 1, 1))
        self.setMaximumDate(QDate.currentDate())
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setMinimumHeight(340)
        header = QTextCharFormat()
        header.setForeground(QColor('#e8eaf0'))
        header.setBackground(QColor('#252a35'))
        self.setHeaderTextFormat(header)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, header)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, header)

    def paintCell(self, p, rect, day):
        if day.month() != self.monthShown() or day > self.maximumDate():
            super().paintCell(p, rect, day)
            return
        title, color = STATES[self.ledger.day_status(day.toPython())]
        p.save()
        p.fillRect(rect.adjusted(1, 1, -1, -1), QColor(color))
        p.setPen(QColor('#ffffff'))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(day.day()) + '\n' + title)
        if day == self.selectedDate() or day == QDate.currentDate():
            p.setPen(QPen(QColor('#cfc4ff') if day == self.selectedDate() else QColor('#ffffff'), 2))
            p.drawRect(rect.adjusted(2, 2, -2, -2))
        p.restore()


class HealthPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        lay = QVBoxLayout(self)
        lay.addWidget(text('Только учёт назначенных вам или выбранных вами действий. Приложение не назначает лекарства, не меняет дозировки и не рекомендует двойной приём при пропуске.'))
        self.status = text()
        lay.addWidget(self.status)
        try:
            self.ledger = HealthLedger(window.store)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            self.status.setText('История здоровья недоступна; данные оставлены без изменений. ' + str(exc))
            self.ledger = None
            return
        self.global_reminders = QCheckBox('Локальные напоминания (пока приложение запущено)')
        self.global_reminders.setChecked(self.ledger.data['reminders'])
        self.global_reminders.toggled.connect(lambda value: self.act(lambda: self.ledger.reminders(value)))
        lay.addWidget(self.global_reminders)
        self.calendar = HealthCalendar(self.ledger)
        self.nav = CalendarNavigation(self.calendar)
        lay.addWidget(self.nav)
        lay.addWidget(self.calendar)
        lay.addWidget(text('✓ — всё выполнено · «Часть» — выполнено частично · «Пропуск» — есть явный пропуск · «Не отм.» — действия запланированы, отметок нет · «—» — ничего не запланировано. Отсутствие отметки не означает пропуск.'))
        lay.addWidget(button('Сегодня', lambda: self.calendar.setSelectedDate(QDate.currentDate())))
        self.day_heading = text()
        lay.addWidget(self.day_heading)
        self.day_list = QVBoxLayout()
        lay.addLayout(self.day_list)
        self.stats = text()
        lay.addWidget(self.stats)
        self.history_filter = QComboBox()
        self.history_filter.addItem('История всех действий', None)
        self.history_filter.currentIndexChanged.connect(self.render_history)
        lay.addWidget(self.history_filter)
        self.history = text()
        self.history_toggle = QCheckBox('Показать историю за выбранный месяц')
        lay.addWidget(self.history_toggle)
        lay.addWidget(self.history)
        self.history.hide()
        self.history_filter.hide()
        self.history_toggle.toggled.connect(self.history.setVisible)
        self.history_toggle.toggled.connect(self.history_filter.setVisible)
        self.toggle = QCheckBox('Добавить действие / изменить расписание')
        lay.addWidget(self.toggle)
        self.form = QWidget()
        form = QVBoxLayout(self.form)
        lay.addWidget(self.form)
        self.form.hide()
        self.toggle.toggled.connect(self.form.setVisible)
        self.picker = QComboBox()
        form.addWidget(self.picker)
        self.name = QLineEdit()
        self.name.setPlaceholderText('Название лекарства, процедуры или привычки')
        form.addWidget(self.name)
        self.kind = QComboBox()
        self.kind.addItems(KINDS)
        form.addWidget(self.kind)
        self.weekdays = []
        row = QHBoxLayout()
        for name in ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'):
            check = QCheckBox(name)
            check.setChecked(True)
            self.weekdays.append(check)
            row.addWidget(check)
        form.addLayout(row)
        form.addWidget(text('Количество выполнений в день'))
        self.count = QSpinBox()
        self.count.setRange(1, 12)
        form.addWidget(self.count)
        self.times = QLineEdit()
        self.times.setPlaceholderText('Время для каждого выполнения: 08:00, 20:00 (необязательно)')
        form.addWidget(self.times)
        self.remind = QCheckBox('Напоминать об этом действии в заданное время')
        form.addWidget(self.remind)
        form.addWidget(text('Начало расписания'))
        self.start = QDateEdit(QDate.currentDate())
        self.start.setDisplayFormat('dd.MM.yyyy')
        form.addWidget(self.start)
        self.has_end = QCheckBox('Есть дата окончания')
        form.addWidget(self.has_end)
        self.end = QDateEdit(QDate.currentDate())
        self.end.setDisplayFormat('dd.MM.yyyy')
        self.end.setEnabled(False)
        self.has_end.toggled.connect(self.end.setEnabled)
        form.addWidget(self.end)
        self.description = QTextEdit()
        self.description.setPlaceholderText('Дополнительное описание (без автоматических рекомендаций)')
        self.description.setMaximumHeight(90)
        form.addWidget(self.description)
        form.addWidget(text('Изменения существующего действия действуют с будущей даты; прошлые дни сохраняют прежнее расписание. Новая версия заменяет ранее запланированные изменения начиная с этой даты.'))
        self.effective = QDateEdit(QDate.currentDate().addDays(1))
        self.effective.setMinimumDate(QDate.currentDate().addDays(1))
        self.effective.setDisplayFormat('dd.MM.yyyy')
        form.addWidget(self.effective)
        form.addWidget(button('Сохранить действие / новую версию расписания', self.save_form))
        form.addWidget(button('Прекратить действие с выбранной будущей даты', self.archive))
        self.picker.currentIndexChanged.connect(self.load_form)
        self.calendar.selectionChanged.connect(self.render)
        self.calendar.currentPageChanged.connect(self.render_history)
        # Put daily marking and adding an action before the calendar and analytics.
        lay.removeWidget(self.toggle)
        lay.removeWidget(self.form)
        lay.insertWidget(3, self.toggle)
        lay.insertWidget(4, self.form)
        lay.removeWidget(self.day_heading)
        lay.removeItem(self.day_list)
        lay.insertWidget(5, self.day_heading)
        lay.insertLayout(6, self.day_list)
        self.reload_actions()
        self.render()
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.check_reminders)
        self.timer.start()
        QTimer.singleShot(1000, self.check_reminders)

    def act(self, action):
        try:
            result = action()
        except (OSError, ValueError) as exc:
            self.status.setText('Изменение не сохранено: ' + str(exc))
            self.global_reminders.blockSignals(True)
            self.global_reminders.setChecked(self.ledger.data['reminders'])
            self.global_reminders.blockSignals(False)
            return False
        self.status.setText('Сохранено локально.')
        self.render()
        return True

    def reload_actions(self):
        selected = self.picker.currentData()
        self.picker.blockSignals(True)
        self.history_filter.blockSignals(True)
        history_id = self.history_filter.currentData()
        self.picker.clear()
        self.history_filter.clear()
        self.picker.addItem('Новое действие', None)
        self.history_filter.addItem('История всех действий', None)
        for action in self.ledger.data['actions']:
            latest = action['revisions'][-1]
            title = latest['name'] + (' (прекращение запланировано)' if latest.get('archived') else '')
            self.picker.addItem(title, action['id'])
            self.history_filter.addItem(title, action['id'])
        self.picker.setCurrentIndex(max(0, self.picker.findData(selected)))
        self.history_filter.setCurrentIndex(max(0, self.history_filter.findData(history_id)))
        self.picker.blockSignals(False)
        self.history_filter.blockSignals(False)
        self.load_form()

    def load_form(self):
        aid = self.picker.currentData()
        s = self.ledger.action(aid)['revisions'][-1] if aid else {'name': '', 'kind': KINDS[0], 'weekdays': list(range(7)), 'count': 1, 'times': [], 'remind': False, 'start': date.today().isoformat(), 'end': None, 'description': ''}
        self.name.setText(s['name'])
        self.kind.setCurrentText(s['kind'])
        for i, check in enumerate(self.weekdays):
            check.setChecked(i in s['weekdays'])
        self.count.setValue(s['count'])
        self.times.setText(', '.join(s['times']))
        self.remind.setChecked(s['remind'])
        self.start.setDate(QDate.fromString(s['start'], 'yyyy-MM-dd'))
        self.has_end.setChecked(bool(s.get('end')))
        self.end.setDate(QDate.fromString(s['end'], 'yyyy-MM-dd') if s.get('end') else QDate.currentDate())
        self.description.setPlainText(s.get('description', ''))
        self.effective.setEnabled(aid is not None)

    def form_data(self):
        return {'name': self.name.text().strip(), 'kind': self.kind.currentText(), 'weekdays': [i for i, c in enumerate(self.weekdays) if c.isChecked()], 'count': self.count.value(), 'times': [s.strip() for s in self.times.text().split(',') if s.strip()], 'remind': self.remind.isChecked(), 'start': self.start.date().toString('yyyy-MM-dd'), 'end': self.end.date().toString('yyyy-MM-dd') if self.has_end.isChecked() else None, 'description': self.description.toPlainText()}

    def save_form(self):
        aid, schedule = self.picker.currentData(), self.form_data()
        action = (lambda: self.ledger.revise(aid, schedule, self.effective.date().toPython())) if aid else (lambda: self.ledger.add(schedule))
        if self.act(action):
            self.reload_actions()
            self.status.setText('Сохранено.' + (' Новая версия действует с ' + self.effective.date().toString('dd.MM.yyyy') if aid else ''))

    def archive(self):
        aid = self.picker.currentData()
        if aid and self.act(lambda: self.ledger.revise(aid, self.ledger.action(aid)['revisions'][-1], self.effective.date().toPython(), archived=True)):
            self.reload_actions()

    def render(self, *args):
        day = self.calendar.selectedDate().toPython()
        self.day_heading.setText('Действия на ' + day.strftime('%d.%m.%Y'))
        while self.day_list.count():
            item = self.day_list.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        slots = self.ledger.slots(day)
        for s in slots:
            box = QWidget()
            line = QVBoxLayout(box)
            title = s['schedule']['name'] + f" · {s['slot'] + 1}/{s['schedule']['count']}" + (' · ' + s['time'] if s['time'] else '')
            state = {'done': 'Выполнено', 'skipped': 'Пропущено', 'unmarked': 'Ещё не отмечено'}[s['state']]
            line.addWidget(text(title + ' — ' + state))
            if s['schedule'].get('description'):
                line.addWidget(text(s['schedule']['description']))
            row = QHBoxLayout()
            for title, value in (('Выполнено', 'done'), ('Пропущено', 'skipped'), ('Снять отметку', 'unmarked')):
                row.addWidget(button(title, lambda checked=False, aid=s['action'], slot=s['slot'], state=value, d=day: self.act(lambda: self.ledger.mark(d, aid, slot, state))))
            line.addLayout(row)
            self.day_list.addWidget(box)
        if not slots:
            self.day_list.addWidget(text('Нет запланированных действий.'))
        for action in self.ledger.data['actions']:
            if not self.ledger.planned(action['id'], day):
                self.day_list.addWidget(text(action['revisions'][-1]['name'] + ' — не требуется сегодня.'))
        self.calendar.setMaximumDate(QDate.currentDate())
        self.calendar.updateCells()
        self.nav.sync()
        self.render_history()

    def render_history(self, *args):
        now = self.ledger.now().date()
        year, month = self.calendar.yearShown(), self.calendar.monthShown()
        start, end = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
        def describe(s):
            percent = f"{s['percent']:.1f}%" if s['percent'] is not None else '—'
            return f"выполнено {s['done']}/{s['planned']} ({percent}), пропущено {s['skipped']}, без отметки {s['unmarked']}, полных дней {s['full_days']}"
        self.stats.setText('Последние 7 дней: ' + describe(self.ledger.statistics(now - timedelta(days=6), now)) + f'\nМесяц {month:02}.{year}: ' + describe(self.ledger.statistics(start, end)))
        aid = self.history_filter.currentData()
        lines = ['История за выбранный месяц' + (' · ' + describe(self.ledger.statistics(start, end, aid)) if aid else '')]
        day = start
        while day <= min(end, now):
            slots = self.ledger.slots(day, aid)
            if slots:
                lines.append(day.strftime('%d.%m.%Y') + ': ' + ', '.join(s['schedule']['name'] + f" #{s['slot'] + 1}: " + {'done': 'выполнено', 'skipped': 'пропущено', 'unmarked': 'без отметки'}[s['state']] for s in slots))
            day += timedelta(days=1)
        self.history.setText('\n'.join(lines))

    def check_reminders(self):
        if self.ledger is None:
            return
        try:
            due = self.ledger.due()
        except OSError:
            self.status.setText('Не удалось сохранить отметку напоминания; уведомление отложено.')
            return
        if due:
            self.status.setText('Запланированные действия: ' + ', '.join(s['schedule']['name'] + f" #{s['slot'] + 1}" for s in due) + '. Проверьте назначенное вам расписание.')
            self.window.statusBar().showMessage('Есть запланированные действия в разделе «Здоровье».')
            QApplication.alert(self.window, 0)

    def shutdown(self):
        if self.ledger is not None:
            self.timer.stop()
