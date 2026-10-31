"""Ephemeral in-memory SQLite. No contract or report is written to disk."""
import sqlite3
import threading
import time
from .schemas import Document

connection = sqlite3.connect(':memory:', check_same_thread=False)
connection.execute('CREATE TABLE documents (id TEXT PRIMARY KEY, body TEXT, expires REAL)')
connection.execute('CREATE TABLE versions (id TEXT, version INTEGER, body TEXT, expires REAL, PRIMARY KEY(id,version))')
connection.execute('CREATE TABLE reports (id TEXT PRIMARY KEY, body TEXT, expires REAL)')
connection.execute('CREATE TABLE tools (id TEXT, version INTEGER, name TEXT, body TEXT, PRIMARY KEY(id,version,name))')
lock = threading.Lock()
TTL = 3600


def cleanup():
    with lock, connection:
        connection.execute('DELETE FROM documents WHERE expires < ?', (time.time(),))
        connection.execute('DELETE FROM versions WHERE expires < ?', (time.time(),))
        connection.execute('DELETE FROM reports WHERE expires < ?', (time.time(),))
        connection.execute('DELETE FROM tools WHERE id NOT IN (SELECT id FROM documents)')


def put(doc: Document):
    cleanup()
    with lock, connection:
        count = connection.execute('SELECT count(*) FROM documents').fetchone()[0]
        exists = connection.execute('SELECT id FROM documents WHERE id=?', (doc.id,)).fetchone()
        if count >= 20 and not exists:
            raise ValueError('临时文档已达到 20 份，请先清除已有文档或重启服务。')
        connection.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?)',
                           (doc.id, doc.model_dump_json(), time.time() + TTL))
        connection.execute('INSERT OR IGNORE INTO versions VALUES (?,?,?,?)', (doc.id, doc.version, doc.model_dump_json(), time.time() + TTL))


def get(doc_id: str):
    cleanup()
    with lock:
        row = connection.execute('SELECT body FROM documents WHERE id=?', (doc_id,)).fetchone()
    return Document.model_validate_json(row[0]) if row else None


def delete(doc_id: str):
    with lock, connection:
        connection.execute('DELETE FROM documents WHERE id=?', (doc_id,))
        connection.execute('DELETE FROM versions WHERE id=?', (doc_id,))
        connection.execute('DELETE FROM tools WHERE id=?', (doc_id,))
        connection.execute('DELETE FROM reports WHERE json_extract(body,\'$.document.id\')=?', (doc_id,))


def get_version(doc_id, version):
    cleanup()
    with lock:
        row = connection.execute('SELECT body FROM versions WHERE id=? AND version=?', (doc_id, version)).fetchone()
    return Document.model_validate_json(row[0]) if row else None


def versions(doc_id):
    cleanup()
    with lock:
        return [r[0] for r in connection.execute('SELECT version FROM versions WHERE id=? ORDER BY version', (doc_id,))]


def put_report(identifier, snapshot):
    import json
    with lock, connection:
        connection.execute('INSERT OR REPLACE INTO reports VALUES (?,?,?)', (identifier, json.dumps(snapshot, ensure_ascii=False), time.time() + TTL))


def get_report(identifier):
    import json
    cleanup()
    with lock:
        row = connection.execute('SELECT body FROM reports WHERE id=?', (identifier,)).fetchone()
    return json.loads(row[0]) if row else None


def put_tool(doc_id, version, name, result):
    import json
    with lock, connection:
        connection.execute('INSERT OR REPLACE INTO tools VALUES (?,?,?,?)', (doc_id, version, name, json.dumps(result, ensure_ascii=False)))


def get_tools(doc_id, version):
    import json
    with lock:
        return {r[0]: json.loads(r[1]) for r in connection.execute('SELECT name,body FROM tools WHERE id=? AND version=?', (doc_id, version))}


def delete_tool(doc_id, version, name):
    with lock, connection:
        connection.execute('DELETE FROM tools WHERE id=? AND version=? AND name=?', (doc_id, version, name))
