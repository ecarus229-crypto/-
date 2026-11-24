"""Safe local endpoint diagnostics and Windows machine probing."""
from __future__ import annotations
import json
import subprocess
import urllib.request
from urllib.parse import urlsplit


def local_endpoint(url):
    parsed = urlsplit(url)
    return parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1') and parsed.port is not None and not parsed.username and not parsed.password and not parsed.fragment and not parsed.query


def probe_local(base_url, timeout=3):
    if not local_endpoint(base_url):
        raise ValueError('Разрешён только локальный HTTP на localhost:port')
    url = base_url.rstrip('/') + '/models'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        data = json.load(response)
    models = [str(m.get('id', '')) for m in data.get('data', []) if isinstance(m, dict)]
    return models[:30]


def get_gpu_windows():
    script = 'Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Compress'
    proc = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True,
                          text=True, check=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return proc.stdout.strip()
