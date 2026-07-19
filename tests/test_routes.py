import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage
from webtest import WebTestCase


class RouteTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.parent_id = self.logged_in_parent()
        storage.set_current_user(self.parent_id)

    def unlock_word_practice(self):
        import learning
        active = learning.starter_practice_letters + ["S", "O"]
        progress = {}
        for letter in active:
            progress[letter] = {
                mode: {
                    "attempts": 10,
                    "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10,
                    "strength": 1.0,
                }
                for mode in learning.practice_modes
            }
        storage.set_document("practice_progress", progress)
        storage.set_document("learning_state", {
            "groups": {"SO": {"first_learning_date": "2000-01-01", "letters": ["S", "O"]}},
            "last_learning_start_date": "2000-01-01",
        })

    # Pages

    def test_pages_render(self):
        for path in ("/", "/practice", "/progress"):
            response = self.client.get(path)
            self.assertEqual(200, response.status_code, path)

    def test_anonymous_is_redirected_to_login(self):
        anonymous = self.app.test_client()
        for path in ("/practice", "/progress"):
            response = anonymous.get(path)
            self.assertEqual(302, response.status_code, path)
            self.assertIn("/login", response.headers["Location"])

    def test_all_practice_modes_render(self):
        for mode in ("send", "read", "listen", "echo", "learn"):
            response = self.client.get(f"/practice?mode={mode}")
            self.assertEqual(200, response.status_code, mode)

    def test_unknown_mode_falls_back_to_send(self):
        response = self.client.get("/practice?mode=bogus")
        self.assertEqual(200, response.status_code)
        self.assertIn(b'data-practice-mode="send"', response.data)

    def test_message_converts_to_morse(self):
        response = self.client.post("/", data={"message": "SOS"})
        self.assertEqual(200, response.status_code)
        self.assertIn(b"... --- ...", response.data)

    def test_home_renders_for_anonymous_visitors(self):
        anonymous = self.app.test_client()
        response = anonymous.get("/")
        self.assertEqual(200, response.status_code)

    # Timing settings

    def test_timing_settings_persist(self):
        response = self.client.post(
            "/timing-settings",
            data={"character_wpm": "15", "effective_wpm": "8", "tone_hz": "650"},
        )
        self.assertEqual(302, response.status_code)
        response = self.client.get("/")
        self.assertIn(b"15/8 WPM", response.data)

    def test_timing_settings_clamped(self):
        self.client.post(
            "/timing-settings",
            data={"character_wpm": "99", "effective_wpm": "1", "tone_hz": "9999"},
        )
        saved = storage.get_document("timing_settings")
        self.assertEqual(35, saved["character_wpm"])
        self.assertEqual(3, saved["effective_wpm"])
        self.assertEqual(1000, saved["tone_hz"])

    # Practice flow

    def test_practice_next_returns_prompt_payload(self):
        response = self.client.post("/practice/next?mode=send")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        for key in ("target", "expected_morse", "read_choices", "timing", "progress", "score", "overall"):
            self.assertIn(key, payload)
        self.assertIn(payload["target"], ["E", "T", "A", "N", "I", "M"])

    def test_correct_send_attempt_is_recorded(self):
        response = self.client.post("/practice/result", json={
            "target": "E",
            "mode": "send",
            "actual_morse": ".",
            "timing_events": [{"type": "symbol", "symbol": ".", "duration_ms": 90}],
        })
        payload = response.get_json()
        self.assertEqual("recorded", payload["status"])
        self.assertTrue(payload["attempt"]["correct"])
        self.assertEqual(1, len(storage.load_attempts("practice")))
        self.assertIn("timing_summary", storage.load_attempts("practice")[0])

    def test_incorrect_send_attempt_is_recorded(self):
        response = self.client.post("/practice/result", json={
            "target": "E",
            "mode": "send",
            "actual_morse": "-",
        })
        payload = response.get_json()
        self.assertEqual("recorded", payload["status"])
        self.assertFalse(payload["attempt"]["correct"])

    def test_read_attempt_checked_server_side(self):
        response = self.client.post("/practice/result", json={
            "target": "E",
            "mode": "read",
            "answer": "e",
        })
        payload = response.get_json()
        self.assertEqual("recorded", payload["status"])
        self.assertTrue(payload["attempt"]["correct"])
        self.assertEqual("", payload["attempt"]["actual_morse"])

    def test_locked_letter_attempt_is_ignored(self):
        response = self.client.post("/practice/result", json={
            "target": "Q",
            "mode": "send",
            "actual_morse": "--.-",
        })
        self.assertEqual("ignored", response.get_json()["status"])
        self.assertEqual(0, len(storage.load_attempts("practice")))

    def test_client_cannot_forge_correct_flag(self):
        response = self.client.post("/practice/result", json={
            "target": "E",
            "mode": "send",
            "actual_morse": "-",
            "correct": True,
        })
        self.assertFalse(response.get_json()["attempt"]["correct"])

    def test_attempt_metadata_uses_logged_in_user(self):
        self.client.post("/practice/result", json={
            "target": "E", "mode": "send", "actual_morse": ".",
        })
        attempt = storage.load_attempts("practice")[0]
        self.assertEqual(storage.get_user(self.parent_id)["slug"], attempt["student_id"])

    # Bonus sprint

    def test_bonus_flow_records_and_summarizes(self):
        response = self.client.post("/bonus/next")
        self.assertEqual(200, response.status_code)

        response = self.client.post("/bonus/result", json={
            "session_id": "abc123",
            "target": "E",
            "actual_morse": ".",
        })
        payload = response.get_json()
        self.assertEqual("recorded", payload["status"])
        self.assertEqual(1, payload["bonus"]["attempts"])
        self.assertEqual(1, payload["bonus"]["correct"])

    def test_bonus_result_requires_session(self):
        response = self.client.post("/bonus/result", json={"target": "E", "actual_morse": "."})
        self.assertEqual(400, response.status_code)

    # Words

    def test_word_attempt_ignored_before_unlock(self):
        response = self.client.post("/words/result", json={"word": "AM", "actual_morse": ".- --"})
        self.assertEqual(400, response.status_code)

    def test_word_attempt_recorded_after_unlock(self):
        self.unlock_word_practice()
        response = self.client.post("/words/result", json={"word": "AM", "actual_morse": ".- --"})
        payload = response.get_json()
        self.assertEqual("recorded", payload["status"])
        self.assertTrue(payload["attempt"]["correct"])
        self.assertEqual("AM", payload["attempt"]["decoded"])


if __name__ == "__main__":
    unittest.main()
