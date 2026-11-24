"""Local read-only project snapshots: metadata and hashes, never file contents.

Snapshots are explicit user actions. No watcher, no network and no file writes to
projects. Comparisons are bounded, and symlinks / sensitive paths are skipped.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from . import core, workspace

MAX_FILES = 1500
MAX_FILE_SIZE = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 96 * 1024 * 1024
IGNORE_DIRS = {'.git', '.svn', '.hg', '.venv', 'venv', 'node_modules', '__pycache__', '.idea', '.vs', 'dist', 'build'}
IGNORE_FILES = {'.env', '.env.local', '.env.production', 'id_rsa', 'id_ed25519', 'credentials.json', 'secrets.json'}


def init(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS project_snapshots (
        id INTEGER PRIMARY KEY, created INTEGER NOT NULL, root TEXT NOT NULL,
        label TEXT NOT NULL, data TEXT NOT NULL)''')


def scan(root):
    """Return capped mapping of relative paths to sha256 / bytes; no content stored."""
    base = workspace.normalized_root(root)
    found = {}
    hashed = 0
    skipped = 0
    truncated = False
    for current, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not (Path(current) / d).is_symlink())
        for filename in sorted(files):
            path = Path(current) / filename
            if filename.lower() in IGNORE_FILES or path.is_symlink():
                skipped += 1
                continue
            try:
                stat = path.stat()
                if not path.is_file() or stat.st_size > MAX_FILE_SIZE or hashed + stat.st_size > MAX_TOTAL_BYTES:
                    skipped += 1
                    continue
                if len(found) == MAX_FILES:
                    truncated = True
                    break
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    while part := stream.read(128 * 1024):
                        digest.update(part)
                # A file altered while being read must not enter a snapshot as reliable.
                after = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    skipped += 1
                    continue
                name = path.relative_to(base).as_posix()
                found[name] = {'sha256': digest.hexdigest(), 'bytes': stat.st_size}
                hashed += stat.st_size
            except (OSError, PermissionError):
                skipped += 1
        if truncated:
            break
    return {'files': found, 'skipped': skipped, 'truncated': truncated, 'hashed_bytes': hashed}


def create(root, label='Снимок проекта'):
    label = label.strip()
    if not 1 <= len(label) <= 120:
        raise ValueError('Название снимка: от 1 до 120 символов')
    base = str(workspace.normalized_root(root))
    snapshot = scan(base)
    with core.db() as conn:
        init(conn)
        cur = conn.execute('INSERT INTO project_snapshots(created,root,label,data) VALUES (?,?,?,?)',
                           (int(time.time()), base, label, json.dumps(snapshot, ensure_ascii=False)))
        return cur.lastrowid, snapshot


def list_all(root=None, limit=100):
    with core.db() as conn:
        init(conn)
        if root is None:
            return conn.execute('SELECT id,created,root,label FROM project_snapshots ORDER BY id DESC LIMIT ?', (min(max(int(limit),1),200),)).fetchall()
        return conn.execute('SELECT id,created,root,label FROM project_snapshots WHERE root=? ORDER BY id DESC LIMIT ?',
                            (str(workspace.normalized_root(root)),min(max(int(limit),1),200))).fetchall()


def load(snapshot_id):
    with core.db() as conn:
        init(conn)
        row = conn.execute('SELECT root,label,data FROM project_snapshots WHERE id=?', (int(snapshot_id),)).fetchone()
    if not row:
        raise ValueError('Снимок не найден')
    return row[0], row[1], json.loads(row[2])


def compare(old, new):
    a = old['files']
    b = new['files']
    return {
        'added': sorted(b.keys() - a.keys()),
        'deleted': sorted(a.keys() - b.keys()),
        'modified': sorted(name for name in a.keys() & b.keys() if a[name]['sha256'] != b[name]['sha256']),
        'unchanged_count': sum(a[name]['sha256'] == b[name]['sha256'] for name in a.keys() & b.keys()),
        'incomplete': old.get('truncated',False) or new.get('truncated',False) or bool(old.get('skipped') or new.get('skipped')),
    }


def compare_to_disk(snapshot_id):
    root, label, original = load(snapshot_id)
    current = scan(root)
    return root, label, compare(original, current), current


def render_comparison(diff, limit=200):
    lines = [f"Добавлено: {len(diff['added'])}; изменено: {len(diff['modified'])}; удалено: {len(diff['deleted'])}; без изменений: {diff['unchanged_count']}"]
    if diff['incomplete']:
        lines.append('Внимание: сканирование не было полным; удаление/изменение может быть следствием исключений или ограничений.')
    for key, title in [('added','НОВЫЕ'),('modified','ИЗМЕНЁННЫЕ'),('deleted','ОТСУТСТВУЮТ')]:
        lines.append('\n' + title + ':')
        lines.extend('  ' + name for name in diff[key][:limit])
        if len(diff[key]) > limit:
            lines.append(f'  ... ещё {len(diff[key]) - limit}')
    return '\n'.join(lines)


def delete(snapshot_id):
    with core.db() as conn:
        init(conn)
        cur = conn.execute('DELETE FROM project_snapshots WHERE id=?', (int(snapshot_id),))
        if cur.rowcount != 1:
            raise ValueError('Снимок не найден')
