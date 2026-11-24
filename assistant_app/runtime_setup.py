"""Conservative, offline runtime setup for a modest Windows 11 PC.

No downloads, execution or network requests happen in this module.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from .model_inventory import inspect_model

PROFILES = {
    'CPU — надёжный старт': {'gpu_layers': 0, 'context': 2048},
    'Vulkan — осторожный тест': {'gpu_layers': 8, 'context': 2048},
    'Vulkan — расширенный тест': {'gpu_layers': 20, 'context': 4096},
}


def profile_settings(name, port=8080):
    if name not in PROFILES:
        raise ValueError('Неизвестный профиль запуска')
    try:
        port = int(port)
    except (ValueError, TypeError) as exc:
        raise ValueError('Неверный порт') from exc
    if not 1024 <= port <= 65535:
        raise ValueError('Порт должен быть в диапазоне 1024–65535')
    return {**PROFILES[name], 'port': port,
            'local_url': f'http://127.0.0.1:{port}/v1'}


def assess_model(path, free_gb=None):
    info = inspect_model(path)
    gib = info['size'] / 1024**3
    warnings = []
    if gib > 5.5:
        warnings.append('Файл модели велик для RX 580 8 ГБ: начните с CPU.')
    if free_gb is not None and float(free_gb) < max(4, gib + 2):
        warnings.append('На диске может не хватить места для безопасных операций и временных файлов.')
    return {'name': info['name'], 'size_gib': round(gib, 2),
            'warnings': warnings, 'version': info['version']}


def validate_local_base(url):
    """Strict loopback-only URL and exact /v1 path, without URL userinfo or query."""
    try:
        u = urlsplit(url)
        port = u.port
    except (ValueError, TypeError) as exc:
        raise ValueError('Неправильный адрес сервера') from exc
    if (u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost')
            or port is None or u.username or u.password or u.query or u.fragment
            or u.path not in ('/v1', '/v1/')):
        raise ValueError('Доступен только локальный http://127.0.0.1:порт/v1')
    return f'http://127.0.0.1:{port}/v1'


def runtime_report(settings):
    """Produce read-only local setup guidance; never infer installed Vulkan support."""
    profile = {k: settings.get(k, '') for k in ('server_exe', 'model_file', 'gpu_layers', 'context', 'port')}
    messages = []
    exe = Path(profile['server_exe']) if profile['server_exe'] else None
    if not exe or exe.name.lower() != 'llama-server.exe' or not exe.is_file() or exe.is_symlink():
        messages.append('Не найден выбранный llama-server.exe: укажи доверенную Windows-сборку.')
    else:
        messages.append('Файл llama-server.exe найден; его подлинность и Vulkan-бэкенд НЕ проверены.')
    try:
        if not profile['model_file']:
            raise ValueError('модель не выбрана')
        a = assess_model(profile['model_file'])
        messages.append(f"Модель: {a['name']} ({a['size_gib']} ГиБ, GGUF v{a['version']}).")
        messages.extend(a['warnings'])
    except (ValueError, OSError) as exc:
        messages.append('Модель недоступна или повреждена: ' + str(exc))
    try:
        validate_local_base(settings.get('local_url', ''))
        messages.append('Адрес сервера ограничен локальным компьютером.')
    except ValueError as exc:
        messages.append('Предупреждение об адресе: ' + str(exc))
    messages.append('Рекомендация для Ryzen 5 3600 / RX 580: начать с CPU, затем проверять Vulkan вручную.')
    messages.append('Этот отчёт не запускает сервер, не тестирует GPU и не обращается к сети.')
    return '\n'.join(messages)
