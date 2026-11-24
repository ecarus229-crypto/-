"""Opt-in model GGUF downloader with SHA-256, size limits and atomic install.

Remote URLs are untrusted: only HTTPS, no redirects, no authentication, and no
automatic execution of downloaded content. The user selects URL and checksum.
"""
from __future__ import annotations
import hashlib
import os
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

MAX_GB = 12


def validate(url, sha256, destination):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError('Требуется публичный HTTPS URL без учётных данных и нестандартных портов')
    if parsed.hostname.lower() in ('localhost',) or parsed.hostname.endswith('.local'):
        raise ValueError('Локальные адреса запрещены')
    import ipaddress
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ValueError('Используйте доменное имя проверенного HTTPS-хранилища')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', sha256):
        raise ValueError('Необходим полный SHA-256 от надёжного источника')
    dest = Path(destination).expanduser().absolute()
    if dest.suffix.lower() != '.gguf' or dest.is_symlink() or not dest.parent.is_dir():
        raise ValueError('Выберите путь GGUF в существующей папке')
    if dest.exists():
        raise FileExistsError('Файл назначения уже существует')
    return dest


def download(url, sha256, destination, *, progress=None, max_bytes=MAX_GB * 1024**3, opener=None):
    dest = validate(url, sha256, destination)
    if not 0 < max_bytes <= MAX_GB * 1024**3:
        raise ValueError('Неверный лимит загрузки')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            raise ValueError('Перенаправления загрузки запрещены')
    client = opener or urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={'User-Agent': 'PersonalAI-ModelDownloader/1.5'})
    import tempfile
    tmp_name = None
    try:
        with client.open(req, timeout=45) as stream:
            count = 0
            digest = hashlib.sha256()
            with tempfile.NamedTemporaryFile(mode='wb', prefix='.personalai-', suffix='.part', dir=dest.parent, delete=False) as tmp:
                tmp_name = tmp.name
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    count += len(block)
                    if count > max_bytes:
                        raise ValueError('Загрузка превышает лимит размера')
                    digest.update(block)
                    tmp.write(block)
                    if progress:
                        progress(count)
                tmp.flush()
                os.fsync(tmp.fileno())
        with open(tmp_name, 'rb') as check_file:
            valid_header = check_file.read(4) == b'GGUF'
        if count < 4 or not valid_header:
            raise ValueError('Загруженный файл не имеет заголовка GGUF')
        if digest.hexdigest().lower() != sha256.lower():
            raise ValueError('Контрольная сумма SHA-256 не совпала; файл отклонён')
        # Create only if absent. Avoid accidental replacement of an existing model.
        os.link(tmp_name, dest)
        return count
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)
