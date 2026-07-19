"""SQLite storage for morseWeb.

Replaces morsePi's per-student JSON/JSONL files with a single SQLite
database. Two shapes of data:

- documents: named JSON blobs per user (practice progress, learning
  state, timing settings) - the learning core operates on these dicts
  unchanged from morsePi.
- attempts: append-only practice/word/bonus attempt records with the
  raw key timing events preserved.

Phase 2 adds real accounts: users carry auth fields (email, password
hash, role, parent link, consent) and the current user is tracked in a
context variable set per request, never in cross-request module state.
All SQL lives in this module so a later move to Postgres touches only
this file.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "morseweb.sqlite3"
DEFAULT_USER_SLUG = "operator"
DEFAULT_USER_NAME = "Operator"

ROLES = ("admin", "parent", "student")

_lock = threading.Lock()
_initialized_paths = set()
_current_user = ContextVar("morseweb_current_user", default=None)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    email TEXT,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    parent_id INTEGER REFERENCES users(id),
    email_verified INTEGER NOT NULL DEFAULT 0,
    consent_at TEXT,
    consent_by INTEGER REFERENCES users(id),
    is_active INTEGER NOT NULL DEFAULT 1
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

CREATE TABLE IF NOT EXISTS progress_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL
);
"""

# Columns added since the Phase 1 schema, applied to existing databases.
USER_MIGRATIONS = {
    "email": "ALTER TABLE users ADD COLUMN email TEXT",
    "password_hash": "ALTER TABLE users ADD COLUMN password_hash TEXT",
    "role": "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'",
    "parent_id": "ALTER TABLE users ADD COLUMN parent_id INTEGER REFERENCES users(id)",
    "email_verified": "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0",
    "consent_at": "ALTER TABLE users ADD COLUMN consent_at TEXT",
    "consent_by": "ALTER TABLE users ADD COLUMN consent_by INTEGER REFERENCES users(id)",
    "is_active": "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
}

USER_FIELDS = (
    "slug", "name", "email", "password_hash", "role", "parent_id",
    "email_verified", "consent_at", "consent_by", "is_active",
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def configure(db_path):
    """Point storage at a database file (used by the app and by tests)."""
    global DB_PATH
    with _lock:
        DB_PATH = Path(db_path)
        _current_user.set(None)


def _apply_schema(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    for column, statement in USER_MIGRATIONS.items():
        if column not in existing:
            conn.execute(statement)
    # After the column migrations so it works on Phase 1 databases too.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email"
        " ON users (email) WHERE email IS NOT NULL"
    )
    conn.commit()


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
                _apply_schema(conn)
                _initialized_paths.add(key)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# --- current user (request-scoped) -----------------------------------

def set_current_user(user_id):
    _current_user.set(user_id)


def clear_current_user():
    _current_user.set(None)


def current_user_id():
    """The user all document/attempt operations apply to.

    The web app sets this per request from the login session. Scripts
    and single-user dev fall back to the shared default user.
    """
    user_id = _current_user.get()
    if user_id is None:
        user_id = ensure_user()
        _current_user.set(user_id)
    return user_id


# --- users ------------------------------------------------------------

def _user_dict(row):
    return dict(row) if row is not None else None


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


def create_user(slug, name, email=None, password_hash=None, role="student",
                parent_id=None, email_verified=False, consent_at=None, consent_by=None):
    """Insert a user; raises sqlite3.IntegrityError on duplicate slug/email."""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO users (slug, name, created_at, email, password_hash, role,"
            " parent_id, email_verified, consent_at, consent_by, is_active)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (slug, name, now_iso(), email, password_hash, role,
             parent_id, int(bool(email_verified)), consent_at, consent_by),
        )
        return cursor.lastrowid


def get_user(user_id):
    with _connect() as conn:
        return _user_dict(conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_by_slug(slug):
    with _connect() as conn:
        return _user_dict(conn.execute(
            "SELECT * FROM users WHERE slug = ?", (slug,)).fetchone())


def get_user_by_email(email):
    with _connect() as conn:
        return _user_dict(conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)).fetchone())


def update_user(user_id, **fields):
    unknown = set(fields) - set(USER_FIELDS)
    if unknown:
        raise ValueError(f"unknown user fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with _connect() as conn:
        conn.execute(
            f"UPDATE users SET {assignments} WHERE id = ?",
            (*fields.values(), user_id),
        )


def list_children(parent_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE parent_id = ? ORDER BY created_at",
            (parent_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_users():
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    return [dict(row) for row in rows]


def user_usage(user_id):
    """Attempt counts and last activity for the admin/parent views."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS attempts, MAX(timestamp) AS last_attempt"
            " FROM attempts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return {
        "attempts": row["attempts"] or 0,
        "last_attempt": row["last_attempt"] or "",
    }


def backup_and_reset_user(user_id, reason=""):
    """Snapshot a user's documents and attempts, then delete them.

    Replaces morsePi's desktop admin reset: the student starts fresh but
    nothing is lost - the snapshot lands in progress_backups.
    """
    with _connect() as conn:
        documents = conn.execute(
            "SELECT name, body, updated_at FROM documents WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        attempts = conn.execute(
            "SELECT kind, timestamp, body FROM attempts WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        snapshot = {
            "documents": [dict(row) for row in documents],
            "attempts": [dict(row) for row in attempts],
        }
        cursor = conn.execute(
            "INSERT INTO progress_backups (user_id, created_at, reason, body)"
            " VALUES (?, ?, ?, ?)",
            (user_id, now_iso(), reason, json.dumps(snapshot, sort_keys=True)),
        )
        conn.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM attempts WHERE user_id = ?", (user_id,))
        return cursor.lastrowid


def list_backups(user_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, reason FROM progress_backups"
            " WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# --- documents and attempts (always scoped to the current user) -------

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
