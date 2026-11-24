"""Small, explicitly approved Windows application launcher.

No shell, user-supplied executable path, arguments, or AI-supplied commands.
Only fixed applications in the Windows system directory are supported.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

APPLICATIONS = {
    'notepad': ('Блокнот', 'notepad.exe'),
    'calculator': ('Калькулятор', 'calc.exe'),
    'explorer': ('Проводник', 'explorer.exe'),
}


def list_applications():
    return [(key, title) for key, (title, _) in APPLICATIONS.items()]


def executable_for(app_id, *, windows_dir=None, platform=None):
    if app_id not in APPLICATIONS:
        raise ValueError('Приложение отсутствует в разрешённом списке')
    system = sys.platform if platform is None else platform
    if system != 'win32':
        raise OSError('Запуск разрешённых приложений доступен только в Windows')
    path = windows_dir if windows_dir is not None else os.environ.get('SystemRoot', '')
    if not path:
        raise OSError('Не удалось определить каталог Windows')
    base = Path(path).resolve(strict=True)
    if base.name.lower() != 'windows':
        raise ValueError('Некорректный каталог Windows')
    system32 = (base / 'System32').resolve(strict=True)
    exe = (system32 / APPLICATIONS[app_id][1]).resolve(strict=True)
    if exe.parent != system32 or not exe.is_file():
        raise ValueError('Приложение не найдено в System32')
    return exe


def launch(app_id, *, approved=False):
    if not approved:
        raise PermissionError('Нужно явное подтверждение запуска приложения')
    path = executable_for(app_id)
    # An exact argument-free executable path; shell expansion is never used.
    subprocess.Popen([str(path)], shell=False, close_fds=True)
    return APPLICATIONS[app_id][0]
