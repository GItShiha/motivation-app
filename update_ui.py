"""Non-modal update settings and notifications; Git runs only in child processes."""
import json
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QComboBox, QPushButton, QMessageBox
from update_bootstrap import read_json, state_dir


class UpdatePanel(QWidget):
    def __init__(self, window, enabled=True):
        super().__init__()
        self.window = window
        self.root_path = Path(__file__).resolve().parent
        self.process = None
        self.target = None
        self.manual = False
        self.pending = False
        self.gate = None
        self.installer = None
        settings = window.store.data.get('updates', {})
        self.settings = dict(settings) if isinstance(settings, dict) else {}
        for key in ('last_check', 'dismissed', 'current'):
            if not isinstance(self.settings.get(key, ''), str):
                self.settings.pop(key, None)
        if type(self.settings.get('hours')) is not int or self.settings['hours'] not in (1, 6, 24):
            self.settings['hours'] = 6
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('Обновления'))
        self.auto = QCheckBox('Автоматическая проверка')
        self.auto.setChecked(self.settings.get('auto', True) is not False)
        self.notify = QCheckBox('Уведомления')
        self.notify.setChecked(self.settings.get('notify', True) is not False)
        self.defer = QCheckBox('Отложить перезапуск до завершения фокус-сессии')
        self.defer.setChecked(self.settings.get('defer', True) is not False)
        self.interval = QComboBox()
        for hours in (1, 6, 24):
            self.interval.addItem(f'Каждые {hours} ч', hours)
        self.interval.setCurrentIndex({1: 0, 6: 1, 24: 2}.get(self.settings.get('hours'), 1))
        self.status = QLabel('Текущая ревизия: определяется при проверке\nПоследняя успешная проверка: ' + self.settings.get('last_check', 'ещё не выполнялась'))
        self.status.setWordWrap(True)
        self.check_button = QPushButton('Проверить сейчас')
        self.check_button.clicked.connect(lambda: self.check(True))
        for w in (self.auto, self.interval, self.notify, self.defer, self.check_button, self.status):
            lay.addWidget(w)
        self.banner = QWidget()
        banner_layout = QVBoxLayout(self.banner)
        self.notice = QLabel('Доступно обновление „Точки опоры“')
        self.notice.setWordWrap(True)
        banner_layout.addWidget(self.notice)
        self.install_button = QPushButton('Обновить')
        self.install_button.clicked.connect(self.confirm)
        banner_layout.addWidget(self.install_button)
        later = QPushButton('Позже')
        later.clicked.connect(self.later)
        banner_layout.addWidget(later)
        details = QPushButton('Подробнее')
        details.clicked.connect(self.show_details)
        banner_layout.addWidget(details)
        self.banner.hide()
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.check(False))
        self.focus_timer = QTimer(self)
        self.focus_timer.timeout.connect(self.update_focus)
        self.focus_timer.start(500)
        for control in (self.auto, self.notify, self.defer):
            control.toggled.connect(self.configure)
        self.interval.currentIndexChanged.connect(self.configure)
        self.configure(save=False)
        if not enabled or not sys.platform.startswith('linux'):
            self.timer.stop()
            self.check_button.setEnabled(False)
        else:
            QTimer.singleShot(100, self.read_revision)
            QTimer.singleShot(2500, lambda: self.check(False) if self.auto.isChecked() else None)
            try:
                journal = read_json(state_dir() / 'transaction.json', {})
                if journal.get('phase') == 'failed':
                    error = journal.get('error', 'Установка не завершена; сохранена предыдущая версия.')
                    self.status.setText(error)
                    self.window.statusBar().showMessage(error)
            except (OSError, ValueError):
                self.status.setText('Журнал обновлений недоступен; проверьте каталог обновлений.')

    def read_revision(self):
        self.revision_process = QProcess(self)
        self.revision_process.setProgram(sys.executable)
        self.revision_process.setArguments([str(self.root_path / 'updater.py'), 'revision', '--root', str(self.root_path)])
        def done(*args):
            try:
                value = json.loads(bytes(self.revision_process.readAllStandardOutput()))
                self.settings['current'] = value['current']
                self.status.setText('Текущая ревизия: ' + value['current'][:12] + '\nПоследняя успешная проверка: ' + self.settings.get('last_check', 'ещё не выполнялась'))
            except (ValueError, KeyError):
                pass
            self.revision_process.deleteLater()
        self.revision_process.finished.connect(done)
        self.revision_process.start()

    def configure(self, *args, save=True):
        self.settings.update(auto=self.auto.isChecked(), notify=self.notify.isChecked(), defer=self.defer.isChecked(), hours=self.interval.currentData())
        self.timer.setInterval(self.interval.currentData() * 3600000)
        if self.auto.isChecked():
            self.timer.start()
        else:
            self.timer.stop()
        if not self.notify.isChecked():
            self.banner.hide()
        if save:
            self.persist()

    def persist(self):
        self.window.store.data['updates'] = self.settings
        self.window.persist()

    def check(self, manual=False):
        if self.process is not None:
            return
        self.manual = manual
        self.check_button.setEnabled(False)
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments([str(self.root_path / 'updater.py'), 'check', '--root', str(self.root_path)])
        self.process.finished.connect(self.checked)
        self.process.errorOccurred.connect(self.process_error)
        self.process.start()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.status.setText('Не удалось запустить проверку обновлений.')
            self.process.deleteLater()
            self.process = None
            self.check_button.setEnabled(True)

    def checked(self, code, status):
        process = self.process
        if process is None:
            return
        try:
            result = json.loads(bytes(process.readAllStandardOutput()))
        except (ValueError, UnicodeError):
            result = {'error': 'Проверка недоступна. Повторите позже.'}
        process.deleteLater()
        self.process = None
        self.check_button.setEnabled(True)
        if 'error' in result:
            self.status.setText(result['error'] + '\nТекущая ревизия: ' + self.settings.get('current', 'не определена')[:12] + '\nПоследняя успешная проверка: ' + self.settings.get('last_check', 'не выполнялась'))
            return
        self.settings['last_check'] = result['checked_at']
        self.settings['current'] = result['current']
        self.status.setText('Текущая ревизия: ' + result['current'][:12] + '\nПоследняя успешная проверка: ' + result['checked_at'])
        self.target = result['target'] if result['available'] else None
        if self.manual and self.target:
            self.settings.pop('dismissed', None)
        self.banner.setVisible(bool(self.target) and (self.manual or (self.notify.isChecked() and self.settings.get('dismissed') != self.target)))
        self.persist()
        self.update_focus()

    def later(self):
        self.settings['dismissed'] = self.target
        self.pending = False
        self.banner.hide()
        self.persist()

    def show_details(self):
        self.notice.setText('Доступно обновление „Точки опоры“\nРевизия: ' + (self.target or '') + '\nИсточник: github.com/GItShiha/motivation-app, main.\nБудут подготовлены отдельное окружение, копия данных и точка возврата. Установка требует подтверждения. Локальные изменения не перезаписываются.')

    def busy(self):
        return bool(self.window.remaining or self.window.recovery.exercise is not None or (self.window.sleep.ledger is not None and self.window.sleep.practice.exercise is not None))

    def update_focus(self):
        self.install_button.setEnabled(not self.busy())
        if self.target and self.busy():
            self.pending = self.settings.get('dismissed') != self.target
            self.notice.setText('Доступно обновление „Точки опоры“ · установка после текущей сессии.')
        elif self.pending and self.target:
            self.pending = False
            if self.defer.isChecked() and self.notify.isChecked() and self.settings.get('dismissed') != self.target:
                self.banner.show()
                self.notice.setText('Сессия завершена. Доступно обновление „Точки опоры“.')

    def confirm(self):
        if not self.target or self.busy():
            return
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle('Установить обновление?')
        dialog.setText('Приложение закроется, установит зависимости и проверит новую версию.\nРевизия: ' + self.target[:12] + '\nПри ошибке будет запущена предыдущая версия. Данные автоматически не заменяются.')
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Yes).setText('Установить')
        dialog.button(QMessageBox.StandardButton.Cancel).setText('Отмена')
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.finished.connect(lambda result: self.install() if result == QMessageBox.StandardButton.Yes else None)
        dialog.open()
        self.dialog = dialog

    def install(self):
        if self.busy() or self.installer is not None or not self.window.persist():
            return
        read_fd, write_fd = os.pipe()
        try:
            self.installer = subprocess.Popen([sys.executable, str(self.root_path / 'updater.py'), 'install', '--root', str(self.root_path), '--target', self.target, '--data', str(self.window.store.path.resolve()), '--wait-fd', str(read_fd)], pass_fds=(read_fd,), start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            os.close(read_fd)
            os.close(write_fd)
            self.status.setText('Не удалось запустить установщик. Приложение продолжает работу.')
            return
        os.close(read_fd)
        # Deliberately retained until process exit. Installer must not race GUI saves.
        self.gate = write_fd
        if not self.window.close():
            self.installer.terminate()
            self.installer = None
            os.close(self.gate)
            self.gate = None

    def shutdown(self):
        self.timer.stop()
        if self.process is not None:
            self.process.kill()
