"""Local housekeeping; never deletes data without an explicit UI approval."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from . import workspace, core


def backup_inventory(backup_dir, limit=400):
    root = Path(backup_dir)
    if not root.is_dir():
        return []
    rows = []
    for p in root.iterdir():
        if p.is_file() and p.suffix == '.bak' and not p.is_symlink():
            rows.append((p.name, p.stat().st_size, int(p.stat().st_mtime)))
    return sorted(rows, key=lambda row: row[2], reverse=True)[:limit]


def restore_backup(workspace_root, destination, backup_dir, backup_name, approved=False):
    """Must be called AFTER showing the restore diff and receiving approval."""
    if not approved:
        raise PermissionError('Требуется явное подтверждение')
    root = Path(backup_dir).resolve(strict=True)
    if Path(backup_name).name != backup_name or not backup_name.endswith('.bak'):
        raise ValueError('Неверное имя резервной копии')
    source = (root / backup_name).resolve(strict=True)
    if source.parent != root or not source.is_file() or source.stat().st_size > workspace.MAX_TEXT_BYTES:
        raise ValueError('Резервная копия недоступна')
    text = source.read_text(encoding='utf-8-sig')
    draft = workspace.draft_change(workspace_root, destination, text)
    return workspace.apply_change(workspace_root, draft, backup_dir)


def purge_history_before(cutoff_ts, approved=False):
    if not approved:
        raise PermissionError('Требуется подтверждение удаления истории')
    with core.db() as conn:
        cursor = conn.execute('DELETE FROM history WHERE ts < ?', (int(cutoff_ts),))
        return cursor.rowcount


def storage_statistics():
    with core.db() as conn:
        counts = {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in ('history', 'notes', 'audit')}
    backup_dir = core.ensure_dir() / 'backups'
    backups = backup_inventory(backup_dir)
    counts['backups'] = len(backups)
    counts['backup_bytes'] = sum(x[1] for x in backups)
    counts['database_bytes'] = (core.ensure_dir() / 'memory.db').stat().st_size
    return counts


def clear_legacy_history(approved=False):
    """Purge the legacy table after migration; preserve all modern conversations."""
    if not approved:
        raise PermissionError('Нужно явное подтверждение удаления старой истории')
    with core.db() as conn:
        # Prevent accidental data loss if migration was not completed yet.
        from . import conversations
        conversations.init(conn)
        n = conn.execute('DELETE FROM history').rowcount
        return n
