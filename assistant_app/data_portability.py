"""Offline verified, export-only backup of PersonalAI settings and SQLite data.

Never includes installed models, source projects, API keys, or arbitrary folders.
Restoration is intentionally not automated: replacing a live database is risky.
"""
from __future__ import annotations
import hashlib
from contextlib import closing
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from . import core

MAX_DB_BYTES = 256 * 1024 * 1024
MAX_SETTINGS_BYTES = 128 * 1024
ALLOWED_NAMES = frozenset(('memory.db', 'settings.json', 'manifest.json'))


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _settings_bytes(data_dir: Path) -> bytes:
    path = data_dir / 'settings.json'
    if not path.exists():
        obj = dict(core.DEFAULT_CONFIG)
    else:
        if path.is_symlink() or path.stat().st_size > MAX_SETTINGS_BYTES:
            raise ValueError('Неподдерживаемый файл настроек')
        obj = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(obj, dict):
            raise ValueError('Неверный формат настроек')
    # Keep only supported keys. Never place tokens in a portable archive.
    obj = {k: v for k, v in obj.items() if k in core.DEFAULT_CONFIG and k != 'api_key'}
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True).encode('utf-8')


def export_backup(destination: str | Path, *, data_dir: str | Path | None = None) -> dict:
    """Create an atomic, checked backup. The destination must not be inside data_dir."""
    base = Path(data_dir) if data_dir is not None else core.ensure_dir()
    base = base.resolve(strict=True)
    dest = Path(destination).expanduser().resolve()
    if dest.suffix.lower() != '.zip':
        raise ValueError('Резервная копия должна иметь расширение ZIP')
    if base == dest or base in dest.parents:
        raise ValueError('Храните архив вне папки данных PersonalAI')
    if dest.exists():
        raise FileExistsError('Нельзя перезаписывать существующий архив')
    db = base / 'memory.db'
    if db.is_symlink():
        raise ValueError('База данных не может быть символической ссылкой')
    if db.exists() and db.stat().st_size > MAX_DB_BYTES:
        raise ValueError('База данных превышает ограничение резервной копии')
    settings = _settings_bytes(base)
    # sqlite3 backup API creates a consistent snapshot even with WAL active.
    with tempfile.TemporaryDirectory(prefix='personalai-backup-') as temp:
        snapshot = Path(temp) / 'memory.db'
        with closing(sqlite3.connect(str(db) if db.exists() else ':memory:', timeout=10)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
                integrity = target.execute('PRAGMA integrity_check').fetchone()[0]
                if integrity != 'ok':
                    raise ValueError('Проверка целостности базы данных не пройдена')
        if snapshot.stat().st_size > MAX_DB_BYTES:
            raise ValueError('Снимок базы превышает ограничение')
        contents = {'settings.json': settings, 'memory.db': snapshot.read_bytes()}
        manifest = {'format': 'PersonalAI-backup-v1',
                    'created_utc': datetime.now(timezone.utc).isoformat(),
                    'files': {name: {'sha256': _sha256(data), 'size': len(data)}
                              for name, data in contents.items()}}
        contents['manifest.json'] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.personalai-', suffix='.tmp', dir=dest.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                for name, data in contents.items():
                    z.writestr(name, data)
            result = verify_backup(tmp)
            if not result['valid']:
                raise ValueError('Созданный архив не прошёл проверку')
            if dest.exists():
                raise FileExistsError('Файл появился во время создания резервной копии')
            os.replace(tmp, dest)
            return result
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def verify_backup(path: str | Path) -> dict:
    """Read-only verification. Never extracts ZIP entries onto disk."""
    path = Path(path)
    with zipfile.ZipFile(path, 'r') as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != 3 or set(names) != ALLOWED_NAMES or len(names) != len(set(names)):
            raise ValueError('Неверный состав архива')
        if any(i.is_dir() or i.file_size > MAX_DB_BYTES or i.flag_bits & 1 for i in infos):
            raise ValueError('Недопустимые записи ZIP')
        if next(i.file_size for i in infos if i.filename == 'settings.json') > MAX_SETTINGS_BYTES:
            raise ValueError('Слишком большой файл настроек')
        if next(i.file_size for i in infos if i.filename == 'manifest.json') > 4096:
            raise ValueError('Слишком большой манифест')
        manifest = json.loads(z.read('manifest.json'))
        if manifest.get('format') != 'PersonalAI-backup-v1' or set(manifest.get('files', {})) != {'memory.db', 'settings.json'}:
            raise ValueError('Неподдерживаемый формат архива')
        for name in ('memory.db', 'settings.json'):
            with z.open(name) as stream:
                h = hashlib.sha256()
                size = 0
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk: break
                    size += len(chunk)
                    if size > (MAX_DB_BYTES if name == 'memory.db' else MAX_SETTINGS_BYTES):
                        raise ValueError('Слишком большой файл в архиве')
                    h.update(chunk)
            record = manifest['files'][name]
            if not isinstance(record, dict) or h.hexdigest() != record.get('sha256') or size != record.get('size'):
                raise ValueError('Контрольная сумма или размер файла не совпадают')
        settings = json.loads(z.read('settings.json'))
        if not isinstance(settings, dict) or 'api_key' in settings:
            raise ValueError('Недопустимые настройки в архиве')
    return {'valid': True, 'created_utc': manifest['created_utc'],
            'database_bytes': manifest['files']['memory.db']['size'],
            'settings_bytes': manifest['files']['settings.json']['size']}
