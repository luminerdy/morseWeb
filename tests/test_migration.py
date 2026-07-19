"""Upgrading a Phase 1 database in place must work - the deployed EC2
instance will carry one."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage

PHASE1_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE documents (
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, name)
);
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    body TEXT NOT NULL
);
"""


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "morseweb.sqlite3"

        conn = sqlite3.connect(self.db_path)
        conn.executescript(PHASE1_SCHEMA)
        conn.execute(
            "INSERT INTO users (slug, name, created_at) VALUES (?, ?, ?)",
            ("operator", "Operator", "2026-07-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO documents (user_id, name, body, updated_at)"
            " VALUES (1, 'practice_progress', '{}', '2026-07-01T00:00:00+00:00')",
        )
        conn.commit()
        conn.close()

        storage.configure(self.db_path)

    def tearDown(self):
        storage.configure(Path("data/morseweb.sqlite3"))
        self.temp_dir.cleanup()

    def test_phase1_database_gains_auth_columns_and_keeps_data(self):
        user = storage.get_user_by_slug("operator")
        self.assertIsNotNone(user)
        self.assertEqual("student", user["role"])
        self.assertEqual(1, user["is_active"])
        self.assertIsNone(user["email"])

        storage.set_current_user(user["id"])
        self.assertEqual({}, storage.get_document("practice_progress"))

    def test_migrated_database_accepts_new_style_users(self):
        parent_id = storage.create_user(
            slug="parent", name="Parent", email="parent@example.com",
            password_hash="x", role="parent", email_verified=True,
        )
        self.assertEqual("parent", storage.get_user(parent_id)["role"])

        with self.assertRaises(sqlite3.IntegrityError):
            storage.create_user(
                slug="parent2", name="Duplicate", email="parent@example.com",
                password_hash="x", role="parent",
            )


if __name__ == "__main__":
    unittest.main()
