"""Stable Linux launcher and durable update state. Standard library only."""
import json
import os
from pathlib import Path
import sys


def state_dir():
    base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    if not base.is_absolute():
        base = Path.home() / '.local/share'
    return base / 'MotivationApp' / 'updates'


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if os.name != 'posix':
        return
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def recover(folder):
    journal = read_json(folder / 'transaction.json', {})
    if journal.get('phase') in ('preparing', 'testing', 'launching'):
        atomic(folder / 'active.json', journal['previous'])
        journal.update(phase='failed', error='Обновление прервано. Сохранена предыдущая версия; данные не заменялись.')
        atomic(folder / 'transaction.json', journal)
    return journal


def route():
    if not sys.platform.startswith('linux'):
        return
    import fcntl
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    # A live installer owns this lock. A power failure releases it automatically.
    with (folder / 'install.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not os.environ.get('TOCHKA_UPDATE_TRIAL'):
                print('Установка обновления ещё выполняется. Повторите запуск позже.', file=sys.stderr)
                raise SystemExit(1)
        else:
            recover(folder)
    global _application_lock
    _application_lock = (folder / 'application.lock').open('a')
    try:
        fcntl.flock(_application_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('Точка опоры уже запущена.', file=sys.stderr)
        raise SystemExit(1)
    active = read_json(folder / 'active.json')
    if not active:
        return
    script = Path(active['code']) / 'main.py'
    python = Path(active['python'])
    if script.resolve() == Path(sys.argv[0]).resolve() and python.absolute() == Path(sys.executable).absolute():
        return
    if not script.is_file() or not python.is_file():
        raise RuntimeError('Выбранная версия недоступна. Проверьте каталог обновлений.')
    # Replacement process will reacquire the application lock.
    _application_lock.close()
    os.execv(str(python), [str(python), str(script), *sys.argv[1:]])


def launcher_command(default):
    """Keep login registration pointed at the original stable launcher."""
    try:
        active = read_json(state_dir() / 'active.json', {})
        return active.get('launcher', default)
    except (OSError, ValueError):
        return default
