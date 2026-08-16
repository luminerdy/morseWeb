"""Word bank content and adaptive rotation, ported from morsePi's
app.py (verified against its source on 2026-08-15) and adapted to
morseWeb's per-user, storage-backed attempt history."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import learning
import storage
from webtest import WebTestCase


class WordBankContentTests(unittest.TestCase):
    def test_bank_has_eighty_words_no_duplicates(self):
        self.assertEqual(80, len(learning.word_practice_bank))
        self.assertEqual(80, len(set(learning.word_practice_bank)))

    def test_original_forty_two_words_preserved(self):
        original = {
            "AM", "AN", "AS", "AT", "IN", "IS", "IT", "ME", "NO", "ON", "SO", "TO",
            "EAT", "SAT", "SIT", "SET", "SEE", "SEA", "TEA", "TEN", "NET", "MEN",
            "MET", "MAT", "MAN", "SON", "NOT", "TOO", "ANT", "MOM", "MINE", "NAME",
            "MEAN", "MEAT", "MOON", "SOON", "TEAM", "TONE", "NOTE", "SEAT", "STEM",
            "STONE",
        }
        self.assertTrue(original.issubset(set(learning.word_practice_bank)))

    def test_du_and_cwhl_tier_words_present(self):
        for word in ("AND", "SOUND", "ROUND", "TUNE"):
            self.assertIn(word, learning.word_practice_bank)
        for word in ("HELLO", "WORLD", "CLOCK", "HOUSE"):
            self.assertIn(word, learning.word_practice_bank)

    def test_every_word_uses_only_letters_from_its_unlock_tier(self):
        # Every word must be spellable from starter + unlock-group letters,
        # since available_word_practice_words filters on exactly that.
        all_letters = set(letter for letter in learning.all_practice_letters)
        for word in learning.word_practice_bank:
            self.assertTrue(set(word) <= all_letters, word)


class AdaptiveWordSelectionTests(unittest.TestCase):
    def setUp(self):
        self.words = ["AM", "AN", "AS", "AT"]

    def test_completed_words_from_correct_attempts_only(self):
        attempts = [
            {"word": "am", "correct": True},
            {"word": "AN", "correct": False},
            {"word": "AS", "correct": True},
        ]
        self.assertEqual({"AM", "AS"}, learning.completed_word_practice_words(attempts))

    def test_ranked_reviews_sorts_weakest_first(self):
        attempts = [
            {"word": "AM", "correct": True},
            {"word": "AM", "correct": True},
            {"word": "AN", "correct": True},
            {"word": "AN", "correct": False},
        ]
        ranked = learning.ranked_word_practice_reviews(self.words, attempts)
        # AN: 1/2 = 50% accuracy: weaker than AM's 100%, so it ranks first.
        self.assertEqual(["AN", "AM"], ranked)

    def test_select_candidate_prefers_unfinished_in_unfinished_phase(self):
        # phase 0 is "unfinished" in word_practice_phases.
        choice = learning.select_word_practice_candidate(0, ["AT"], ["AM"])
        self.assertEqual("AT", choice)

    def test_select_candidate_falls_back_to_reviews_when_nothing_unfinished(self):
        choice = learning.select_word_practice_candidate(0, [], ["AM"])
        self.assertEqual("AM", choice)

    def test_select_candidate_cycles_past_current_word(self):
        choice = learning.select_word_practice_candidate(
            0, ["AM", "AN", "AS"], [], current_word="AM")
        self.assertEqual("AN", choice)

    def test_select_candidate_returns_empty_when_nothing_available(self):
        self.assertEqual("", learning.select_word_practice_candidate(0, [], []))


class AdaptiveWordPracticeItemTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.parent_id = self.logged_in_parent()
        storage.set_current_user(self.parent_id)

    def unlock_word_practice(self):
        active = learning.starter_practice_letters + ["S", "O"]
        progress = {}
        for letter in active:
            progress[letter] = {
                mode: {
                    "attempts": 10, "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10, "strength": 1.0,
                }
                for mode in learning.practice_modes
            }
        storage.set_document("practice_progress", progress)
        storage.set_document("learning_state", {
            "groups": {"SO": {"first_learning_date": "2000-01-01", "letters": ["S", "O"]}},
            "last_learning_start_date": "2000-01-01",
        })

    def test_returns_none_before_word_practice_unlocks(self):
        self.assertIsNone(learning.adaptive_word_practice_item())

    def test_returns_a_word_from_the_available_set_once_unlocked(self):
        self.unlock_word_practice()
        item = learning.adaptive_word_practice_item()
        self.assertIsNotNone(item)
        self.assertIn(item["word"], learning.available_word_practice_words())
        self.assertEqual(item["morse"], learning.text_to_morse(item["word"]))
        self.assertIn(item["next_word"], learning.available_word_practice_words())

    def test_requested_word_honored_when_available(self):
        self.unlock_word_practice()
        available = learning.available_word_practice_words()
        item = learning.adaptive_word_practice_item(requested_word=available[0].lower())
        self.assertEqual(available[0], item["word"])

    def test_unrequested_or_unavailable_word_falls_back_to_selection(self):
        self.unlock_word_practice()
        item = learning.adaptive_word_practice_item(requested_word="ZZZZ-not-a-word")
        self.assertIn(item["word"], learning.available_word_practice_words())


class WordsNextRouteTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.parent_id = self.logged_in_parent()
        storage.set_current_user(self.parent_id)

    def unlock_word_practice(self):
        active = learning.starter_practice_letters + ["S", "O"]
        progress = {}
        for letter in active:
            progress[letter] = {
                mode: {
                    "attempts": 10, "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10, "strength": 1.0,
                }
                for mode in learning.practice_modes
            }
        storage.set_document("practice_progress", progress)
        storage.set_document("learning_state", {
            "groups": {"SO": {"first_learning_date": "2000-01-01", "letters": ["S", "O"]}},
            "last_learning_start_date": "2000-01-01",
        })

    def test_locked_before_unlock_returns_400(self):
        response = self.client.post("/words/next", json={})
        self.assertEqual(400, response.status_code)
        self.assertEqual("locked", response.get_json()["status"])

    def test_unlocked_returns_a_word_payload(self):
        self.unlock_word_practice()
        response = self.client.post("/words/next", json={"phase": 0})
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual("ok", payload["status"])
        for key in ("word", "morse", "phase", "next_phase", "next_word", "total", "letters"):
            self.assertIn(key, payload)

    def test_requires_login_or_demo(self):
        anonymous = self.app.test_client()
        response = anonymous.post("/words/next", json={})
        self.assertEqual(302, response.status_code)
        self.assertIn("/login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
