"""Data storage, local/remote LLM transport and safety boundaries."""
from __future__ import annotations
import json
from contextlib import contextmanager
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PersonalAI'
DEFAULT_CONFIG = {
    'mode': 'hybrid', 'local_url': 'http://127.0.0.1:8080/v1',
    'local_model': 'local-model', 'cloud_url': 'https://api.openai.com/v1',
    'cloud_model': 'gpt-4.1-mini', 'timeout_seconds': 90,
    'cloud_fallback': False, 'streaming_enabled': False, 'workspace': '', 'voice_output': False, 'max_context': 18,
    'models_folder': '', 'vosk_model_dir': '', 'server_exe': '', 'model_file': '', 'gpu_layers': '0', 'context': '4096', 'port': '8080',
}
SYSTEM_PROMPT = ('Ты персональный ИИ-помощник для Windows. Отвечай на русском, '
                 'честно сообщай об ограничениях. Ты не можешь самостоятельно '
                 'изменять ПК: любые действия выполняются только после подтверждения. '
                 'Не утверждай, что выполнил действие, пока оно не выполнено.')


def ensure_dir():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def config_path():
    return ensure_dir() / 'settings.json'


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    p = config_path()
    if p.exists():
        try:
            val = json.loads(p.read_text(encoding='utf-8'))
            if isinstance(val, dict):
                cfg.update({k: v for k, v in val.items() if k in cfg and k != 'api_key'})
        except (ValueError, OSError):
            pass
    cfg['cloud_fallback'] = bool(cfg.get('cloud_fallback', False))
    return cfg


def save_config(config):
    cfg = {k: v for k, v in config.items() if k in DEFAULT_CONFIG and k != 'api_key'}
    p = config_path()
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(p)


@contextmanager
def db():
    p = ensure_dir() / 'memory.db'
    connection = sqlite3.connect(p, timeout=5)
    connection.execute('CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, provider TEXT)')
    connection.execute('CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL)')
    connection.commit()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def add_message(role, message, provider=''):
    with db() as conn:
        conn.execute('INSERT INTO history(ts,role,text,provider) VALUES(?,?,?,?)', (int(time.time()), role, message, provider))


def history(limit=24):
    with db() as conn:
        return list(reversed(conn.execute('SELECT role,text FROM history ORDER BY id DESC LIMIT ?', (limit,)).fetchall()))


def clear_history():
    with db() as conn:
        conn.execute('DELETE FROM history')


def export_history(path):
    rows = history(100000)
    Path(path).write_text(json.dumps([{'role': role, 'text': content} for role, content in rows], ensure_ascii=False, indent=2), encoding='utf-8')
    return len(rows)


def add_note(title, body):
    with db() as conn:
        conn.execute('INSERT INTO notes(ts,title,body) VALUES(?,?,?)', (int(time.time()), title[:150], body[:20000]))


def list_notes():
    with db() as conn:
        return conn.execute('SELECT id,title,body FROM notes ORDER BY id DESC').fetchall()


def remove_note(note_id):
    with db() as conn:
        conn.execute('DELETE FROM notes WHERE id=?', (int(note_id),))


def get_audit(limit=250):
    with db() as conn:
        return conn.execute('SELECT ts,action,status,details FROM audit ORDER BY id DESC LIMIT ?', (limit,)).fetchall()


def audit(action, status, details=''):
    with db() as conn:
        conn.execute('INSERT INTO audit(ts,action,status,details) VALUES(?,?,?,?)', (int(time.time()), action, status, details[:1500]))


def request_chat(base_url, model, key, messages, timeout=90):
    from urllib.parse import urlsplit
    parsed = urlsplit(base_url)
    is_local = parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost') and parsed.port is not None
    is_https = parsed.scheme == 'https' and bool(parsed.hostname)
    if not (is_local or is_https) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Для удалённого API требуется HTTPS; локальный допускается только на localhost.')
    url = base_url.rstrip('/') + '/chat/completions'
    data = json.dumps({'model': model, 'messages': messages, 'temperature': 0.6, 'max_tokens': 900}).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    # Prevent proxy access to loopback and avoid redirecting API requests to a different origin.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError('Переадресации API запрещены')
    handlers = [NoRedirect()]
    if is_local:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read(400).decode("utf-8", errors="replace")}') from None
    return payload['choices'][0]['message']['content']


def chat(config, messages, cloud_key=''):
    mode = config.get('mode', 'hybrid')
    timeout = max(5, min(int(config.get('timeout_seconds', 90)), 300))
    if mode != 'cloud':
        try:
            return request_chat(config['local_url'], config['local_model'], '', messages, timeout), 'локальный'
        except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
            if mode == 'local':
                raise RuntimeError('Локальный сервер недоступен: ' + str(exc)) from exc
            local_error = str(exc)
    else:
        local_error = ''
    if mode == 'hybrid' and not config.get('cloud_fallback', False):
        raise RuntimeError('Локальный ИИ недоступен: ' + local_error + '. Переключение в облако отключено для приватности. Выберите облачный режим вручную либо разрешите fallback в настройках.')
    if not cloud_key:
        raise RuntimeError(('Локальная модель недоступна (' + local_error + '). ' if local_error else '') + 'Облачный API-ключ не задан. Откройте настройки.')
    try:
        return request_chat(config['cloud_url'], config['cloud_model'], cloud_key, messages, timeout), 'облачный'
    except Exception as exc:
        raise RuntimeError('Облачный запрос не выполнен: ' + str(exc)) from exc


def system_info():
    """Read-only, never invoke shell=True."""
    ps = ("$o=Get-CimInstance Win32_OperatingSystem; $p=Get-CimInstance Win32_Processor | Select-Object -First 1; "
          "$m=Get-CimInstance Win32_ComputerSystem; "
          "[PSCustomObject]@{Windows=$o.Caption;CPU=$p.Name;RAM_GB=[math]::Round($m.TotalPhysicalMemory/1GB,1);" 
          "FreeDiskGB=[math]::Round((Get-PSDrive C).Free/1GB,1)} | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', ps],
                            capture_output=True, text=True, timeout=20, check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stdout.strip()
