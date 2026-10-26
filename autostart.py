"""Per-user login startup registration; no administrator privileges required."""
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path


class Autostart:
    name = 'TochkaOpory'
    registry_key = r'Software\Microsoft\Windows\CurrentVersion\Run'

    def __init__(self, platform=None, home=None, environ=None, command=None):
        self.platform = platform or sys.platform
        home = Path.home() if home is None else Path(home)
        environ = os.environ if environ is None else environ
        executable = Path(sys.executable)
        if self.platform == 'win32' and executable.with_name('pythonw.exe').is_file():
            executable = executable.with_name('pythonw.exe')
        self.command = command or [str(executable), str(Path(__file__).resolve().with_name('main.py'))]
        if self.platform == 'darwin':
            self.path = home / 'Library/LaunchAgents/app.motivation.tochkaopory.plist'
        else:
            config = Path(environ.get('XDG_CONFIG_HOME') or home / '.config')
            if not config.is_absolute():
                config = home / '.config'
            self.path = config / 'autostart/tochka-opory.desktop'

    @property
    def supported(self):
        return self.platform in ('win32', 'darwin') or self.platform.startswith('linux')

    def enabled(self):
        if self.platform == 'win32':
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key) as key:
                    winreg.QueryValueEx(key, self.name)
                return True
            except FileNotFoundError:
                return False
        return self.path.is_file()

    def set_enabled(self, enabled):
        if not self.supported:
            raise OSError('Автозапуск не поддерживается на этой системе.')
        if self.platform == 'win32':
            import winreg
            if enabled:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.registry_key) as key:
                    winreg.SetValueEx(key, self.name, 0, winreg.REG_SZ,
                                     subprocess.list2cmdline(self.command))
            else:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key,
                                        0, winreg.KEY_SET_VALUE) as key:
                        winreg.DeleteValue(key, self.name)
                except FileNotFoundError:
                    pass
            return
        if not enabled:
            self.path.unlink(missing_ok=True)
            return
        if self.platform == 'darwin':
            content = plistlib.dumps({'Label': 'app.motivation.tochkaopory',
                                     'ProgramArguments': self.command, 'RunAtLoad': True})
        else:
            # Desktop Entry string escaping is separate from Exec argument quoting.
            def quote(arg):
                arg = arg.replace('%', '%%')
                for char in ('\\', '"', '`', '$'):
                    arg = arg.replace(char, '\\' + char)
                return '"' + arg + '"'
            command = ' '.join(quote(arg) for arg in self.command)
            command = command.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            content = ('[Desktop Entry]\nType=Application\nName=Точка опоры\n'
                       f'Exec={command}\nTerminal=false\n').encode('utf-8')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
