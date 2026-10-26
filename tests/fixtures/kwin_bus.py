"""Session-bus fixture for the worker callback protocol; not a KWin emulator."""
import json
import re
from pathlib import Path
import sys
from PySide6.QtCore import QCoreApplication, QObject, Slot, ClassInfo, QProcess, QTimer
from PySide6.QtDBus import QDBusConnection, QDBusInterface

app = QCoreApplication(sys.argv)
bus = QDBusConnection.sessionBus()
service = ''

@ClassInfo(**{'D-Bus Interface': 'org.kde.kwin.Scripting'})
class Scripting(QObject):
    @Slot(str, str, result=int)
    def loadScript(self, path, name):
        global service
        source = Path(path).read_text()
        service = json.loads(re.search(r'callDBus\(("[^"]+")', source).group(1))
        return 0

    @Slot(str, result=bool)
    def unloadScript(self, name):
        return True

@ClassInfo(**{'D-Bus Interface': 'org.kde.kwin.Script'})
class Script(QObject):
    @Slot()
    def run(self):
        QDBusInterface(service, '/Result', 'local.TochkaOpory.WindowPin', bus).asyncCallWithArgumentList('result', [True, 'applied'])

scripting, script = Scripting(), Script()
assert bus.registerService('org.kde.KWin')
assert bus.registerObject('/Scripting', scripting, QDBusConnection.RegisterOption.ExportAllSlots)
assert bus.registerObject('/Scripting/Script0', script, QDBusConnection.RegisterOption.ExportAllSlots)
worker = QProcess()
worker.setProgram(sys.executable)
worker.setArguments([sys.argv[1], '1234', '1', 'Точка опоры · Тикеты'])
def done(code, status):
    print(bytes(worker.readAllStandardOutput()).decode(), end='')
    app.exit(code)
worker.finished.connect(done)
worker.start()
QTimer.singleShot(10000, lambda: (worker.kill(), app.exit(2)))
sys.exit(app.exec())
