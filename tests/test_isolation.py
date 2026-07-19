"""Per-user data isolation - the Phase 2 exit criterion.

Two users practice through their own logged-in sessions; each sees only
their own attempts, progress, and settings.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage
from webtest import WebTestCase


class IsolationTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.alice_id = self.create_parent(email="alice@example.com", slug="alice", name="Alice")
        self.bob_id = self.create_parent(email="bob@example.com", slug="bob", name="Bob")

        self.alice = self.app.test_client()
        self.bob = self.app.test_client()
        self.login("alice@example.com", client=self.alice)
        self.login("bob@example.com", client=self.bob)

    def test_attempts_do_not_cross_users(self):
        self.alice.post("/practice/result", json={
            "target": "E", "mode": "send", "actual_morse": ".",
        })

        storage.set_current_user(self.alice_id)
        self.assertEqual(1, len(storage.load_attempts("practice")))

        storage.set_current_user(self.bob_id)
        self.assertEqual(0, len(storage.load_attempts("practice")))

    def test_concurrent_practice_keeps_progress_separate(self):
        for _ in range(3):
            self.alice.post("/practice/result", json={
                "target": "E", "mode": "send", "actual_morse": ".",
            })
        self.bob.post("/practice/result", json={
            "target": "T", "mode": "send", "actual_morse": "-",
        })

        storage.set_current_user(self.alice_id)
        alice_progress = storage.get_document("practice_progress")
        self.assertEqual(3, alice_progress["E"]["send"]["attempts"])
        self.assertEqual(0, alice_progress["T"]["send"]["attempts"])

        storage.set_current_user(self.bob_id)
        bob_progress = storage.get_document("practice_progress")
        self.assertEqual(1, bob_progress["T"]["send"]["attempts"])
        self.assertEqual(0, bob_progress["E"]["send"]["attempts"])

    def test_progress_page_shows_only_own_attempts(self):
        for _ in range(5):
            self.alice.post("/practice/result", json={
                "target": "E", "mode": "send", "actual_morse": ".",
            })

        bob_page = self.bob.get("/progress").data
        self.assertIn(b"0 tries", bob_page)

    def test_timing_settings_are_per_user(self):
        self.alice.post("/timing-settings", data={
            "character_wpm": "20", "effective_wpm": "10", "tone_hz": "800",
        })

        storage.set_current_user(self.bob_id)
        self.assertIsNone(storage.get_document("timing_settings"))
        self.assertIn(b"12/6 WPM", self.bob.get("/").data)
        self.assertIn(b"20/10 WPM", self.alice.get("/").data)

    def test_practice_target_is_per_user(self):
        storage.set_current_user(self.alice_id)
        storage.set_document("practice_state", {"target": "A", "feedback": ""})

        storage.set_current_user(self.bob_id)
        storage.set_document("practice_state", {"target": "M", "feedback": ""})

        alice_page = self.alice.get("/practice").data
        bob_page = self.bob.get("/practice").data
        self.assertIn(b'data-practice-target="A"', alice_page)
        self.assertIn(b'data-practice-target="M"', bob_page)


if __name__ == "__main__":
    unittest.main()
