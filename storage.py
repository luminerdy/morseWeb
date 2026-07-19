"""SQLite storage for morseWeb.

Replaces morsePi's per-student JSON/JSONL files with a single SQLite
database. Two shapes of data:

- documents: named JSON blobs per user (practice progress, learning
  state, timing settings) - the learning core operates on these dicts
  unchanged from morsePi.
- attempts: append-only practice/word/bonus attempt records with the
  raw key timing events preserved.

Phase 1 uses a single default user; Phase 2 adds real accounts on the
same schema. All SQL lives in this module so a later move to Postgres
touches only this file.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/morseweb.sqlite3")
DEFAULT_USER_SLUG = "operator"
DEFAULT_USER_NAME = "Operator"

_lock = threading.Lock()
_initialized_paths = set()
_current_user_id = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, name)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_user_kind_time
    ON attempts (user_id, kind, timestamp);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def configure(db_path):
    """Point storage at a database file (used by the app and by tests)."""
    global DB_PATH, _current_user_id
    with _lock:
        DB_PATH = Path(db_path)
        _current_user_id = None


@contextmanager
def _connect():
    """Yield a connection that commits on success and always closes.

    sqlite3's own context manager leaves the connection open, which keeps
    the database file locked on Windows; closing here lets tests delete
    their temp directories.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    key = str(DB_PATH.resolve())
    if key not in _initialized_paths:
        with _lock:
            if key not in _initialized_paths:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(SCHEMA)
                conn.commit()
                _initialized_paths.add(key)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def ensure_user(slug=DEFAULT_USER_SLUG, name=DEFAULT_USER_NAME):
    with _connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE slug = ?", (slug,)).fetchone()
        if row:
            return row["id"]
        cursor = conn.execute(
            "INSERT INTO users (slug, name, created_at) VALUES (?, ?, ?)",
            (slug, name, now_iso()),
        )
        return cursor.lastrowid


def set_current_user(user_id):
    global _current_user_id
    _current_user_id = user_id


def current_user_id():
    global _current_user_id
    if _current_user_id is None:
        _current_user_id = ensure_user()
    return _current_user_id


def get_document(name, default=None):
    with _connect() as conn:
        row = conn.execute(
            "SELECT body FROM documents WHERE user_id = ? AND name = ?",
            (current_user_id(), name),
        ).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["body"])
    except (ValueError, TypeError):
        return default


def set_document(name, value):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO documents (user_id, name, body, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (user_id, name) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
            (current_user_id(), name, json.dumps(value, sort_keys=True), now_iso()),
        )
        conn.commit()


def append_attempt(kind, record):
    """Store an attempt record. Preserves a caller-supplied timestamp
    (importer, tests); stamps now otherwise."""
    normalized = dict(record)
    normalized.setdefault("timestamp", now_iso())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO attempts (user_id, kind, timestamp, body) VALUES (?, ?, ?, ?)",
            (current_user_id(), kind, normalized["timestamp"], json.dumps(normalized, sort_keys=True)),
        )
        conn.commit()
    return normalized


def load_attempts(kind):
    """All attempts of one kind for the current user, in insert order."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT body FROM attempts WHERE user_id = ? AND kind = ? ORDER BY id",
            (current_user_id(), kind),
        ).fetchall()
    records = []
    for row in rows:
        try:
            records.append(json.loads(row["body"]))
        except (ValueError, TypeError):
            continue
    return records
