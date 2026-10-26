"""Isolated updater process. Never resets checkout, overwrites user data or logs command output."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from update_bootstrap import atomic, read_json, state_dir, recover

EXPECTED = {'https://github.com/GItShiha/motivation-app.git', 'https://github.com/GItShiha/motivation-app', 'git@github.com:GItShiha/motivation-app.git', 'ssh://git@github.com/GItShiha/motivation-app.git'}


class UpdateError(Exception):
    pass


def run(args, cwd=None, timeout=120, env=None):
    try:
        r = subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError('Команда недоступна или превышено время ожидания: ' + Path(str(args[0])).name) from exc
    if r.returncode:
        # Remote errors and pip output may contain credentials: never persist them.
        raise UpdateError('Ошибка ' + Path(str(args[0])).name + '. Проверьте сеть, доступ и зависимости вручную; вывод скрыт для защиты секретов.')
    return r.stdout.strip()


def git(root, *args):
    return run(['git', '-C', root, *args])


def validate(root):
    root = Path(root).resolve()
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise UpdateError('Выберите корень репозитория приложения.')
    if git(root, 'remote', 'get-url', 'origin') not in EXPECTED:
        raise UpdateError('Источник origin не соответствует GItShiha/motivation-app.')
    if git(root, 'config', '--get-all', 'remote.origin.url').count('\n') != 0:
        raise UpdateError('У origin несколько источников; требуется ручная проверка.')
    if git(root, 'status', '--porcelain', '--untracked-files=normal'):
        raise UpdateError('Есть незакоммиченные файлы. Сохраните их отдельным коммитом или вручную перенесите; обновление их не изменяет.')
    return git(root, 'rev-parse', 'HEAD')


def check(root, fetch=True):
    current = validate(root)
    if fetch:
        git(root, 'fetch', '--no-tags', 'origin', 'refs/heads/main:refs/remotes/origin/main')
    target = git(root, 'rev-parse', 'refs/remotes/origin/main')
    if not re.fullmatch(r'[0-9a-f]{40,64}', target):
        raise UpdateError('Некорректная ревизия main.')
    if target != current:
        try:
            git(root, 'merge-base', '--is-ancestor', current, target)
        except UpdateError as exc:
            raise UpdateError('Локальная история расходится с origin/main или опережает её. Обновите вручную без потери локальных коммитов.') from exc
    return {'current': current, 'target': target, 'available': current != target,
            'checked_at': datetime.now().astimezone().isoformat()}


def log(folder, event):
    with (folder / 'events.log').open('a', encoding='utf-8') as f:
        f.write(datetime.now().astimezone().isoformat() + ' ' + event + '\n')
        f.flush()
        os.fsync(f.fileno())


def launch(version, data_path, folder, trial=False):
    env = os.environ.copy()
    env['TOCHKA_UPDATE_DATA'] = str(data_path)
    ready = folder / ('ready-' + uuid.uuid4().hex + '.json')
    if trial:
        env['TOCHKA_UPDATE_TRIAL'] = str(ready)
    else:
        env.pop('TOCHKA_UPDATE_TRIAL', None)
    p = subprocess.Popen([version['python'], str(Path(version['code']) / 'main.py')], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if not trial:
        return p
    for _ in range(150):
        if p.poll() is not None:
            raise UpdateError('Новая версия завершилась до открытия окна.')
        if ready.is_file():
            # Opening the window alone is insufficient: require a live event loop afterwards.
            time.sleep(2)
            if p.poll() is None:
                return p
            break
        time.sleep(.2)
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    raise UpdateError('Новая версия не подтвердила запуск за 30 секунд.')


def install(root, target, data_path, folder=None, python=None):
    import fcntl
    folder = Path(folder or state_dir())
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recover(folder)
        app_lock = (folder / 'application.lock').open('a')
        fcntl.flock(app_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = validate(root)
        previous = {'code': str(Path(root).resolve()), 'python': python or sys.executable, 'revision': current}
        active = read_json(folder / 'active.json', {})
        previous['launcher'] = active.get('launcher', [previous['python'], str(Path(root) / 'main.py')])
        transaction = {'phase': 'preparing', 'previous': previous, 'target': target}
        atomic(folder / 'transaction.json', transaction)
        log(folder, 'Подготовка обновления: ' + target)
        trial = None
        try:
            if not Path(previous['python']).is_file() or not (Path(root) / 'main.py').is_file():
                raise UpdateError('Прежний интерпретатор или запускатель недоступен; безопасный откат невозможен.')
            run([previous['python'], '-c', 'import PySide6'], timeout=30)
            result = check(root)
            if result['target'] != target or not result['available']:
                raise UpdateError('main изменилась после подтверждения. Проверьте обновления и подтвердите новую ревизию.')
            if shutil.disk_usage(folder).free < 2 * 1024**3:
                raise UpdateError('Для отдельного окружения и резервной копии нужно не менее 2 ГиБ свободного места.')
            release = folder / 'releases' / (target + '-' + uuid.uuid4().hex[:8])
            release.mkdir(parents=True)
            backup = release / 'data-before.json'
            if Path(data_path).exists():
                # Never restore this over live data automatically, including on rollback.
                value = read_json(data_path)
                if not isinstance(value, dict):
                    raise UpdateError('Данные имеют неверный формат; установка остановлена.')
                atomic(backup, value)
            atomic(release / 'restore.json', {'previous': previous, 'data': str(data_path), 'backup': str(backup)})
            code = release / 'code'
            git(root, 'worktree', 'add', '--detach', str(code), target)
            # A release must include this update protocol and startup handshake.
            if not (code / 'update_bootstrap.py').is_file():
                raise UpdateError('Версия не поддерживает безопасный протокол обновления.')
            venv = release / 'venv'
            run([sys.executable, '-m', 'venv', venv], timeout=120)
            newpython = venv / 'bin/python'
            run([newpython, '-m', 'pip', 'install', '-r', code / 'requirements.txt'], cwd=code, timeout=900)
            run([newpython, '-m', 'pip', 'check'], timeout=60)
            log(folder, 'Зависимости установлены; проверка новой версии.')
            transaction['phase'] = 'testing'
            atomic(folder / 'transaction.json', transaction)
            env = os.environ.copy()
            env['QT_QPA_PLATFORM'] = 'offscreen'
            env['TOCHKA_UPDATE_DATA'] = str(backup)
            env.pop('TOCHKA_UPDATE_TRIAL', None)
            run([newpython, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=code, env=env, timeout=180)
            smoke_data = release / 'smoke-data.json'
            if backup.is_file():
                atomic(smoke_data, read_json(backup))
            run([newpython, 'main.py', '--update-smoke-test', str(smoke_data)], cwd=code, env=env, timeout=60)
            # Refuse migrations that prevent the previous code reading the migrated snapshot.
            run([previous['python'], '-c', 'import sys; from main import Store; Store(sys.argv[1])', str(smoke_data)], cwd=root, env=env, timeout=60)
            # Catch edits made by another process during dependency installation.
            if validate(root) != current:
                raise UpdateError('Рабочая копия изменилась во время установки.')
            version = {'code': str(code), 'python': str(newpython), 'revision': target, 'launcher': previous['launcher']}
            log(folder, 'Проверки пройдены; пробный запуск.')
            transaction['phase'] = 'launching'
            atomic(folder / 'transaction.json', transaction)
            atomic(folder / 'active.json', version)
            app_lock.close()
            trial = launch(version, data_path, folder, trial=True)
            transaction.update(phase='complete', installed=version)
            atomic(folder / 'transaction.json', transaction)
            log(folder, 'Обновление успешно подтверждено: ' + target)
        except Exception as exc:
            if trial is not None and trial.poll() is None:
                trial.terminate()
                trial.wait(timeout=10)
            atomic(folder / 'active.json', previous)
            error = str(exc) if isinstance(exc, UpdateError) else 'Не удалось установить обновление. Проверьте права, свободное место и журнал.'
            transaction.update(phase='failed', error=error)
            atomic(folder / 'transaction.json', transaction)
            log(folder, error)
            app_lock.close()
            fcntl.flock(lock, fcntl.LOCK_UN)
            launch(previous, data_path, folder)
            return False
    return True


def rollback(folder=None):
    """Explicit manual recovery of code and interpreter; live data is never restored."""
    import fcntl
    folder = Path(folder or state_dir())
    with (folder / 'install.lock').open('a') as install_lock, (folder / 'application.lock').open('a') as app_lock:
        try:
            fcntl.flock(install_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(app_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateError('Закройте приложение и дождитесь завершения установщика.') from exc
        journal = read_json(folder / 'transaction.json', {})
        previous = journal.get('previous')
        if not previous or not (Path(previous['code']) / 'main.py').is_file() or not Path(previous['python']).is_file():
            raise UpdateError('Точка восстановления недоступна. Проверьте restore.json в каталоге releases.')
        validate(previous['code'])
        run([previous['python'], '-c', 'import PySide6'])
        atomic(folder / 'active.json', previous)
        journal.update(phase='rolled_back', error='Выполнен ручной возврат к предыдущей версии. Данные не изменялись.')
        atomic(folder / 'transaction.json', journal)
        log(folder, 'Ручной возврат к предыдущей версии; данные не изменялись.')
    return previous


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['check', 'revision', 'install', 'rollback'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--target')
    parser.add_argument('--data')
    parser.add_argument('--wait-fd', type=int)
    args = parser.parse_args()
    try:
        if args.action == 'rollback':
            rollback()
            print('Восстановлена предыдущая версия. Запустите приложение обычным ярлыком. Данные не изменялись.')
        elif args.action == 'revision':
            print(json.dumps({'current': git(args.root, 'rev-parse', 'HEAD')}))
        elif args.action == 'check':
            print(json.dumps(check(args.root)))
        else:
            if args.wait_fd is None or not args.target or not args.data:
                raise UpdateError('Установка запускается только из приложения после подтверждения.')
            # EOF means the GUI process has exited, not merely hidden its window.
            with os.fdopen(args.wait_fd, 'rb') as gate:
                gate.read()
            return 0 if install(args.root, args.target, args.data) else 1
    except Exception as exc:
        error = str(exc) if isinstance(exc, UpdateError) else 'Обновление недоступно. Проверьте Git, права и каталог установки.'
        print(json.dumps({'error': error}, ensure_ascii=False))
        if args.action == 'install' and args.data:
            folder = state_dir()
            folder.mkdir(parents=True, exist_ok=True)
            previous = {'code': str(Path(args.root).resolve()), 'python': sys.executable}
            atomic(folder / 'transaction.json', {'phase': 'failed', 'previous': previous, 'error': error})
            launch(previous, args.data, folder)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
