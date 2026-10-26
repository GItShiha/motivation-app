"""Work page and an independent Qt floating counter, with no CRM access."""
import json
import os
from pathlib import Path
import sys
from PySide6.QtCore import Qt, QByteArray, QTimer, QProcess
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QCheckBox, QProgressBar, QApplication, QMessageBox, QScrollArea, QLayout, QSizePolicy)
from tickets import TicketLedger


def text(value=''):
    label = QLabel(value)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def button(title, action):
    item = QPushButton(title)
    item.clicked.connect(action)
    return item


def number(lay, title, minimum=0, maximum=1000000):
    lay.addWidget(text(title))
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setAccessibleName(title)
    lay.addWidget(spin)
    return spin


class CounterView(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.count = text()
        self.count.setObjectName('metric')
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.count)
        row = QHBoxLayout()
        self.minus = button('−', lambda: page.act(lambda: page.ledger.step(-1)))
        self.plus = button('+', lambda: page.act(lambda: page.ledger.step(1)))
        for b in (self.minus, self.plus):
            b.setMinimumSize(70, 50)
            row.addWidget(b)
        lay.addLayout(row)
        self.details = text()
        lay.addWidget(self.details)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setStyleSheet('QProgressBar {background: #252a35; border: 1px solid #384153; border-radius: 6px; text-align: center;} QProgressBar::chunk {background: #64558d;}')
        lay.addWidget(self.progress)
        self.notice = text()
        lay.addWidget(self.notice)
        self.break_box = QWidget()
        controls = QVBoxLayout(self.break_box)
        self.break_text = text()
        self.break_text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        controls.addWidget(self.break_text)
        controls.addWidget(button('Перейти в «Восстановление»', page.recover))
        row = QHBoxLayout()
        row.addWidget(button('Позже', lambda: page.act(lambda: page.ledger.mark_break('later'))))
        row.addWidget(button('Пропустить', lambda: page.act(lambda: page.ledger.mark_break('skipped'))))
        controls.addLayout(row)
        lay.addWidget(self.break_box)
        self.break_box.hide()

    def render(self):
        shift = self.page.ledger.active
        self.plus.setEnabled(shift is not None)
        self.minus.setEnabled(shift is not None and shift['count'] > 0)
        if not shift:
            self.count.setText('Смена не начата')
            self.details.setText('Начните новую смену в разделе «Работа».')
            self.progress.setValue(0)
            self.break_box.hide()
            return
        self.count.setText(f"{shift['count']} / {shift['goal']}")
        interval = shift['interval']
        remaining = ((max(shift['count'], shift['break_high']) // interval) + 1) * interval - shift['count']
        self.details.setText(f"Норма: {shift['percent']:.1f}% · осталось {max(0, shift['goal'] - shift['count'])}\nДо следующего перерыва: {remaining} тикетов\nСмена от {shift['date']}" + ('\nУчёт сверх нормы отключён.' if not shift['track_excess'] else ''))
        self.progress.setValue(int(shift['percent']))
        pending = [e for e in shift['breaks'] if e['state'] == 'pending']
        self.break_box.setVisible(bool(pending))
        if pending:
            self.break_text.setText(f"Пора сделать перерыв: пройден порог {pending[-1]['threshold']}. Рекомендуемый перерыв: {shift['break_minutes']} мин.")
        self.notice.setText(self.page.message)


class FloatingCounter(QWidget):
    def __init__(self, page):
        super().__init__(page.window, Qt.WindowType.Window)
        self.page = page
        self.ready = False
        self.setWindowTitle('Точка опоры · Тикеты')
        self.resize(330, 380)
        lay = QVBoxLayout(self)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.content)
        lay.addWidget(self.scroll)
        lay = self.content_layout
        self.view = CounterView(page)
        lay.addWidget(self.view)
        self.top = QCheckBox('Поверх всех окон')
        self.compact = QCheckBox('Компактный режим')
        lay.addWidget(self.top)
        lay.addWidget(self.compact)
        self.help = text('Положение и режим поверх окон зависят от правил KDE/Wayland. Окно можно перемещать за заголовок.')
        lay.addWidget(self.help)
        self.more = button('Развернуть', lambda: self.compact.setChecked(False))
        lay.addWidget(self.more)
        self.geometry_timer = QTimer(self)
        self.geometry_timer.setSingleShot(True)
        self.geometry_timer.setInterval(300)
        self.geometry_timer.timeout.connect(self.save_state)
        state = page.ledger.data.get('window', {})
        self.top.setChecked(state.get('top', False) is True)
        self.compact.setChecked(state.get('compact', False) is True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.top.isChecked())
        encoded = state.get('geometry')
        if isinstance(encoded, str):
            self.restoreGeometry(QByteArray.fromBase64(encoded.encode()))
        self.top.toggled.connect(self.top_changed)
        self.compact.toggled.connect(self.compact_changed)
        self.pin_process = None
        self.ready = True
        self.compact_changed(save=False)

    def top_changed(self):
        if QGuiApplication.platformName().startswith('wayland'):
            self.pin_kwin()
            return
        geometry = self.saveGeometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.top.isChecked())
        self.show()
        self.restoreGeometry(geometry)
        self.save_state()

    def pin_kwin(self):
        if self.pin_process is not None:
            return
        enabled = self.top.isChecked()
        self.top.setEnabled(False)
        self.help.setText('Запрашиваем закрепление окна у KWin…')
        process = QProcess(self)
        self.pin_process = process
        process.setProgram(sys.executable)
        process.setArguments([str(Path(__file__).with_name('kwin_pin.py')), str(os.getpid()), '1' if enabled else '0', self.windowTitle()])
        process.setStandardErrorFile(QProcess.nullDevice())
        def done(*args):
            if self.pin_process is not process:
                return
            try:
                confirmed = json.loads(bytes(process.readAllStandardOutput())).get('ok') is True
            except (ValueError, UnicodeError):
                confirmed = False
            self.pin_process = None
            self.top.setEnabled(True)
            if not confirmed:
                self.top.blockSignals(True)
                self.top.setChecked(not enabled)
                self.top.blockSignals(False)
                self.help.setText('KWin не подтвердил изменение. Используйте Alt+F3 → Дополнительные действия → Поверх остальных.')
            else:
                self.help.setText('KWin подтвердил: ' + ('окно поверх остальных.' if enabled else 'обычный режим окна.'))
            self.save_state()
            process.deleteLater()
        process.finished.connect(done)
        process.errorOccurred.connect(lambda error: done() if error == QProcess.ProcessError.FailedToStart else None)
        watchdog = QTimer(process)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(process.kill)
        watchdog.start(7000)
        process.start()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_content)
        if self.ready and self.top.isChecked() and QGuiApplication.platformName().startswith('wayland'):
            QTimer.singleShot(200, self.pin_kwin)

    def compact_changed(self, *args, save=True):
        compact = self.compact.isChecked()
        for w in (self.view.details, self.view.progress, self.view.notice, self.view.break_box, self.top, self.compact, self.help):
            w.setVisible(not compact)
        self.more.setVisible(compact)
        if compact:
            self.content.layout().activate()
            self.resize(self.width(), self.content.sizeHint().height() + 24)
        if not compact:
            QTimer.singleShot(0, self.fit_content)
        if save:
            self.save_state()

    def fit_content(self):
        if self.compact.isChecked() or not self.isVisible():
            return
        width = self.scroll.viewport().width()
        needed = self.content.heightForWidth(width)
        if needed < 0:
            needed = self.content.sizeHint().height()
        limit = self.screen().availableGeometry().height() - 80
        self.resize(self.width(), min(max(self.height(), needed + 32), max(200, limit)))

    def render(self):
        self.view.render()
        self.content.layout().activate()
        self.fit_content()
        if self.compact.isChecked():
            for w in (self.view.details, self.view.progress, self.view.notice, self.view.break_box):
                w.hide()

    def save_state(self):
        if not self.ready:
            return True
        settings = {'top': self.top.isChecked(), 'compact': self.compact.isChecked(), 'geometry': bytes(self.saveGeometry().toBase64()).decode()}
        return self.page.act(lambda: self.page.ledger.window_settings(settings), refresh=False)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.ready:
            self.geometry_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.ready:
            self.geometry_timer.start()

    def stop_pin(self):
        process = self.pin_process
        if process is not None:
            self.pin_process = None
            process.finished.disconnect()
            process.errorOccurred.disconnect()
            process.finished.connect(process.deleteLater)
            process.kill()
            self.top.blockSignals(True)
            self.top.setChecked(not self.top.isChecked())
            self.top.blockSignals(False)
            self.top.setEnabled(True)

    def closeEvent(self, event):
        self.stop_pin()
        self.geometry_timer.stop()
        if self.save_state():
            event.accept()
        else:
            event.ignore()


class WorkPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.floating = None
        self.message = ''
        lay = QVBoxLayout(self)
        self.status = text()
        lay.addWidget(self.status)
        try:
            self.ledger = TicketLedger(window.store)
        except (ValueError, KeyError, TypeError) as exc:
            self.status.setText('Не удалось прочитать историю работы. Данные сохранены без изменений. ' + str(exc))
            self.ledger = None
            return
        self.view = CounterView(self)
        lay.addWidget(self.view)
        lay.addWidget(button('Открыть плавающий счётчик', self.open_counter))
        self.initial = number(lay, 'Уже обработано к началу новой смены')
        lay.addWidget(button('Начать новую смену', self.ask_start))
        lay.addWidget(button('Завершить текущую смену', lambda: self.act(self.ledger.end)))
        self.parameters = QWidget()
        outer = lay
        toggle = QCheckBox('Параметры смены и ручное исправление')
        toggle.setChecked(self.ledger.active is None)
        outer.addWidget(toggle)
        outer.addWidget(self.parameters)
        toggle.toggled.connect(self.parameters.setVisible)
        self.parameters.setVisible(toggle.isChecked())
        lay = QVBoxLayout(self.parameters)
        config = self.ledger.data['settings']
        self.goal = number(lay, 'Дневная норма', 1)
        self.interval = number(lay, 'Перерыв каждые N тикетов', 1)
        self.minutes = number(lay, 'Рекомендуемый перерыв, минут', 1, 120)
        for field, key in ((self.goal, 'goal'), (self.interval, 'interval'), (self.minutes, 'break_minutes')):
            field.setValue(config[key])
        self.reminders = QCheckBox('Напоминать о перерывах')
        self.reminders.setChecked(config['reminders'])
        lay.addWidget(self.reminders)
        self.excess = QCheckBox('Продолжать учёт фактических тикетов после нормы')
        self.excess.setChecked(config['track_excess'])
        lay.addWidget(self.excess)
        lay.addWidget(button('Применить параметры к текущей и следующим сменам', self.configure))
        self.correction = number(lay, 'Исправить фактическое количество в текущей смене')
        lay.addWidget(button('Применить исправление', lambda: self.act(lambda: self.ledger.set_count(self.correction.value()))))
        lay = outer
        lay.addWidget(button('Сделать отложенный перерыв', self.recover))
        self.stats = text()
        lay.addWidget(self.stats)
        self.history = text()
        lay.addWidget(self.history)
        lay.addWidget(text('Ручной счётчик не читает CRM. Смена не сбрасывается в полночь. Статистика относится к дате начала смены.'))
        self.render()

    def act(self, action, refresh=True):
        try:
            notices = action()
        except (OSError, ValueError) as exc:
            self.status.setText('Не удалось сохранить изменение: ' + str(exc))
            self.window.statusBar().showMessage(self.status.text())
            if self.floating:
                self.floating.view.notice.setText(self.status.text())
                self.floating.view.notice.show()
            return False
        self.status.setText('')
        if isinstance(notices, list) and notices:
            if 'goal' in notices:
                self.message = 'Дневная норма выполнена'
                self.window.sounds.play('tickets_goal', tone='bell')
            elif 'break' in notices:
                self.message = 'Пора сделать перерыв'
                self.window.sounds.play('tickets_break')
            self.window.statusBar().showMessage(self.message)
            QApplication.alert(self.floating or self.window, 0)
        if refresh:
            self.render()
        return True

    def configure(self):
        self.act(lambda: self.ledger.configure({'goal': self.goal.value(), 'interval': self.interval.value(), 'break_minutes': self.minutes.value(), 'reminders': self.reminders.isChecked(), 'track_excess': self.excess.isChecked()}))

    def ask_start(self):
        if not self.ledger.active:
            self.start()
            return
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle('Начать новую смену?')
        dialog.setText('Текущая смена будет завершена и останется в истории.')
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Yes).setText('Начать новую смену')
        dialog.button(QMessageBox.StandardButton.Cancel).setText('Отмена')
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.finished.connect(lambda result: self.start() if result == QMessageBox.StandardButton.Yes else None)
        self.dialog = dialog
        dialog.open()

    def start(self):
        if self.act(lambda: self.ledger.start(self.initial.value())):
            self.message = ''
            self.render()

    def recover(self):
        if self.window.remaining or self.window.recovery.exercise is not None:
            self.status.setText('Сначала завершите текущую фокус-сессию или упражнение.')
            return
        if self.act(lambda: self.ledger.mark_break('started')):
            self.window.navigate(5)
            minutes = self.ledger.active['break_minutes'] if self.ledger.active else self.minutes.value()
            recovery = self.window.recovery
            index = recovery.time.findData(min((2, 5, 10, 20), key=lambda n: abs(n - minutes)))
            recovery.time.setCurrentIndex(index)
            self.window.showNormal()
            self.window.raise_()

    def open_counter(self):
        if self.floating is None:
            self.floating = FloatingCounter(self)
        self.floating.render()
        self.floating.show()
        self.floating.raise_()

    def render(self):
        self.view.render()
        if self.floating:
            self.floating.render()
        self.correction.setEnabled(self.ledger.active is not None)
        if self.ledger.active:
            self.correction.setValue(self.ledger.active['count'])
        lines = []
        for title, stats in (('Сегодня', self.ledger.statistics(1)), ('Последние 7 дней', self.ledger.statistics(7)), ('Текущий месяц', self.ledger.statistics(month=True))):
            percent = f"{stats['percent']:.1f}%" if stats['percent'] is not None else '—'
            lines.append(f"{title}: смен {stats['shifts']}, фактически {stats['count']}, в норме {stats['credited']}, выполнение {percent}")
        self.stats.setText('\n'.join(lines))
        rows = []
        for shift in reversed(self.ledger.data['shifts']):
            breaks = ', '.join(f"{e['threshold']}: " + {'pending': 'предложен', 'later': 'отложен', 'skipped': 'пропущен', 'started': 'переход к восстановлению'}[e['state']] for e in shift['breaks']) or 'нет отметок'
            rows.append(f"{shift['date']} · {shift['count']} / {shift['goal']} · {shift['percent']:.1f}%\nНачало {shift['started_at']} · конец {shift.get('ended_at') or 'смена продолжается'}\nПерерывы: {breaks}")
        self.history.setText('История смен\n' + ('\n\n'.join(rows) if rows else 'Пока нет смен.'))

    def shutdown(self):
        if self.floating:
            self.floating.stop_pin()
            self.floating.geometry_timer.stop()
            if not self.floating.save_state():
                return False
            self.floating.hide()
        return True
