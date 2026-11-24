"""Review queue for inert file changes. No execution without a separately approved step."""
from __future__ import annotations
import time
from . import core, proposals, workspace


def init(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS review_steps (
        id INTEGER PRIMARY KEY, batch TEXT NOT NULL, created INTEGER NOT NULL,
        workspace TEXT NOT NULL, relative_path TEXT NOT NULL, content TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT ''
    )""")

def enqueue(root, proposal):
    # Validate ALL changes first, never commit anything here.
    drafts = proposals.prepare_drafts(root, proposal)
    if not drafts:
        return []
    import uuid
    batch = uuid.uuid4().hex
    with core.db() as conn:
        init(conn)
        ids = []
        for (name, draft) in drafts:
            cur = conn.execute('INSERT INTO review_steps(batch,created,workspace,relative_path,content,state) VALUES(?,?,?,?,?,?)',
                (batch,int(time.time()),str(workspace.normalized_root(root)),name,draft['new_text'],'pending'))
            ids.append(cur.lastrowid)
        return ids

def pending(limit=150):
    with core.db() as conn:
        init(conn)
        return conn.execute('SELECT id,batch,relative_path,state,workspace FROM review_steps ORDER BY id DESC LIMIT ?',
                            (max(1,min(int(limit),250)),)).fetchall()

def preview(step_id):
    with core.db() as conn:
        init(conn)
        row = conn.execute('SELECT workspace,relative_path,content,state FROM review_steps WHERE id=?', (int(step_id),)).fetchone()
    if not row:
        raise ValueError('Этап не найден')
    root, name, content, state = row
    if state != 'pending':
        raise ValueError('Этап уже обработан')
    return root, name, workspace.draft_change(root,name,content)

def decide(step_id, decision, approved=False, draft=None, backup_dir=None):
    if decision not in ('apply','reject'):
        raise ValueError('Некорректное решение')
    if not approved:
        raise PermissionError('Требуется отдельное подтверждение пользователя')
    with core.db() as conn:
        init(conn)
        row = conn.execute('SELECT workspace,relative_path,content,state FROM review_steps WHERE id=?', (int(step_id),)).fetchone()
        if not row or row[3] != 'pending':
            raise ValueError('Этап уже обработан или отсутствует')
        root, name, content, _ = row
        if decision == 'apply':
            if draft is None or backup_dir is None or draft.get('new_text') != content or \
                    workspace.safe_path(root,name,existing=False) != workspace.safe_path(root,draft['path'],existing=False):
                raise ValueError('Предпросмотр не совпадает с ожидаемым изменением')
            backup = workspace.apply_change(root, draft, backup_dir)
            note = 'backup=' + backup
            state = 'applied'
        else:
            note = ''
            state = 'rejected'
        conn.execute("UPDATE review_steps SET state=?,note=? WHERE id=? AND state='pending'", (state,note,int(step_id)))
        return state
