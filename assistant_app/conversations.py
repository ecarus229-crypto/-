"""Independent chats. Legacy single-chat history is imported once and left untouched."""
from __future__ import annotations
import time
from . import core


def init(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS conversations
        (id INTEGER PRIMARY KEY, title TEXT NOT NULL, created INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS conversation_messages
        (id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id),
         ts INTEGER NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, provider TEXT NOT NULL DEFAULT '')''')
    conn.execute('CREATE INDEX IF NOT EXISTS conversation_msg_idx ON conversation_messages(conversation_id,id)')
    conn.execute('CREATE TABLE IF NOT EXISTS conversation_migrations(name TEXT PRIMARY KEY)')
    if not conn.execute("SELECT 1 FROM conversation_migrations WHERE name='legacy_history'").fetchone():
        old = conn.execute('SELECT ts,role,text,COALESCE(provider,\'\') FROM history ORDER BY id').fetchall()
        if old:
            cur = conn.execute('INSERT INTO conversations(title,created) VALUES(?,?)', ('Импортированная история', int(time.time())))
            conn.executemany('INSERT INTO conversation_messages(conversation_id,ts,role,text,provider) VALUES(?,?,?,?,?)',
                             [(cur.lastrowid, *item) for item in old])
        conn.execute("INSERT INTO conversation_migrations(name) VALUES('legacy_history')")
    if not conn.execute('SELECT 1 FROM conversations LIMIT 1').fetchone():
        conn.execute('INSERT INTO conversations(title,created) VALUES(?,?)', ('Новый диалог', int(time.time())))


def list_all():
    with core.db() as conn:
        init(conn)
        return conn.execute('SELECT id,title FROM conversations ORDER BY id DESC').fetchall()


def create(title='Новый диалог'):
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError('Название диалога должно содержать 1–120 символов')
    with core.db() as conn:
        init(conn)
        return conn.execute('INSERT INTO conversations(title,created) VALUES(?,?)', (title, int(time.time()))).lastrowid


def rename(cid, title):
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError('Название диалога должно содержать 1–120 символов')
    with core.db() as conn:
        init(conn)
        if conn.execute('UPDATE conversations SET title=? WHERE id=?', (title, int(cid))).rowcount != 1:
            raise ValueError('Диалог не найден')


def delete(cid):
    with core.db() as conn:
        init(conn)
        if conn.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] <= 1:
            raise ValueError('Нельзя удалить последний диалог')
        if not conn.execute('SELECT 1 FROM conversations WHERE id=?', (int(cid),)).fetchone():
            raise ValueError('Диалог не найден')
        conn.execute('DELETE FROM conversation_messages WHERE conversation_id=?', (int(cid),))
        conn.execute('DELETE FROM conversations WHERE id=?', (int(cid),))


def add_message(cid, role, text, provider=''):
    if role not in ('user', 'assistant') or not isinstance(text, str) or len(text) > 200000:
        raise ValueError('Некорректное сообщение')
    with core.db() as conn:
        init(conn)
        if not conn.execute('SELECT 1 FROM conversations WHERE id=?', (int(cid),)).fetchone():
            raise ValueError('Диалог не найден')
        return conn.execute('INSERT INTO conversation_messages(conversation_id,ts,role,text,provider) VALUES(?,?,?,?,?)',
                            (int(cid),int(time.time()),role,text,provider)).lastrowid


def history(cid, limit=24):
    limit = max(1, min(int(limit), 100000))
    with core.db() as conn:
        init(conn)
        return list(reversed(conn.execute('SELECT role,text FROM conversation_messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?',
                                          (int(cid),limit)).fetchall()))


def clear(cid):
    with core.db() as conn:
        init(conn)
        conn.execute('DELETE FROM conversation_messages WHERE conversation_id=?', (int(cid),))


def export(cid, path):
    import json
    from pathlib import Path
    rows = history(cid, 100000)
    target = Path(path)
    if target.exists():
        raise FileExistsError('Экспорт не должен заменять существующий файл')
    with target.open('x', encoding='utf-8') as handle:
        json.dump([{'role': role, 'text': text} for role, text in rows], handle, ensure_ascii=False, indent=2)
    return len(rows)


def purge_before(cutoff):
    with core.db() as conn:
        init(conn)
        cur = conn.execute('DELETE FROM conversation_messages WHERE ts < ?', (int(cutoff),))
        return cur.rowcount


def count():
    with core.db() as conn:
        init(conn)
        return conn.execute('SELECT COUNT(*) FROM conversation_messages').fetchone()[0]


def search_messages(query, limit=100):
    """Case-insensitive literal search over saved chats (no SQL wildcards)."""
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 160:
        raise ValueError('Поисковый запрос должен содержать 2–160 символов')
    limit = max(1, min(int(limit), 200))
    # Restrict scanning to 10k recent messages; LIKE is used only for prefiltering.
    with core.db() as conn:
        init(conn)
        rows = conn.execute(
            'SELECT m.id,m.conversation_id,c.title,m.role,m.text,m.ts '
            'FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id '
            'ORDER BY m.id DESC LIMIT 10000').fetchall()
    needle = query.strip().casefold()
    out = []
    for mid,cid,title,role,body,ts in rows:
        pos = body.casefold().find(needle)
        if pos >= 0:
            out.append((mid,cid,title,role,body[max(0,pos-90):pos+len(needle)+130],ts))
            if len(out) >= limit:
                break
    return out
