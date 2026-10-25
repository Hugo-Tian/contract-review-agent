"""Explicit local snapshots; originals and unsaved documents remain ephemeral."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


@contextmanager
def connect():
    path = Path(os.getenv('HISTORY_DB', str(Path(__file__).resolve().parents[2] / 'data' / 'history.sqlite3')))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, name TEXT, created TEXT, body TEXT)')
    try:
        with db:
            yield db
    finally:
        db.close()


def save(snapshot):
    identifier = uuid.uuid4().hex
    created = datetime.now(timezone.utc).isoformat()
    snapshot = {**snapshot, 'id': identifier, 'created': created}
    with connect() as db:
        db.execute('INSERT INTO snapshots VALUES (?,?,?,?)', (identifier, snapshot['document']['name'], created, json.dumps(snapshot, ensure_ascii=False)))
    return snapshot


def listing():
    with connect() as db:
        return [{'id': r[0], 'name': r[1], 'created': r[2]} for r in db.execute('SELECT id,name,created FROM snapshots ORDER BY created DESC LIMIT 200')]


def get(identifier):
    with connect() as db:
        row = db.execute('SELECT body FROM snapshots WHERE id=?', (identifier,)).fetchone()
    return json.loads(row[0]) if row else None


def delete(identifier):
    with connect() as db:
        db.execute('DELETE FROM snapshots WHERE id=?', (identifier,))
