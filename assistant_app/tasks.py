"""Persistent user-controlled task checklist; never executes tasks autonomously."""
from __future__ import annotations
import time
from . import core

VALID_STATES = {'planned', 'in_progress', 'done', 'cancelled'}


def init(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS tasks
        (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, title TEXT NOT NULL,
         description TEXT NOT NULL, state TEXT NOT NULL)''')


def create(title, description=''):
    title, description = title.strip(), description.strip()
    if not 1 <= len(title) <= 200 or len(description) > 5000:
        raise ValueError('Задача должна содержать заголовок (до 200 символов) и описание до 5000 символов')
    with core.db() as conn:
        init(conn)
        cur = conn.execute('INSERT INTO tasks(ts,title,description,state) VALUES(?,?,?,?)',
                           (int(time.time()), title, description, 'planned'))
        return cur.lastrowid


def list_all():
    with core.db() as conn:
        init(conn)
        return conn.execute('SELECT id,title,description,state FROM tasks ORDER BY id DESC').fetchall()


def set_state(task_id, new_state):
    if new_state not in VALID_STATES:
        raise ValueError('Недопустимый статус задачи')
    with core.db() as conn:
        init(conn)
        cur = conn.execute('UPDATE tasks SET state=? WHERE id=?', (new_state, int(task_id)))
        if cur.rowcount != 1:
            raise ValueError('Задача не найдена')


def delete(task_id):
    with core.db() as conn:
        init(conn)
        cur = conn.execute('DELETE FROM tasks WHERE id=?', (int(task_id),))
        if cur.rowcount != 1:
            raise ValueError('Задача не найдена')
