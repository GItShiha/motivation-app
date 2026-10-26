"""Recovery page; no network or modal exercise prompts."""
from datetime import datetime
import math
import time
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QCheckBox, QStackedWidget, QFileDialog, QApplication)
from recovery import METHODS, BY_KEY, STATES, METRICS, ExerciseTimer, history, statistics, recommend


def text(value):
    w = QLabel(value)
    w.setWordWrap(True)
    w.setTextFormat(Qt.TextFormat.PlainText)
    return w


def btn(title, callback):
    b = QPushButton(title)
    b.clicked.connect(callback)
    return b


class Breath(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(160)
        self.phase = 0
        self.inhale, self.exhale = 4, 6

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cycle = self.inhale + self.exhale
        pos = self.phase % cycle
        progress = pos / self.inhale if pos < self.inhale else 1 - (pos - self.inhale) / self.exhale
        radius = 28 + 35 * (0.5 - 0.5 * math.cos(math.pi * progress))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#a99aff'))
        from PySide6.QtCore import QPointF
        p.drawEllipse(QPointF(self.width() / 2, 75), radius, radius)
        p.setPen(QColor('#e8eaf0'))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, 'Вдох' if pos < self.inhale else 'Выдох')


class Ratings(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.mode = QComboBox()
        self.mode.addItems(['Пропустить оценку', 'Быстро: бодрость и готовность', 'Все четыре показателя'])
        layout.addWidget(self.mode)
        self.fields = {}
        for key, title in METRICS.items():
            row = QWidget()
            line = QHBoxLayout(row)
            line.addWidget(text(title))
            value = QSpinBox()
            value.setRange(-1, 10)
            value.setSpecialValueText('Пропустить')
            value.setValue(-1)
            line.addWidget(value)
            self.fields[key] = (row, value)
            layout.addWidget(row)
        self.mode.currentIndexChanged.connect(self.update_fields)
        self.update_fields()

    def update_fields(self):
        for key, (row, _) in self.fields.items():
            row.setVisible(self.mode.currentIndex() == 2 or (self.mode.currentIndex() == 1 and key in ('energy', 'readiness')))

    def scores(self):
        return {k: v.value() for k, (_, v) in self.fields.items() if v.value() >= 0 and (self.mode.currentIndex() == 2 or (self.mode.currentIndex() == 1 and k in ('energy', 'readiness')))}

    def reset(self):
        self.mode.setCurrentIndex(0)
        for _, v in self.fields.values():
            v.setValue(-1)


class RecoveryPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.exercise = None
        self.record = None
        self.player = None
        self.current = None
        self.root = QVBoxLayout(self)
        self.root.addWidget(text('Методы не заменяют полноценный сон. При стойкой или необъяснимой усталости обратитесь за медицинской помощью.'))
        self.pages = QStackedWidget()
        self.root.addWidget(self.pages)
        self.build_library()
        self.build_exercise()
        self.build_result()
        self.root.addWidget(btn('Что помогает мне лучше всего', self.show_stats))
        self.stats = text('')
        self.stats.hide()
        self.root.addWidget(self.stats)
        self.pulse = QTimer(self)
        self.pulse.setInterval(40)
        self.pulse.timeout.connect(self.tick)
        self.pulse.start()
        self.update_recommendations()

    def panel(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        self.pages.addWidget(w)
        return layout

    def build_library(self):
        lay = self.panel()
        lay.addWidget(text('Что сейчас мешает тебе работать?'))
        self.state = QComboBox()
        self.state.addItems(STATES)
        lay.addWidget(self.state)
        self.time = QComboBox()
        for n in (2, 5, 10, 20):
            self.time.addItem(f'{n} мин', n)
        self.time.setCurrentIndex(1)
        lay.addWidget(self.time)
        self.reasons = text('')
        lay.addWidget(self.reasons)
        self.methods = QComboBox()
        lay.addWidget(self.methods)
        self.details_toggle = QCheckBox('Описание, шаги и ограничения')
        lay.addWidget(self.details_toggle)
        self.details = text('')
        self.details.hide()
        lay.addWidget(self.details)
        self.details_toggle.toggled.connect(self.details.setVisible)
        self.duration = QSpinBox()
        self.duration.setSuffix(' мин')
        lay.addWidget(self.duration)
        lay.addWidget(text('С какого действия продолжите работу? (необязательно)'))
        self.plan = QLineEdit()
        self.plan.setPlaceholderText('Например: открыть один тикет')
        lay.addWidget(self.plan)
        lay.addWidget(btn('Выбрать из планов «Если → то»', self.load_plans))
        self.plans = QComboBox()
        self.plans.hide()
        self.plans.activated.connect(lambda i: self.plan.setText(self.plans.itemData(i) or ''))
        lay.addWidget(self.plans)
        self.before = Ratings()
        lay.addWidget(self.before)
        self.message = text('')
        lay.addWidget(self.message)
        lay.addWidget(btn('Начать', self.start))
        self.state.currentIndexChanged.connect(self.update_recommendations)
        self.time.currentIndexChanged.connect(self.update_recommendations)
        self.methods.currentIndexChanged.connect(self.select_method)

    def update_recommendations(self):
        recommended = recommend(self.state.currentIndex(), self.time.currentData(), history(self.window.store.data))
        self.methods.blockSignals(True)
        self.methods.clear()
        for method in recommended + [m for m in METHODS if m not in recommended]:
            self.methods.addItem(('Рекомендуем · ' if method in recommended else 'Библиотека · ') + method.name, method.key)
        self.methods.blockSignals(False)
        self.select_method()
        hint = 'Оцените сон, голод, жажду и потребность в отдыхе. ' if self.state.currentIndex() == 4 else ''
        if self.state.currentIndex() == 3:
            hint += 'Можно также выбрать короткую фокус-сессию после одного действия. '
        self.reasons.setText(hint + 'Рекомендации учитывают состояние и время. Все методы доступны вручную; личный приоритет меняется после 5 парных оценок. Для сна нужно около 30 минут с подготовкой и пробуждением.')

    def select_method(self):
        method = BY_KEY.get(self.methods.currentData())
        if not method:
            return
        minimum = 30 if method.key == 'nap' else method.minimum
        self.duration.setRange(minimum, method.maximum)
        self.duration.setValue(min(method.maximum, max(minimum, self.time.currentData())))
        self.details.setText(f'Почему это может помочь: {method.mechanism}\n\n' + '\n'.join(f'{i}. {s}' for i, s in enumerate(method.steps, 1)) + '\n\n' + method.caution)

    def load_plans(self):
        self.plans.clear()
        self.plans.addItem('Выберите план', '')
        for p in self.window.store.data['plans']:
            self.plans.addItem(f"Если {p['trigger']} → {p['action']}", p['action'])
        self.plans.show()

    def build_exercise(self):
        lay = self.panel()
        self.heading = text('')
        lay.addWidget(self.heading)
        self.clock = text('')
        self.clock.setObjectName('clock')
        lay.addWidget(self.clock)
        self.breath = Breath()
        lay.addWidget(self.breath)
        self.tempo = QComboBox()
        self.tempo.addItem('Вдох 4 с · выдох 6 с', (4, 6))
        self.tempo.addItem('Вдох 3 с · выдох 4 с', (3, 4))
        self.tempo.addItem('Вдох 5 с · выдох 6 с', (5, 6))
        self.tempo.currentIndexChanged.connect(self.change_tempo)
        lay.addWidget(self.tempo)
        self.step = text('')
        lay.addWidget(self.step)
        lay.addWidget(btn('Следующий шаг', self.next_step))
        self.audio = QWidget()
        audio_layout = QVBoxLayout(self.audio)
        audio_layout.addWidget(btn('Выбрать локальный аудиофайл', self.choose_audio))
        audio_layout.addWidget(btn('Воспроизвести', self.play_audio))
        audio_layout.addWidget(btn('Остановить звук', self.stop_audio))
        self.audio_status = text('')
        audio_layout.addWidget(self.audio_status)
        lay.addWidget(self.audio)
        lay.addWidget(btn('Закончить досрочно', lambda: self.finish('interrupted')))
        lay.addWidget(btn('Отменить перерыв', lambda: self.finish('cancelled')))

    def change_tempo(self):
        self.breath.inhale, self.breath.exhale = self.tempo.currentData()
        self.breath.phase = 0
        self.breath_origin = time.monotonic()

    def start(self):
        if self.window.sleep.ledger is not None and self.window.sleep.practice.exercise is not None:
            self.message.setText('Сначала завершите вечернюю практику.')
            return
        if self.window.remaining:
            self.message.setText('Сначала завершите текущую фокус-сессию в разделе «Пауза от ленты».')
            return
        self.message.clear()
        self.current = BY_KEY[self.methods.currentData()]
        self.exercise = ExerciseTimer(self.duration.value() * 60)
        self.record = {'method': self.current.key, 'state': self.state.currentIndex(), 'started_at': datetime.now().astimezone().isoformat(), 'planned_seconds': self.exercise.seconds, 'before': self.before.scores(), 'after': {}, 'plan': self.plan.text().strip(), 'status': 'running'}
        self.heading.setText(self.current.name + '\n' + self.current.caution)
        self.step_index = 0
        self.update_step()
        self.breath.setVisible(self.current.key == 'breath')
        self.tempo.setVisible(self.current.key == 'breath')
        self.audio.setVisible(self.current.key == 'audio')
        self.change_tempo()
        self.pages.setCurrentIndex(1)
        self.tick()

    def update_step(self):
        self.step.setText(f'Шаг {self.step_index + 1} из {len(self.current.steps)}\n{self.current.steps[self.step_index]}')

    def next_step(self):
        if self.current:
            self.step_index = min(self.step_index + 1, len(self.current.steps) - 1)
            self.update_step()

    def tick(self):
        if self.exercise is None:
            return
        remaining = self.exercise.remaining
        self.clock.setText(f'{remaining // 60:02}:{remaining % 60:02}')
        if self.current.key == 'breath':
            self.breath.phase = time.monotonic() - self.breath_origin
            self.breath.update()
        if remaining == 0:
            self.finish('completed')
            QApplication.alert(self.window, 0)

    def finish(self, status):
        if self.exercise is None:
            return
        self.record.update(status=status, elapsed_seconds=round(self.exercise.elapsed, 2), ended_at=datetime.now().astimezone().isoformat())
        self.exercise = None
        self.stop_audio()
        self.after.reset()
        self.after.mode.setCurrentIndex(self.before.mode.currentIndex())
        self.result.setText(('Перерыв завершён.' if status == 'completed' else 'Перерыв остановлен. Продолжите, когда будете готовы.') + '\nСледующий шаг: ' + (self.record['plan'] or 'выберите одно посильное действие'))
        self.saved = False
        self.pages.setCurrentIndex(2)
        self.save_result()
        if status == 'completed':
            self.window.sounds.play('recovery')

    def build_result(self):
        lay = self.panel()
        self.result = text('')
        lay.addWidget(self.result)
        lay.addWidget(text('Как вы сейчас? Можно пропустить оценку.'))
        self.after = Ratings()
        lay.addWidget(self.after)
        self.save_status = text('')
        lay.addWidget(self.save_status)
        lay.addWidget(btn('Сохранить оценку', self.save_result))
        lay.addWidget(btn('Вернуться к работе', self.return_work))
        lay.addWidget(btn('Начать фокус-сессию по желанию', self.focus))
        lay.addWidget(btn('Выбрать другой метод', self.new_method))

    def save_result(self):
        if not self.record:
            return True
        self.record['after'] = self.after.scores()
        data = self.window.store.data
        if 'recovery' in data and not isinstance(data['recovery'], list):
            self.save_status.setText('История имеет неверный формат. Существующие данные оставлены без изменений.')
            return False
        records = data.setdefault('recovery', [])
        if not self.saved:
            records.append(self.record)
            self.saved = True
        # Non-modal, retryable persistence; never discard prior records.
        try:
            self.window.store.save()
        except OSError:
            self.save_status.setText('Не удалось сохранить. Повторите сохранение перед выходом.')
            return False
        self.save_status.setText('Сохранено локально.')
        return True

    def return_work(self):
        if self.save_result():
            self.window.navigate(2)
            self.window.focus_status.setText('Следующий шаг: ' + (self.record['plan'] or 'одно посильное действие'))

    def focus(self):
        if self.save_result():
            self.return_work()
            if not self.window.remaining:
                self.window.start_focus()

    def new_method(self):
        if self.save_result():
            self.before.reset()
            self.pages.setCurrentIndex(0)
            self.update_recommendations()

    def show_stats(self):
        lines = ['Что помогает мне лучше всего', 'Разница самооценок не доказывает причинную эффективность. Усталость учитывается с обратным знаком. Только завершённые перерывы с парными оценками входят в среднее.']
        records = history(self.window.store.data)
        for days in (7, 30):
            lines.append(f'\nПоследние {days} дней:')
            stats = statistics(records, days=days)
            for method in METHODS:
                g = stats.get(method.key, {'uses': 0, 'rated': 0, 'mean': None, 'improved': None})
                result = f"средняя разница {g['mean']:+.1f}; улучшение {g['improved']:.0%}" if g['rated'] else 'нет парных оценок'
                lines.append(f"{method.name}: {g['uses']} использований, {g['rated']} оценок; {result}" + (' · мало наблюдений' if g['rated'] < 5 else ''))
        lines.append('\nПо состояниям (вся история):')
        for i, state in enumerate(STATES):
            rated = [(key, g) for key, g in statistics(records, state=i).items() if g['rated'] >= 5]
            if rated:
                key, g = max(rated, key=lambda pair: pair[1]['mean'])
                lines.append(f"{state}: наибольшая средняя субъективная разница — {BY_KEY[key].name} ({g['mean']:+.1f}, n={g['rated']})")
            else:
                lines.append(state + ': пока недостаточно наблюдений')
        self.stats.setText('\n'.join(lines))
        self.stats.show()

    def choose_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Выберите локальный аудиофайл', '', 'Аудио (*.mp3 *.wav *.ogg *.flac *.m4a)')
        if not path:
            return
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            if self.player is None:
                self.player = QMediaPlayer(self)
                self.output = QAudioOutput(self)
                self.output.setVolume(0.4)
                self.player.setAudioOutput(self.output)
                self.player.errorOccurred.connect(lambda *args: self.audio_status.setText('Не удалось воспроизвести файл. Выберите другой формат.'))
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(path))
            self.audio_status.setText('Файл выбран. Нажмите «Воспроизвести».')
        except ImportError:
            self.audio_status.setText('Qt Multimedia недоступен; можно использовать внешний проигрыватель.')

    def play_audio(self):
        if self.player:
            self.player.play()

    def stop_audio(self):
        if self.player:
            self.player.stop()
