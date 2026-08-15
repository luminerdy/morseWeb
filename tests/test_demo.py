"""No-signup demo mode (Phase 4): anonymous try-it practice sessions
that reuse the real login-gated routes without a real account."""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage
from webtest import WebTestCase


class DemoModeTests(WebTestCase):
    def test_anonymous_without_demo_still_redirected_to_login(self):
        # Regression: a plain anonymous visitor (no /demo yet) must keep
        # the old @login_required behavior on the practice routes.
        for path in ("/practice", "/progress"):
            response = self.client.get(path)
            self.assertEqual(302, response.status_code, path)
            self.assertIn("/login", response.headers["Location"])

    def test_starting_demo_creates_session_and_unlocks_practice(self):
        response = self.client.post("/demo", follow_redirects=False)
        self.assertEqual(302, response.status_code)
        self.assertIn("/practice", response.headers["Location"])

        with self.client.session_transaction() as sess:
            demo_id = sess.get("demo_user_id")
        self.assertIsNotNone(demo_id)

        demo_user = storage.get_user(demo_id)
        self.assertEqual("demo", demo_user["role"])
        self.assertIsNone(demo_user["email"])
        self.assertIsNone(demo_user["password_hash"])

        self.assertEqual(200, self.client.get("/practice").status_code)
        self.assertEqual(200, self.client.get("/progress").status_code)

    def test_demo_user_can_record_a_practice_attempt(self):
        self.client.post("/demo")
        response = self.client.post("/practice/result", json={
            "target": "E", "mode": "send", "actual_morse": ".",
        })
        payload = response.get_json()
        self.assertEqual("recorded", payload["status"])

        with self.client.session_transaction() as sess:
            demo_id = sess["demo_user_id"]
        storage.set_current_user(demo_id)
        self.assertEqual(1, len(storage.load_attempts("practice")))

    def test_repeated_demo_posts_reuse_the_same_user(self):
        self.client.post("/demo")
        with self.client.session_transaction() as sess:
            first_id = sess["demo_user_id"]

        self.client.post("/demo")
        with self.client.session_transaction() as sess:
            second_id = sess["demo_user_id"]

        self.assertEqual(first_id, second_id)
        self.assertEqual(1, len(
            [u for u in storage.list_users(include_demo=True) if u["role"] == "demo"]))

    def test_logged_in_user_posting_demo_does_not_create_demo_account(self):
        self.logged_in_parent()
        before = storage.count_demo_users()

        response = self.client.post("/demo", follow_redirects=False)
        self.assertEqual(302, response.status_code)
        self.assertIn("/practice", response.headers["Location"])
        self.assertEqual(before, storage.count_demo_users())

        with self.client.session_transaction() as sess:
            self.assertNotIn("demo_user_id", sess)

    def test_two_demo_sessions_are_isolated(self):
        alice = self.app.test_client()
        bob = self.app.test_client()
        alice.post("/demo")
        bob.post("/demo")

        alice.post("/practice/result", json={
            "target": "E", "mode": "send", "actual_morse": ".",
        })

        with alice.session_transaction() as sess:
            alice_id = sess["demo_user_id"]
        with bob.session_transaction() as sess:
            bob_id = sess["demo_user_id"]

        self.assertNotEqual(alice_id, bob_id)
        storage.set_current_user(bob_id)
        self.assertEqual(0, len(storage.load_attempts("practice")))
        storage.set_current_user(alice_id)
        self.assertEqual(1, len(storage.load_attempts("practice")))

    def test_demo_session_cannot_reach_family_or_admin(self):
        self.client.post("/demo")
        for path in ("/family", "/admin"):
            response = self.client.get(path)
            self.assertEqual(302, response.status_code, path)
            self.assertIn("/login", response.headers["Location"])

    def test_admin_user_list_excludes_demo_accounts(self):
        self.client.post("/demo")
        self.assertEqual(0, len(storage.list_users()))
        self.assertEqual(1, len(storage.list_users(include_demo=True)))

    def test_home_shows_try_it_button_only_when_fully_anonymous(self):
        anon_page = self.client.get("/").data
        self.assertIn(b'action="/demo"', anon_page)

        self.client.post("/demo")
        demo_page = self.client.get("/").data
        self.assertNotIn(b'action="/demo"', demo_page)
        self.assertIn(b"Demo mode", demo_page)


class PurgeDemoUsersTests(WebTestCase):
    def _backdate(self, user_id, hours_ago):
        conn = sqlite3.connect(storage.DB_PATH)
        try:
            with conn:
                conn.execute(
                    "UPDATE users SET created_at = datetime('now', ?) WHERE id = ?",
                    (f"-{hours_ago} hours", user_id),
                )
        finally:
            conn.close()

    def test_purge_removes_stale_demo_users_and_their_data(self):
        stale_id = storage.create_demo_user()
        storage.set_current_user(stale_id)
        storage.append_attempt("practice", {"target": "E", "correct": True})
        self._backdate(stale_id, 30)

        fresh_id = storage.create_demo_user()

        purged = storage.purge_demo_users(older_than_hours=24)

        self.assertEqual(1, purged)
        self.assertIsNone(storage.get_user(stale_id))
        self.assertIsNotNone(storage.get_user(fresh_id))

        storage.set_current_user(stale_id)
        self.assertEqual([], storage.load_attempts("practice"))

    def test_purge_does_not_touch_real_accounts(self):
        parent_id = self.create_parent()
        self._backdate(parent_id, 200)

        storage.purge_demo_users(older_than_hours=1)

        self.assertIsNotNone(storage.get_user(parent_id))


if __name__ == "__main__":
    unittest.main()
