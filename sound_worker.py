"""One-shot Qt playback, isolated even from native audio backend failures."""
from pathlib import Path
import sys
from PySide6.QtCore import QCoreApplication, QTimer, QUrl


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('soft', 'bell', 'two_notes'):
        return 1
    volume = max(0, min(100, int(sys.argv[2])))
    if sys.platform.startswith('linux'):
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    app = QCoreApplication(sys.argv)
    try:
        from PySide6.QtMultimedia import QSoundEffect
        sound = QSoundEffect()
        sound.setLoopCount(1)
        sound.setVolume(volume / 100)
        started = False

        def loaded():
            nonlocal started
            if sound.status() == QSoundEffect.Status.Error:
                app.exit(1)
            elif sound.status() == QSoundEffect.Status.Ready and not started:
                started = True
                sound.play()

        def playing():
            if started and not sound.isPlaying():
                app.quit()

        sound.statusChanged.connect(loaded)
        sound.playingChanged.connect(playing)
        sound.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parent / 'assets/sounds' / (sys.argv[1] + '.wav'))))
        # A broken or disconnected device must not leave an idle worker forever.
        QTimer.singleShot(5000, lambda: app.exit(1))
        return app.exec()
    except (ImportError, RuntimeError, OSError, ValueError):
        return 1


if __name__ == '__main__':
    sys.exit(main())
