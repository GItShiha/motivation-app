"""One-shot, same-session KWin keepAbove request, isolated from the GUI."""
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
from PySide6.QtCore import QCoreApplication, QObject, Slot, QTimer, ClassInfo
from PySide6.QtDBus import QDBusConnection, QDBusInterface

INTERFACE = 'local.TochkaOpory.WindowPin'


def script_source(pid, caption, enabled, service):
    return '''var matched = false;
var confirmed = false;
var windows = workspace.windowList();
for (var i = 0; i < windows.length; ++i) {
    var w = windows[i];
    if (w.pid === %d && w.caption === %s) {
        matched = true;
        w.keepAbove = %s;
        confirmed = (w.keepAbove === %s);
        break;
    }
}
callDBus(%s, '/Result', %s, 'result', confirmed, matched ? 'applied' : 'not-found');
''' % (pid, json.dumps(caption), str(enabled).lower(), str(enabled).lower(), json.dumps(service), json.dumps(INTERFACE))


@ClassInfo(**{'D-Bus Interface': INTERFACE})
class Result(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.success = False

    @Slot(bool, str)
    def result(self, success, message):
        self.success = success
        self.app.exit(0 if success else 1)


def main():
    app = QCoreApplication(sys.argv)
    if len(sys.argv) != 4 or sys.argv[2] not in ('0', '1'):
        return 1
    pid, enabled, caption = int(sys.argv[1]), sys.argv[2] == '1', sys.argv[3]
    bus = QDBusConnection.sessionBus()
    service = 'local.TochkaOpory.Pin.p' + str(os.getpid()) + '_' + uuid.uuid4().hex
    result = Result(app)
    name = 'tochka-pin-' + uuid.uuid4().hex
    kwin = QDBusInterface('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting', bus)
    kwin.setTimeout(1500)
    try:
        if not bus.isConnected() or not kwin.isValid() or not bus.registerService(service) or not bus.registerObject('/Result', result, QDBusConnection.RegisterOption.ExportAllSlots):
            raise RuntimeError('KWin scripting is unavailable')
        with tempfile.TemporaryDirectory(prefix='tochka-pin-') as folder:
            script = Path(folder) / 'pin.js'
            script.write_text(script_source(pid, caption, enabled, service), encoding='utf-8')
            reply = kwin.call('loadScript', str(script), name)
            values = reply.arguments()
            if reply.errorName() or not values or type(values[0]) is not int or values[0] < 0:
                raise RuntimeError('KWin rejected script')
            runner = QDBusInterface('org.kde.KWin', '/Scripting/Script' + str(values[0]), 'org.kde.kwin.Script', bus)
            runner.setTimeout(1500)
            # Queue execution so that callback delivery happens inside app.exec().
            QTimer.singleShot(0, lambda: runner.asyncCall('run'))
            QTimer.singleShot(4500, lambda: app.exit(1))
            app.exec()
        print(json.dumps({'ok': result.success}))
        return 0 if result.success else 1
    except (RuntimeError, OSError, ValueError):
        print(json.dumps({'ok': False}))
        return 1
    finally:
        if kwin.isValid():
            kwin.call('unloadScript', name)
        bus.unregisterObject('/Result')
        bus.unregisterService(service)


if __name__ == '__main__':
    sys.exit(main())
