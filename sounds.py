"""Local, finite timer sounds. Qt Multimedia is optional at runtime."""
from pathlib import Path

import sys
from PySide6.QtCore import QObject, QProcess, Signal, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QComboBox, QSlider, QPushButton
from PySide6.QtCore import Qt

TONES = {'soft': 'Мягкий', 'bell': 'Колокольчик', 'two_notes': 'Две ноты'}
CATEGORIES = {'focus': 'Фокус-сессии', 'recovery': 'Перерывы и восстановление', 'tickets_break': 'Перерывы по тикетам', 'tickets_goal': 'Достижение нормы тикетов', 'sleep': 'Вечерние практики'}


def preferences(raw):
    raw = raw if isinstance(raw, dict) else {}
    volume = raw.get('volume', 35)
    categories = raw.get('categories', {})
    categories = categories if isinstance(categories, dict) else {}
    tone = raw.get('tone')
    return {'enabled': raw.get('enabled', True) is not False,
            'volume': max(0, min(100, volume)) if type(volume) is int else 35,
            'tone': tone if isinstance(tone, str) and tone in TONES else 'soft',
            'categories': {key: categories.get(key, True) is not False for key in CATEGORIES}}


class TimerSounds(QObject):
    status_changed = Signal(str)

    def __init__(self, store, parent=None, process_factory=None):
        super().__init__(parent)
        self.settings = preferences(store.data.get('sounds'))
        self.process_factory = process_factory or QProcess
        self.process = None

    def apply(self, settings):
        self.settings = preferences(settings)
        self.stop()

    def stop(self):
        if self.process is not None:
            process, self.process = self.process, None
            process.kill()

    def play(self, category=None, tone=None):
        settings = dict(self.settings)
        if tone in TONES:
            settings['tone'] = tone
        if not settings['enabled'] or settings['volume'] == 0:
            return
        if category is not None and not settings['categories'].get(category, False):
            return
        self.stop()
        try:
            process = self.process_factory(self)
            self.process = process
            process.setProgram(sys.executable)
            process.setArguments([str(Path(__file__).with_name('sound_worker.py')), settings['tone'], str(settings['volume'])])
            process.setStandardOutputFile(QProcess.nullDevice())
            process.setStandardErrorFile(QProcess.nullDevice())
            process.finished.connect(lambda code, status: self.finished(process, code))
            process.errorOccurred.connect(lambda error: self.failed(process, error))
            self.watch(process)
            process.start()
        except (RuntimeError, OSError):
            self.status_changed.emit('Звук недоступен. Визуальные уведомления продолжат работать.')

    def watch(self, process):
        watchdog = QTimer(process)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: self.timeout(process))
        watchdog.start(6500)

    def timeout(self, process):
        if self.process is process:
            process.kill()

    def finished(self, process, code):
        if self.process is process:
            self.process = None
            self.status_changed.emit('' if code == 0 else 'Не удалось воспроизвести сигнал. Проверьте звуковое устройство.')
        process.deleteLater()

    def failed(self, process, error):
        if self.process is process:
            self.status_changed.emit('Звук недоступен. Визуальные уведомления продолжат работать.')
        if error == QProcess.ProcessError.FailedToStart:
            if self.process is process:
                self.process = None
            process.deleteLater()


class SoundSettings(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        settings = window.sounds.settings
        lay = QVBoxLayout(self)
        heading = QLabel('Звуки таймеров')
        heading.setObjectName('section')
        lay.addWidget(heading)
        self.enabled = QCheckBox('Звуковые уведомления')
        self.enabled.setChecked(settings['enabled'])
        lay.addWidget(self.enabled)
        self.volume_label = QLabel()
        lay.addWidget(self.volume_label)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(settings['volume'])
        self.volume.setAccessibleName('Громкость уведомлений')
        lay.addWidget(self.volume)
        self.tone = QComboBox()
        for key, title in TONES.items():
            self.tone.addItem(title, key)
        self.tone.setCurrentIndex(list(TONES).index(settings['tone']))
        self.tone.setAccessibleName('Звуковой сигнал')
        lay.addWidget(self.tone)
        self.categories = {}
        for key, title in CATEGORIES.items():
            toggle = QCheckBox(title)
            toggle.setChecked(settings['categories'][key])
            self.categories[key] = toggle
            lay.addWidget(toggle)
            toggle.toggled.connect(self.changed)
        self.preview = QPushButton('Прослушать')
        self.preview.clicked.connect(lambda: window.sounds.play())
        lay.addWidget(self.preview)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        window.sounds.status_changed.connect(self.status.setText)
        self.enabled.toggled.connect(self.changed)
        self.volume.valueChanged.connect(self.changed)
        self.tone.currentIndexChanged.connect(self.changed)
        self.update_controls()

    def update_controls(self):
        self.volume_label.setText(f'Громкость: {self.volume.value()}%')
        self.preview.setEnabled(self.enabled.isChecked() and self.volume.value() > 0)

    def changed(self, *args):
        settings = {'enabled': self.enabled.isChecked(), 'volume': self.volume.value(),
                    'tone': self.tone.currentData(), 'categories': {k: v.isChecked() for k, v in self.categories.items()}}
        self.window.sounds.apply(settings)
        self.window.store.data['sounds'] = settings
        self.window.persist()
        self.update_controls()
