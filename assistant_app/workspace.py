"""Constrained file workspace operations: no shell and no network.

The model never calls these methods directly: UI passes explicitly approved operations.
"""
from __future__ import annotations
import difflib
import hashlib
import os
import shutil
from pathlib import Path

MAX_TEXT_BYTES = 512 * 1024
MAX_WRITE_BYTES = 512 * 1024


class WorkspaceError(ValueError):
    pass


def normalized_root(root):
    p = Path(root).expanduser().resolve(strict=True)
    if not p.is_dir():
        raise WorkspaceError('Рабочая область должна быть папкой')
    return p


def safe_path(root, target, existing=True):
    base = normalized_root(root)
    raw = Path(target)
    if not raw.is_absolute():
        raw = base / raw
    path = raw.resolve(strict=existing)
    if not path.is_relative_to(base):
        raise WorkspaceError('Запрещён выход за пределы рабочей папки')
    if path == base:
        raise WorkspaceError('Выберите файл внутри рабочей папки')
    if path.is_symlink():
        raise WorkspaceError('Символьные ссылки запрещены')
    # Reject symlink ancestors even when the resolved final path stays in bounds.
    rel = raw.relative_to(base) if raw.is_relative_to(base) else None
    if rel is not None:
        cursor = base
        for part in rel.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise WorkspaceError('Символьные ссылки в пути запрещены')
    return path


def list_files(root, limit=250):
    base = normalized_root(root)
    rows = []
    for current, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink() and d not in ('.git', '__pycache__', 'node_modules', '.venv'))
        for file in sorted(files):
            p = Path(current) / file
            if p.is_symlink():
                continue
            try:
                rows.append((str(p.relative_to(base)), p.stat().st_size))
            except OSError:
                continue
            if len(rows) >= limit:
                return rows
    return rows


def read_text(root, target):
    path = safe_path(root, target)
    if not path.is_file():
        raise WorkspaceError('Это не файл')
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise WorkspaceError('Файл превышает ограничение просмотра (512 КБ)')
    try:
        return path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError as exc:
        raise WorkspaceError('Поддерживаются только текстовые UTF-8 файлы') from exc


def draft_change(root, target, new_text):
    if len(new_text.encode('utf-8')) > MAX_WRITE_BYTES:
        raise WorkspaceError('Изменение превышает 512 КБ')
    path = safe_path(root, target, existing=False)
    if not path.parent.is_dir():
        raise WorkspaceError('Родительская папка должна существовать')
    if path.exists() and not path.is_file():
        raise WorkspaceError('Назначение не является файлом')
    old = read_text(root, path) if path.exists() else ''
    diff = ''.join(difflib.unified_diff(old.splitlines(keepends=True), new_text.splitlines(keepends=True),
                      fromfile='до/' + path.name, tofile='после/' + path.name))
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return {'path': str(path), 'new_text': new_text, 'expected_sha256': digest, 'diff': diff or '(нет изменений)'}


def apply_change(root, draft, backup_dir):
    """Must be called ONLY after the GUI has shown the exact diff and asked for approval."""
    path = safe_path(root, draft['path'], existing=False)
    if not path.parent.is_dir() or path.is_symlink():
        raise WorkspaceError('Файл/каталог изменился с момента проверки')
    expected = draft['expected_sha256']
    current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() and path.is_file() else None
    if current != expected:
        raise WorkspaceError('Файл изменился после предпросмотра; повторите операцию')
    new_text = draft['new_text']
    if len(new_text.encode('utf-8')) > MAX_WRITE_BYTES:
        raise WorkspaceError('Превышен лимит')
    backup = None
    if path.exists():
        out = Path(backup_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)
        backup = out / (hashlib.sha256(str(path).encode()).hexdigest()[:20] + '-' + hashlib.sha256(os.urandom(16)).hexdigest()[:12] + '.bak')
        shutil.copy2(path, backup)
    tmp = path.parent / ('.personalai-' + hashlib.sha256(os.urandom(16)).hexdigest()[:12] + '.tmp')
    try:
        tmp.write_text(new_text, encoding='utf-8')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return str(backup) if backup else ''
