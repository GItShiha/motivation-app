"""Точка опоры — локальное настольное приложение для маленьких устойчивых действий."""
import sys
if __name__ == '__main__' and '--update-smoke-test' not in sys.argv:
    from update_bootstrap import route
    route()

import json
import os
import time
from datetime import date, datetime
from pathlib import Path

from guide import IntentionsGuide
from autostart import Autostart
from recovery_ui import RecoveryPage
from update_ui import UpdatePanel
from sounds import TimerSounds, SoundSettings

from PySide6.QtCore import Qt, QTimer, QStandardPaths
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame, QLineEdit, QTextEdit, QSlider, QSpinBox, QComboBox, QCheckBox,
    QStackedWidget, QScrollArea, QMessageBox, QLayout,
)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"plans": [], "entries": {}, "sessions": []}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or not isinstance(loaded.get('plans'), list) or not isinstance(loaded.get('entries'), dict) or not isinstance(loaded.get('sessions'), list):
                    raise ValueError('Неверный формат данных')
                if loaded.get('schema_version', 1) != 1:
                    raise ValueError('Эта версия не поддерживает формат данных. Файл не изменён; используйте совместимую версию приложения.')
                self.data = loaded
            except (ValueError, OSError) as exc:
                raise RuntimeError(f'Не удалось прочитать {self.path}. Файл сохранён без изменений. {exc}') from exc

    def save(self):
        from update_bootstrap import atomic
        atomic(self.path, self.data)


STYLE = """
QWidget { background: #101217; color: #e8eaf0; font-family: 'DejaVu Sans'; font-size: 14px; }
QMainWindow { background: #101217; }
QFrame#sidebar { background: #151820; border-right: 1px solid #282d38; }
QFrame#card { background: #1a1e27; border: 1px solid #2b3140; border-radius: 16px; }
QLabel { background: transparent; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#subtitle { color: #939daf; font-size: 14px; }
QLabel#section { font-size: 18px; font-weight: 600; }
QLabel#metric { font-size: 32px; color: #b7b0ff; font-weight: 700; }
QLabel#clock { font-size: 64px; font-weight: 700; color: #cdc7ff; }
QPushButton { background: #282e3b; border: 1px solid #363e4e; border-radius: 9px; padding: 11px 17px; }
QPushButton:hover { background: #373e50; }
QPushButton:disabled { color: #646d80; background: #222631; }
QPushButton#primary { background: #a99aff; color: #151122; border: none; font-weight: 700; }
QPushButton#primary:hover { background: #c0b5ff; }
QPushButton#nav { text-align: left; background: transparent; border: none; padding: 15px; color: #9da7ba; }
QPushButton#nav:checked { color: #d2caff; background: #2b273f; }
QLineEdit, QTextEdit, QSpinBox, QComboBox { background: #12161e; border: 1px solid #384153; border-radius: 8px; padding: 10px; selection-background-color: #64558d; }
QLineEdit:focus, QTextEdit:focus { border: 1px solid #aa9bff; }
QSlider::groove:horizontal { height: 6px; background: #343b4b; border-radius: 3px; }
QSlider::handle:horizontal { background: #b6a8ff; width: 18px; margin: -6px 0; border-radius: 9px; }
QScrollArea { border: none; } QToolTip { color: #fff; background: #282e3b; }
"""


def label(text, name=None):
    item = QLabel(text)
    item.setWordWrap(True)
    item.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        item.setObjectName(name)
    return item


def button(text, callback, primary=False):
    item = QPushButton(text)
    if primary:
        item.setObjectName('primary')
    item.clicked.connect(callback)
    return item


def card():
    box = QFrame()
    box.setObjectName('card')
    layout = QVBoxLayout(box)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(14)
    return box, layout


class Window(QMainWindow):
    def __init__(self, store, autostart=None):
        super().__init__()
        self.store = store
        self.sounds = TimerSounds(store, self)
        self.autostart = autostart if autostart is not None else Autostart()
        self.setWindowTitle('Точка опоры')
        self.resize(1140, 820)
        self.setMinimumSize(850, 650)
        self.deadline = None
        self.remaining = 0
        self.session_minutes = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        side = QFrame()
        side.setObjectName('sidebar')
        side.setFixedWidth(230)
        nav = QVBoxLayout(side)
        nav.setContentsMargins(20, 30, 20, 24)
        main_nav = QWidget()
        top = QVBoxLayout(main_nav)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        top.addWidget(label('◈  ТОЧКА ОПОРЫ', 'section'))
        top.addWidget(label('Маленькие шаги.\nБольше пространства.', 'subtitle'))
        top.addSpacing(20)
        self.navs = []
        self.stack = QStackedWidget()
        for i, name in enumerate(['Обзор', 'Если → то', 'Пауза от ленты', 'Самочувствие', 'Настройки', 'Восстановление']):
            b = button(name, lambda checked=False, index=i: self.navigate(index))
            b.setObjectName('nav')
            b.setCheckable(True)
            self.navs.append(b)
            if i != 4:
                top.addWidget(b)
        top.addStretch()
        self.nav_scroll = QScrollArea()
        self.nav_scroll.setWidgetResizable(True)
        self.nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_scroll.setWidget(main_nav)
        nav.addWidget(self.nav_scroll, 1)
        nav.addWidget(label('Локально и лично\nДанные остаются на устройстве', 'subtitle'))
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        nav.addWidget(separator)
        nav.addWidget(self.navs[4])
        # Tab follows the visible order even though page indices remain stable.
        for first, second in zip([self.navs[i] for i in (0, 1, 2, 3, 5)], [self.navs[i] for i in (1, 2, 3, 5, 4)]):
            QWidget.setTabOrder(first, second)
        row.addWidget(side)
        row.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.build_overview()
        self.build_plans()
        self.build_focus()
        self.build_wellbeing()
        self.build_settings()
        recovery_layout = self.page('Восстановление', 'Как вы себя чувствуете? Выберите время и посильный способ восстановиться.')
        self.recovery = RecoveryPage(self)
        recovery_layout.addWidget(self.recovery)
        self.updates = UpdatePanel(self, enabled=QApplication.instance().applicationName() == 'TochkaOpory' and '--update-smoke-test' not in sys.argv)
        settings_layout = self.stack.widget(4).widget().layout()
        settings_layout.insertWidget(settings_layout.count() - 1, self.updates)
        top.insertWidget(top.count() - 1, self.updates.banner)
        draft = self.store.data.get('ui_draft', {})
        if isinstance(draft, dict):
            self.trigger.setText(str(draft.get('trigger', '')))
            self.action.setText(str(draft.get('action', '')))
            if type(draft.get('duration')) is int:
                self.duration.setValue(draft['duration'])
            if draft.get('date') == date.today().isoformat():
                self.note.setPlainText(str(draft.get('note', self.note.toPlainText())))
                for slider, key in zip(self.sliders, ('mood', 'fatigue')):
                    if type(draft.get(key)) is int:
                        slider.setValue(draft[key])
        self.navigate(0)

    def build_settings(self):
        lay = self.page('Настройки', 'Звуки, запуск приложения и обновления.')
        sound_box, sound_contents = card()
        self.sound_settings = SoundSettings(self)
        sound_contents.addWidget(self.sound_settings)
        lay.addWidget(sound_box)
        box, contents = card()
        self.autostart_toggle = QCheckBox('Запускать при входе в систему')
        contents.addWidget(self.autostart_toggle)
        contents.addWidget(label('Приложение откроется после входа в вашу учётную запись. '
                                 'После перемещения приложения или Python выключите и снова включите автозапуск.', 'subtitle'))
        self.autostart_status = label('', 'subtitle')
        contents.addWidget(self.autostart_status)
        self.autostart_toggle.setEnabled(self.autostart.supported)
        try:
            self.autostart_toggle.setChecked(self.autostart.enabled() if self.autostart.supported else False)
        except OSError as exc:
            self.autostart_toggle.setEnabled(False)
            self.autostart_status.setText(f'Не удалось проверить автозапуск: {exc}')
        if not self.autostart.supported:
            self.autostart_status.setText('Автозапуск не поддерживается на этой системе.')
        self.autostart_toggle.toggled.connect(self.change_autostart)
        lay.addWidget(box)
        lay.addStretch()

    def change_autostart(self, enabled):
        try:
            self.autostart.set_enabled(enabled)
        except OSError as exc:
            self.autostart_toggle.blockSignals(True)
            self.autostart_toggle.setChecked(not enabled)
            self.autostart_toggle.blockSignals(False)
            self.autostart_status.setText(f'Не удалось изменить автозапуск: {exc}')
            return
        self.autostart_status.setText('Автозапуск включён.' if enabled else 'Автозапуск выключен.')

    def persist(self):
        try:
            self.store.save()
            return True
        except OSError as exc:
            QMessageBox.critical(self, 'Не удалось сохранить', str(exc))
            return False

    def page(self, title, subtitle):
        contents = QWidget()
        layout = QVBoxLayout(contents)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(20)
        layout.addWidget(label(title, 'title'))
        layout.addWidget(label(subtitle, 'subtitle'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(contents)
        self.stack.addWidget(scroll)
        return layout

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.navs):
            b.setChecked(i == index)
        self.refresh()

    def build_overview(self):
        lay = self.page('Вернуться к себе', 'Не нужно менять всё сразу. Выберите одно посильное действие на сегодня.')
        hero, h = card()
        h.addWidget(label('НАЧНИТЕ С МАЛЕНЬКОГО', 'subtitle'))
        h.addWidget(label('Между импульсом и действием\nесть место для выбора.', 'section'))
        h.addWidget(label('Заранее решите, что сделаете в трудный момент. Конкретный сигнал и короткое действие помогают начать.'))
        h.addWidget(button('Создать план «если — то»  →', lambda: self.navigate(1), True))
        lay.addWidget(hero)
        stats = QHBoxLayout()
        self.metrics = []
        for title in ['Активных планов', 'Минут фокуса сегодня', 'Самочувствие сегодня']:
            box, c = card()
            value = label('—', 'metric')
            self.metrics.append(value)
            c.addWidget(value)
            c.addWidget(label(title, 'subtitle'))
            stats.addWidget(box)
        lay.addLayout(stats)
        box, c = card()
        c.addWidget(label('Следующий бережный шаг', 'section'))
        self.next_step = label('')
        c.addWidget(self.next_step)
        c.addWidget(button('Отметить самочувствие', lambda: self.navigate(3)))
        lay.addWidget(box)
        lay.addStretch()

    def build_plans(self):
        lay = self.page('Если → то', 'Привяжите маленькое действие к конкретному моменту, месту или ощущению.')
        box, c = card()
        c.addWidget(label('Новый план', 'section'))
        self.trigger = QLineEdit()
        self.trigger.setPlaceholderText('Если я замечу, что снова открываю ленту…')
        self.action = QLineEdit()
        self.action.setPlaceholderText('…то положу телефон и сделаю три спокойных вдоха')
        c.addWidget(label('ЕСЛИ · ситуация или сигнал', 'subtitle'))
        c.addWidget(self.trigger)
        c.addWidget(label('ТО · одно конкретное действие', 'subtitle'))
        c.addWidget(self.action)
        self.plan_status = label('', 'subtitle')
        c.addWidget(self.plan_status)
        c.addWidget(button('Добавить план', self.add_plan, True))
        lay.addWidget(box)
        self.guide = IntentionsGuide(self.store.data.setdefault('guide', {}))
        self.guide.example_selected.connect(self.use_example)
        self.guide.state_changed.connect(self.save_guide_state)
        lay.addWidget(self.guide)
        lay.addWidget(label('Мои планы', 'section'))
        self.plan_list = QVBoxLayout()
        lay.addLayout(self.plan_list)
        lay.addStretch()

    def save_guide_state(self):
        self.persist()
        # Nested expanding layouts must propagate their new height to the scroll area.
        QTimer.singleShot(0, self.resize_plans_page)

    def resize_plans_page(self):
        page = self.stack.widget(1).widget()
        page.layout().invalidate()
        page.layout().activate()
        page.adjustSize()

    def use_example(self, trigger, action):
        self.trigger.setText(trigger)
        self.action.setText(action)
        self.plan_status.setText('Пример перенесён. Отредактируйте его под себя и нажмите «Добавить план».')
        self.trigger.setFocus()
        self.stack.widget(1).ensureWidgetVisible(self.trigger)

    def add_plan(self):
        trigger, action = self.trigger.text().strip(), self.action.text().strip()
        if not trigger or not action:
            self.plan_status.setText('Заполните обе части: ситуацию и действие.')
            return
        self.store.data['plans'].append({'id': time.time_ns(), 'trigger': trigger, 'action': action, 'done': 0})
        if self.persist():
            self.trigger.clear()
            self.action.clear()
            self.plan_status.setText('План сохранён. Попробуйте мысленно представить этот момент.')
        self.refresh()

    def plan_action(self, pid, remove=False):
        if remove:
            answer = QMessageBox.question(self, 'Удалить план?', 'План будет удалён. Продолжить?')
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.store.data['plans'] = [p for p in self.store.data['plans'] if p['id'] != pid]
        else:
            for p in self.store.data['plans']:
                if p['id'] == pid:
                    p['done'] += 1
        self.persist()
        self.refresh()

    def build_focus(self):
        lay = self.page('Пауза от ленты', 'Заметьте импульс. Отложите реакцию. Выберите, куда направить внимание.')
        box, c = card()
        c.addWidget(label('Одна сессия без скроллинга', 'section'))
        c.addWidget(label('Уберите телефон из поля зрения, отключите уведомления и выберите одно небольшое дело.', 'subtitle'))
        self.duration = QSpinBox()
        self.duration.setRange(1, 120)
        self.duration.setValue(15)
        self.duration.setSuffix(' мин')
        c.addWidget(self.duration)
        self.clock = label('15:00', 'clock')
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.addWidget(self.clock)
        self.focus_status = label('Готовы дать вниманию немного пространства?', 'subtitle')
        c.addWidget(self.focus_status)
        buttons = QHBoxLayout()
        self.start_button = button('Начать сессию', self.start_focus, True)
        self.pause_button = button('Пауза', self.pause_focus)
        self.pause_button.setEnabled(False)
        self.stop_button = button('Завершить досрочно', self.stop_focus)
        self.stop_button.setEnabled(False)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.stop_button)
        c.addLayout(buttons)
        self.duration.valueChanged.connect(lambda v: self.clock.setText(f'{v:02}:00') if not self.remaining else None)
        lay.addWidget(box)
        box, c = card()
        c.addWidget(label('Когда тянет проверить ленту', 'section'))
        c.addWidget(label('1. Назовите происходящее: «Сейчас мне хочется отвлечься».\n\n2. На минуту отложите телефон. Почувствуйте опору под ногами и спокойно подышите.\n\n3. Спросите себя: мне нужен отдых, общение или следующее маленькое действие?'))
        c.addWidget(label('Таймер поддерживает ваше решение; он не блокирует сайты или другие приложения.', 'subtitle'))
        lay.addWidget(box)
        lay.addStretch()

    def start_focus(self):
        if self.recovery.exercise is not None:
            self.focus_status.setText('Сначала завершите восстановление.')
            return
        self.session_minutes = self.duration.value()
        self.remaining = self.session_minutes * 60
        self.deadline = time.monotonic() + self.remaining
        self.duration.setEnabled(False)
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.pause_button.setText('Пауза')
        self.focus_status.setText('Сессия идёт. Вернитесь к выбранному делу — по одному шагу.')
        self.tick()

    def pause_focus(self):
        if self.deadline is not None:
            self.remaining = max(0, self.deadline - time.monotonic())
            self.deadline = None
            self.pause_button.setText('Продолжить')
            self.focus_status.setText('Пауза. Продолжите, когда будете готовы.')
        else:
            self.deadline = time.monotonic() + self.remaining
            self.pause_button.setText('Пауза')
            self.focus_status.setText('Сессия продолжается.')

    def stop_focus(self, completed=False):
        if completed and self.start_button.isEnabled():
            return
        self.deadline = None
        self.remaining = 0
        self.duration.setEnabled(True)
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.clock.setText(f'{self.duration.value():02}:00')
        if completed:
            self.store.data['sessions'].append({'date': date.today().isoformat(), 'minutes': self.session_minutes})
            self.persist()
            self.focus_status.setText('Сессия завершена! Сделайте небольшой перерыв. Время добавлено в обзор.')
            self.sounds.play('focus')
            QApplication.alert(self, 0)
        else:
            self.focus_status.setText('Сессия остановлена. Незавершённое время не добавлено в статистику. Можно начать снова.')
        self.refresh()

    def tick(self):
        if self.deadline is None:
            return
        import math
        self.remaining = max(0, self.deadline - time.monotonic())
        seconds = math.ceil(self.remaining)
        self.clock.setText(f'{seconds // 60:02}:{seconds % 60:02}')
        if self.remaining <= 0:
            self.stop_focus(True)

    def build_wellbeing(self):
        lay = self.page('Как вы сегодня?', 'Короткая отметка без оценок и требований к себе. Одна запись на день.')
        box, c = card()
        c.addWidget(label(datetime.now().strftime('%d.%m.%Y'), 'section'))
        self.sliders = []
        for title, hints in [('Самочувствие', '1 — тяжело · 10 — отлично'), ('Усталость', '1 — полон сил · 10 — очень устал')]:
            val = label('')
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(1, 10)
            slider.valueChanged.connect(lambda v, l=val, t=title: l.setText(f'{t}: {v} / 10'))
            slider.setValue(5)
            c.addWidget(val)
            c.addWidget(slider)
            c.addWidget(label(hints, 'subtitle'))
            self.sliders.append(slider)
        self.note = QTextEdit()
        self.note.setPlaceholderText('Что повлияло на ваше состояние? Что могло бы помочь?')
        self.note.setMaximumHeight(110)
        c.addWidget(self.note)
        self.entry_status = label('', 'subtitle')
        c.addWidget(self.entry_status)
        c.addWidget(button('Сохранить отметку за сегодня', self.save_entry, True))
        lay.addWidget(box)
        existing = self.store.data['entries'].get(date.today().isoformat())
        if existing:
            self.sliders[0].setValue(existing['mood'])
            self.sliders[1].setValue(existing['fatigue'])
            self.note.setPlainText(existing['note'])
        lay.addWidget(label('Последние 7 отметок', 'section'))
        self.history = label('')
        lay.addWidget(self.history)
        lay.addWidget(label('Это инструмент самонаблюдения, а не медицинская оценка.', 'subtitle'))
        lay.addStretch()

    def save_entry(self):
        self.store.data['entries'][date.today().isoformat()] = {'mood': self.sliders[0].value(), 'fatigue': self.sliders[1].value(), 'note': self.note.toPlainText().strip()}
        if self.persist():
            self.entry_status.setText('Сохранено. Повторное сохранение обновит сегодняшнюю запись.')
        self.refresh()

    def refresh(self):
        today = date.today().isoformat()
        entries = self.store.data['entries']
        self.metrics[0].setText(str(len(self.store.data['plans'])))
        self.metrics[1].setText(str(sum(s['minutes'] for s in self.store.data['sessions'] if s['date'] == today)))
        self.metrics[2].setText(f"{entries[today]['mood']} / 10" if today in entries else '—')
        self.next_step.setText('Сегодня вы уже отметили состояние. Выберите посильный план или короткую паузу.' if today in entries else 'Начните с короткой отметки самочувствия. Учитывайте усталость, выбирая нагрузку.')
        while self.plan_list.count():
            item = self.plan_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.store.data['plans']:
            self.plan_list.addWidget(label('Пока нет планов. Например: если закончу завтрак, то открою книгу на одной странице.', 'subtitle'))
        for p in self.store.data['plans']:
            box, c = card()
            c.addWidget(label(f"ЕСЛИ  {p['trigger']}\n\nТО  {p['action']}", 'section'))
            c.addWidget(label(f"Выполнено раз: {p['done']}", 'subtitle'))
            row = QHBoxLayout()
            row.addWidget(button('Сделано +1', lambda checked=False, pid=p['id']: self.plan_action(pid)))
            row.addWidget(button('Удалить', lambda checked=False, pid=p['id']: self.plan_action(pid, True)))
            c.addLayout(row)
            self.plan_list.addWidget(box)
        lines = []
        for day, e in sorted(entries.items(), reverse=True)[:7]:
            lines.append(f"{day}   ·   Самочувствие {e['mood']}/10   ·   Усталость {e['fatigue']}/10" + (f"\n{e['note']}" if e['note'] else ''))
        self.history.setText('\n\n'.join(lines) if lines else 'Здесь появятся ваши отметки. Начните с сегодняшнего дня.')
        self.history.setTextFormat(Qt.TextFormat.PlainText)

    def closeEvent(self, event):
        if self.remaining:
            answer = QMessageBox.question(self, 'Сессия ещё не завершена', 'Закрыть приложение? Текущая сессия не будет сохранена.')
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self.recovery.exercise is not None:
            self.recovery.finish('interrupted')
        if self.recovery.record and not self.recovery.save_result():
            event.ignore()
            return
        self.recovery.stop_audio()
        self.store.data['ui_draft'] = {'trigger': self.trigger.text(), 'action': self.action.text(), 'duration': self.duration.value(), 'date': date.today().isoformat(), 'note': self.note.toPlainText(), 'mood': self.sliders[0].value(), 'fatigue': self.sliders[1].value()}
        if not self.persist():
            event.ignore()
            return
        self.updates.shutdown()
        self.sounds.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('TochkaOpory')
    app.setOrganizationName('MotivationApp')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    path = Path(os.environ.get('TOCHKA_UPDATE_DATA') or (Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / 'data.json'))
    smoke = '--update-smoke-test' in sys.argv
    if smoke:
        path = Path(sys.argv[sys.argv.index('--update-smoke-test') + 1])
    try:
        store = Store(path)
    except RuntimeError as exc:
        QMessageBox.critical(None, 'Ошибка данных', str(exc))
        return 1
    window = Window(store)
    window.show()
    if smoke:
        QTimer.singleShot(200, app.quit)
    elif os.environ.get('TOCHKA_UPDATE_TRIAL'):
        from update_bootstrap import atomic
        QTimer.singleShot(1500, lambda: atomic(Path(os.environ['TOCHKA_UPDATE_TRIAL']), {'ready': True}))
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
