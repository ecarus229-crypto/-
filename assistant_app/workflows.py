"""User-approved, resumable multi-step OFFLINE workflows.

The assistant cannot supply executable commands here. Every step is a fixed,
allowlisted operation; approval is required on every invocation, and advancing
from one step never runs the next step automatically.
"""
from __future__ import annotations
import json
import time
from . import core, workspace, project_audit, project_snapshots

TEMPLATES = {
    'audit_snapshot': ('Аудит и снимок проекта', ('audit', 'snapshot')),
    'audit_only': ('Локальный аудит проекта', ('audit',)),
    'snapshot_only': ('Снимок проекта', ('snapshot',)),
}
LABELS = {'audit': 'Проверить исходники', 'snapshot': 'Сохранить контрольные суммы'}


def init(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS workflows
        (id INTEGER PRIMARY KEY, created INTEGER NOT NULL, root TEXT NOT NULL,
         title TEXT NOT NULL, status TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS workflow_steps
        (id INTEGER PRIMARY KEY, workflow_id INTEGER NOT NULL,
         position INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
         result TEXT NOT NULL DEFAULT '', updated INTEGER NOT NULL DEFAULT 0,
         FOREIGN KEY(workflow_id) REFERENCES workflows(id))''')


def validate_plan(plan):
    """Validate an untrusted plan without running any operation.

    Supports a tiny, fixed vocabulary; no commands, URLs, file paths, arguments,
    extra keys or nested objects may be supplied by an AI response.
    """
    if not isinstance(plan, dict) or set(plan) != {'title', 'steps'}:
        raise ValueError('План должен содержать только title и steps')
    title, steps = plan['title'], plan['steps']
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 80):
        raise ValueError('Недопустимое название плана')
    if any(ord(c) < 32 for c in title):
        raise ValueError('Недопустимые управляющие символы в названии')
    if not isinstance(steps, list) or not (1 <= len(steps) <= 8):
        raise ValueError('План должен содержать от 1 до 8 этапов')
    if any(not isinstance(step, str) or step not in LABELS for step in steps):
        raise ValueError('В плане разрешены только audit и snapshot')
    return title.strip(), tuple(steps)


def parse_plan(text):
    """Parse strict JSON only: model explanations and markdown are not executable."""
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError('План слишком большой или не является текстом')
    def unique_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('Повторяющийся ключ JSON')
            obj[key] = value
        return obj
    try:
        document = json.loads(text, object_pairs_hook=unique_pairs)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError('Нужен корректный JSON без пояснений и Markdown') from exc
    return validate_plan(document)


def preview_plan(root, text):
    title, steps = parse_plan(text)
    normalized = workspace.normalized_root(root)
    return (f'Папка: {normalized}\nНазвание: {title}\nЭтапы ({len(steps)}):\n'
            + '\n'.join(f'{i}. {LABELS[kind]}' for i, kind in enumerate(steps, 1))
            + '\n\nТолько локальные операции. Все этапы запускаются по отдельному подтверждению.')


def create_from_plan(root, text, *, approved=False):
    """Persist a reviewed sequence; never execute steps during creation."""
    title, steps = parse_plan(text)
    base = str(workspace.normalized_root(root))
    if not approved:
        raise PermissionError('Для создания сценария нужно явное подтверждение')
    with core.db() as conn:
        init(conn)
        cur = conn.execute('INSERT INTO workflows(created,root,title,status) VALUES(?,?,?,?)',
                           (int(time.time()), base, title, 'active'))
        wid = cur.lastrowid
        for position, kind in enumerate(steps, 1):
            conn.execute('INSERT INTO workflow_steps(workflow_id,position,kind,status) VALUES(?,?,?,?)',
                         (wid, position, kind, 'pending'))
    core.audit('workflow_plan_created', 'approved', f'#{wid}: {len(steps)} этапов')
    return wid


def create(root, template):
    if template not in TEMPLATES:
        raise ValueError('Неизвестный шаблон сценария')
    base = str(workspace.normalized_root(root))
    title, kinds = TEMPLATES[template]
    with core.db() as conn:
        init(conn)
        cur = conn.execute('INSERT INTO workflows(created,root,title,status) VALUES(?,?,?,?)',
                           (int(time.time()), base, title, 'active'))
        workflow_id = cur.lastrowid
        for position, kind in enumerate(kinds, 1):
            conn.execute('INSERT INTO workflow_steps(workflow_id,position,kind,status) VALUES(?,?,?,?)',
                         (workflow_id, position, kind, 'pending'))
    core.audit('workflow_created', 'approved', f'#{workflow_id}: {title}')
    return workflow_id


def list_all(limit=100):
    with core.db() as conn:
        init(conn)
        return conn.execute('SELECT id,root,title,status FROM workflows ORDER BY id DESC LIMIT ?',
                            (max(1, min(int(limit), 100)),)).fetchall()


def details(workflow_id):
    with core.db() as conn:
        init(conn)
        header = conn.execute('SELECT id,root,title,status FROM workflows WHERE id=?', (int(workflow_id),)).fetchone()
        if not header:
            raise ValueError('Сценарий не найден')
        steps = conn.execute('SELECT id,position,kind,status,result FROM workflow_steps WHERE workflow_id=? ORDER BY position',
                             (int(workflow_id),)).fetchall()
    return header, steps


def next_step(workflow_id):
    header, steps = details(workflow_id)
    if header[3] != 'active':
        return None
    for step in steps:
        if step[3] != 'done':
            return step if step[3] in ('pending', 'failed') else None
    return None


def preview(workflow_id):
    header, steps = details(workflow_id)
    step = next_step(workflow_id)
    if not step:
        return 'Нет этапов, ожидающих подтверждения.'
    return (f'Сценарий #{header[0]}: {header[2]}\nПапка: {header[1]}\n'
            f'Этап {step[1]} из {len(steps)}: {LABELS[step[2]]}\n\n'
            'Работает локально. Не исполняет код проекта и не передаёт его в сеть.\n'
            'Аудит читает исходные файлы, снимок сохраняет пути/хэши в SQLite.\n'
            'Для выполнения этого этапа требуется отдельное подтверждение.')


def execute_step(workflow_id, *, approved=False):
    if not approved:
        raise PermissionError('Требуется отдельное подтверждение каждого этапа')
    workflow_id = int(workflow_id)
    with core.db() as conn:
        init(conn)
        # Claim one step in a write transaction, preventing double execution.
        conn.execute('BEGIN IMMEDIATE')
        header = conn.execute('SELECT root,status FROM workflows WHERE id=?', (workflow_id,)).fetchone()
        if not header or header[1] != 'active':
            raise ValueError('Сценарий завершён или не найден')
        step = conn.execute('''SELECT id,kind,status FROM workflow_steps
            WHERE workflow_id=? AND status!='done' ORDER BY position LIMIT 1''', (workflow_id,)).fetchone()
        if not step or step[2] not in ('pending', 'failed'):
            raise ValueError('Нет доступного этапа либо этап уже выполняется')
        step_id, kind, _ = step
        if kind not in LABELS:
            raise ValueError('Недопустимая операция сценария')
        conn.execute("UPDATE workflow_steps SET status='running',updated=? WHERE id=? AND status IN ('pending','failed')",
                     (int(time.time()), step_id))
    try:
        root = workspace.normalized_root(header[0])
        if kind == 'audit':
            report = project_audit.scan(root)
            result = project_audit.render(report)
        elif kind == 'snapshot':
            snap_id, scan = project_snapshots.create(root, f'Сценарий #{workflow_id}')
            result = (f'Снимок #{snap_id}. Файлов: {len(scan["files"])}; '
                      f'пропущено: {scan["skipped"]}; неполный: {scan["truncated"]}.')
        else:
            raise ValueError('Недопустимый этап')
        result = result[:64000]
    except Exception as exc:
        # Errors can contain paths, but never source contents in normal operations.
        message = f'{type(exc).__name__}: {str(exc)[:1000]}'
        with core.db() as conn:
            init(conn)
            conn.execute("UPDATE workflow_steps SET status='failed',result=?,updated=? WHERE id=? AND status='running'",
                         (message, int(time.time()), step_id))
        core.audit('workflow_step', 'failed', f'#{workflow_id}, {kind}')
        raise
    with core.db() as conn:
        init(conn)
        conn.execute("UPDATE workflow_steps SET status='done',result=?,updated=? WHERE id=? AND status='running'",
                     (result, int(time.time()), step_id))
        remaining = conn.execute("SELECT COUNT(*) FROM workflow_steps WHERE workflow_id=? AND status!='done'", (workflow_id,)).fetchone()[0]
        if not remaining:
            conn.execute("UPDATE workflows SET status='done' WHERE id=? AND status='active'", (workflow_id,))
    core.audit('workflow_step', 'approved', f'#{workflow_id}, {kind}')
    return result


def cancel(workflow_id, *, approved=False):
    if not approved:
        raise PermissionError('Нужно подтверждение отмены')
    with core.db() as conn:
        init(conn)
        running = conn.execute("SELECT COUNT(*) FROM workflow_steps WHERE workflow_id=? AND status='running'", (int(workflow_id),)).fetchone()[0]
        if running:
            raise ValueError('Нельзя отменить выполняющийся этап')
        cur = conn.execute("UPDATE workflows SET status='cancelled' WHERE id=? AND status='active'", (int(workflow_id),))
        if cur.rowcount != 1:
            raise ValueError('Сценарий не найден или уже завершён')
    core.audit('workflow_cancelled', 'approved', f'#{workflow_id}')


def list_interrupted(min_age_seconds=86400, now=None):
    """Show abandoned-looking stages; never auto-retry a write or audit.

    A running stage may still belong to another instance. Only stages older
    than one day are eligible for manual reclassification.
    """
    current = int(time.time()) if now is None else int(now)
    cutoff = current - max(86400, int(min_age_seconds))
    with core.db() as conn:
        init(conn)
        return conn.execute('''SELECT s.id,s.workflow_id,s.kind,s.updated
            FROM workflow_steps s JOIN workflows w ON w.id=s.workflow_id
            WHERE w.status='active' AND s.status='running' AND s.updated<=?
            ORDER BY s.id''', (cutoff,)).fetchall()


def mark_interrupted(workflow_id, *, approved=False, now=None):
    """Mark old running steps failed, without rerunning them.

    If a prior process actually finished its external side-effect, the user
    must inspect the result before authorizing a new attempt.
    """
    if not approved:
        raise PermissionError('Нужно отдельное разрешение на восстановление статуса')
    current = int(time.time()) if now is None else int(now)
    cutoff = current - 86400
    with core.db() as conn:
        init(conn)
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute('''SELECT s.id FROM workflow_steps s
            JOIN workflows w ON w.id=s.workflow_id
            WHERE w.id=? AND w.status='active' AND s.status='running'
            AND s.updated<=?''', (int(workflow_id), cutoff)).fetchall()
        if not rows:
            raise ValueError('Нет прерванных этапов старше 24 часов')
        for (step_id,) in rows:
            conn.execute('''UPDATE workflow_steps
                SET status='failed',result='Этап прерван. Перед повтором проверьте результаты предыдущей попытки.',updated=?
                WHERE id=? AND status='running' ''', (current, step_id))
    core.audit('workflow_recovery', 'approved', f'#{workflow_id}; stages={len(rows)}')
    return len(rows)
