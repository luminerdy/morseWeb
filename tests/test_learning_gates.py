import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage



try:
    learning_module = importlib.import_module("learning")
except ModuleNotFoundError as error:
    learning_module = None
    IMPORT_ERROR = error
else:
    IMPORT_ERROR = None


@unittest.skipIf(learning_module is None, f"learning dependencies unavailable: {IMPORT_ERROR}")
class LearningGateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        storage.configure(self.base / "morseweb.sqlite3")

    def tearDown(self):
        storage.configure(Path("data/morseweb.sqlite3"))
        self.temp_dir.cleanup()

    def make_attempts(self, total, correct, target="E", mode="send"):
        attempts = []

        for index in range(total):
            attempts.append(
                {
                    "correct": index < correct,
                    "target": target,
                    "mode": mode,
                    "timestamp": f"{learning_module.today_key()}T00:{index:02d}:00+00:00",
                }
            )

        return attempts

    def write_progress(self, letters, strength_by_mode):
        progress = {}

        for letter in letters:
            progress[letter] = {}
            for mode, strength in strength_by_mode.items():
                progress[letter][mode] = {
                    "attempts": 10,
                    "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10,
                    "strength": strength,
                }

        storage.set_document("practice_progress", progress)

    def write_learning_state(self, groups, last_learning_start_date=""):
        storage.set_document(
            "learning_state",
            {
                "groups": groups,
                "last_learning_start_date": last_learning_start_date,
            },
        )

    def write_word_attempts(self, total, correct, word="AM", timestamp="2026-06-21T00:00:00+00:00"):
        lines = []
        for index in range(total):
            lines.append(
                json.dumps(
                    {
                        "correct": index < correct,
                        "timestamp": timestamp,
                        "word": word,
                    },
                    sort_keys=True,
                )
            )

        for line in lines:
            storage.append_attempt("word", json.loads(line))

    def all_modes(self, strength):
        return {mode: strength for mode in learning_module.practice_modes}

    def test_fresh_student_starts_with_six_letters_and_no_learning_now(self):
        state = learning_module.get_practice_letter_state()
        overall = learning_module.get_learning_overall(state["active_letters"])

        self.assertEqual(["E", "T", "A", "N", "I", "M"], state["active_letters"])
        self.assertEqual([], state["learning_letters"])
        self.assertEqual("6/26", overall["alphabet_progress"])
        self.assertEqual(0, overall["current_mastery"])

    def test_next_letters_do_not_unlock_below_100_current_set_mastery(self):
        self.write_progress(learning_module.starter_practice_letters, self.all_modes(0.99))

        state = learning_module.get_practice_letter_state()
        overall = learning_module.get_learning_overall(state["active_letters"])

        self.assertEqual([], state["learning_letters"])
        self.assertEqual(["S", "O"], overall["next_unlock"]["letters"])
        self.assertEqual(99, overall["current_mastery"])
        self.assertIn("current-set mastery", overall["next_goal"])

    def test_next_letters_enter_learning_now_at_100_current_set_mastery(self):
        self.write_progress(learning_module.starter_practice_letters, self.all_modes(1.0))

        state = learning_module.get_practice_letter_state()
        learn_letters = learning_module.get_practice_letters_for_mode("learn")
        send_letters = learning_module.get_practice_letters_for_mode("send")

        self.assertEqual(["S", "O"], state["learning_letters"])
        self.assertEqual(["S", "O"], learn_letters)
        self.assertEqual(["E", "T", "A", "N", "I", "M"], send_letters)

    def test_word_practice_unlocks_after_s_o_join_active_set(self):
        self.write_progress(learning_module.starter_practice_letters, self.all_modes(1.0))

        locked = learning_module.word_practice_summary(learning_module.starter_practice_letters)

        self.assertFalse(locked["unlocked"])
        self.assertEqual([], locked["words"])

        active_letters = learning_module.starter_practice_letters + ["S", "O"]
        unlocked = learning_module.word_practice_summary(active_letters)
        item = learning_module.word_practice_item(0, active_letters)

        self.assertTrue(unlocked["unlocked"])
        self.assertIn("SO", unlocked["words"])
        self.assertEqual("AM", item["word"])
        self.assertEqual(".- --", item["morse"])

    def test_started_learning_group_continues_when_current_set_dips(self):
        self.write_progress(learning_module.starter_practice_letters, self.all_modes(0.0))
        self.write_learning_state(
            {
                "SO": {
                    "first_learning_date": "2026-06-21",
                    "letters": ["S", "O"],
                }
            },
            last_learning_start_date="2026-06-21",
        )

        state = learning_module.get_practice_letter_state()
        saved_state = storage.get_document("learning_state")

        self.assertEqual(["S", "O"], state["learning_letters"])
        self.assertEqual(["S", "O"], saved_state["groups"]["SO"]["letters"])
        self.assertEqual("2026-06-21", saved_state["last_learning_start_date"])

    def test_completed_learning_group_graduates_when_current_set_dips(self):
        progress = {}

        for letter in learning_module.starter_practice_letters:
            progress[letter] = {
                mode: {
                    "attempts": 10,
                    "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10,
                    "strength": 1.0,
                }
                for mode in learning_module.practice_modes
            }

        progress["M"]["send"]["strength"] = 0.98
        for letter in ["S", "O"]:
            progress[letter] = {
                "learn": {
                    "attempts": 10,
                    "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10,
                    "strength": 1.0,
                }
            }

        storage.set_document("practice_progress", progress)
        self.write_learning_state(
            {
                "SO": {
                    "first_learning_date": "2000-01-01",
                    "letters": ["S", "O"],
                }
            },
            last_learning_start_date="2000-01-01",
        )

        state = learning_module.get_practice_letter_state()
        overall = learning_module.get_learning_overall(state["active_letters"])

        self.assertEqual([], state["learning_letters"])
        self.assertEqual(["E", "T", "A", "N", "I", "M", "S", "O"], state["active_letters"])
        self.assertEqual("8/26", overall["alphabet_progress"])
        self.assertLess(overall["current_mastery"], 100)

    def test_learning_group_graduates_after_burn_in(self):
        progress = {}
        for letter in learning_module.starter_practice_letters:
            progress[letter] = {
                mode: {
                    "attempts": 10,
                    "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10,
                    "strength": 1.0,
                }
                for mode in learning_module.practice_modes
            }

        for letter in ["S", "O"]:
            progress[letter] = {
                "learn": {
                    "attempts": 10,
                    "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10,
                    "strength": 0.70,
                }
            }

        storage.set_document("practice_progress", progress)
        self.write_learning_state(
            {
                "SO": {
                    "first_learning_date": "2000-01-01",
                    "letters": ["S", "O"],
                }
            },
            last_learning_start_date="2000-01-01",
        )

        state = learning_module.get_practice_letter_state()
        overall = learning_module.get_learning_overall(state["active_letters"])

        self.assertEqual([], state["learning_letters"])
        self.assertEqual(["E", "T", "A", "N", "I", "M", "S", "O"], state["active_letters"])
        self.assertEqual("8/26", overall["alphabet_progress"])

    def test_daily_mission_summary_caps_display_and_marks_complete(self):
        original_loader = learning_module.load_today_attempts
        learning_module.load_today_attempts = lambda: self.make_attempts(total=22, correct=18)

        try:
            daily = learning_module.daily_mission_summary()
        finally:
            learning_module.load_today_attempts = original_loader

        self.assertEqual(22, daily["attempts"])
        self.assertEqual(20, daily["display_attempts"])
        self.assertEqual(0, daily["remaining"])
        self.assertEqual(100, daily["progress"])
        self.assertEqual(82, daily["accuracy"])
        self.assertTrue(daily["completed"])
        self.assertEqual("Daily mission complete.", daily["message"])

    def test_effort_summary_counts_close_practice_without_idle_time(self):
        attempts = [
            {"timestamp": "2026-06-21T00:00:00+00:00"},
            {"timestamp": "2026-06-21T00:01:00+00:00"},
            {"timestamp": "2026-06-21T00:20:00+00:00"},
        ]

        effort = learning_module.effort_summary(attempts)

        self.assertEqual(3, effort["attempts"])
        self.assertEqual(120, effort["seconds"])
        self.assertEqual(2, effort["minutes"])
        self.assertEqual("2 min", effort["label"])

    def test_try_again_win_detects_miss_then_correct(self):
        attempts = [
            {"correct": False, "timestamp": "2026-06-21T00:00:00+00:00"},
            {"correct": True, "timestamp": "2026-06-21T00:01:00+00:00"},
        ]

        self.assertTrue(learning_module.has_try_again_win(attempts))

    def test_student_badges_reward_focused_practice_and_try_again(self):
        daily = {
            "attempt_progress": 50,
            "completed": False,
            "effort": {"minutes": 12},
            "accuracy": 50,
            "remaining": 10,
            "try_again_win": True,
            "learning_focus": {"active": False, "complete": True},
        }
        overall = {
            "alphabet_mastered": 6,
            "current_mastery": 0,
        }

        badges = learning_module.student_badges(overall, daily)
        labels = [badge["label"] for badge in badges["earned"]]

        self.assertIn("Focused Practice", labels)
        self.assertIn("Try Again Champ", labels)
        self.assertEqual("Daily Signal Complete", badges["next"]["label"])

    def test_daily_mission_caps_letter_previews_for_touch_layout(self):
        all_letters = learning_module.alphabet_letters
        self.write_progress(all_letters, self.all_modes(1.0))
        self.write_learning_state(
            {
                learning_module.step_key(step): {
                    "first_learning_date": "2000-01-01",
                    "letters": step["letters"],
                }
                for step in learning_module.letter_unlock_steps
                if all(letter.isalpha() for letter in step["letters"])
            },
            last_learning_start_date="2000-01-01",
        )
        original_loader = learning_module.load_today_attempts
        learning_module.load_today_attempts = lambda: [
            {
                "correct": True,
                "target": letter,
                "mode": "send",
                "timestamp": f"{learning_module.today_key()}T00:00:00+00:00",
            }
            for letter in all_letters
        ]

        try:
            daily = learning_module.daily_mission_summary()
        finally:
            learning_module.load_today_attempts = original_loader

        self.assertEqual(12, len(daily["active_letters_preview"]))
        self.assertEqual(len(all_letters) - 12, daily["active_letters_remaining_count"])
        self.assertEqual(8, len(daily["letters_preview"]))
        self.assertEqual(len(all_letters) - 8, daily["letters_remaining_count"])

    def test_daily_mission_learning_now_keeps_mission_open_until_learn_ready(self):
        self.write_progress(learning_module.starter_practice_letters, self.all_modes(1.0))
        progress = storage.get_document("practice_progress")
        progress["S"] = {
            "learn": {
                "attempts": 6,
                "correct": 6,
                "last_seen": "2026-06-21T00:00:00+00:00",
                "streak": 6,
                "strength": 1.0,
            }
        }
        progress["O"] = {
            "learn": {
                "attempts": 5,
                "correct": 5,
                "last_seen": "2026-06-21T00:00:00+00:00",
                "streak": 5,
                "strength": 1.0,
            }
        }
        storage.set_document("practice_progress", progress)

        original_loader = learning_module.load_today_attempts
        learning_module.load_today_attempts = lambda: self.make_attempts(total=22, correct=18)

        try:
            daily = learning_module.daily_mission_summary()
        finally:
            learning_module.load_today_attempts = original_loader

        self.assertEqual(["S", "O"], daily["learning_letters"])
        self.assertEqual(20, daily["learning_focus"]["goal"])
        self.assertEqual(11, daily["learning_focus"]["correct"])
        self.assertEqual(9, daily["learning_focus"]["remaining"])
        self.assertEqual(55, daily["learning_focus"]["progress"])
        self.assertEqual(78, daily["progress"])
        self.assertFalse(daily["completed"])
        self.assertIn("needs", daily["message"])
        badges = learning_module.student_badges(learning_module.get_learning_overall(learning_module.starter_practice_letters), daily)
        self.assertEqual("New Signals Ready", badges["next"]["label"])
        self.assertIn("S needs", badges["next"]["detail"])

    def test_daily_mission_completed_learning_waits_for_short_break(self):
        self.write_progress(learning_module.starter_practice_letters, self.all_modes(1.0))
        progress = storage.get_document("practice_progress")
        for letter in ["S", "O"]:
            progress[letter] = {
                "learn": {
                    "attempts": 10,
                    "correct": 10,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 10,
                    "strength": 1.0,
                }
            }
        storage.set_document("practice_progress", progress)

        original_loader = learning_module.load_today_attempts
        learning_module.load_today_attempts = lambda: self.make_attempts(total=22, correct=18)

        try:
            daily = learning_module.daily_mission_summary()
        finally:
            learning_module.load_today_attempts = original_loader

        self.assertEqual(["S", "O"], daily["learning_letters"])
        self.assertEqual(20, daily["learning_focus"]["correct"])
        self.assertTrue(daily["completed"])
        self.assertIn("Take a short break", daily["message"])
        self.assertEqual("Break", daily["next_action"]["label"])
        self.assertEqual("Take A Break", daily["next_action"]["title"])

    def test_next_letters_require_correct_words_after_current_set_mastery(self):
        active_letters = learning_module.starter_practice_letters + ["S", "O"]
        self.write_progress(active_letters, self.all_modes(1.0))
        self.write_learning_state(
            {
                "SO": {
                    "first_learning_date": "2000-01-01",
                    "letters": ["S", "O"],
                }
            },
            last_learning_start_date="2000-01-01",
        )

        state = learning_module.get_practice_letter_state()
        overall = learning_module.get_learning_overall(state["active_letters"])

        self.assertEqual([], state["learning_letters"])
        self.assertEqual(["R", "K"], state["next_step"]["letters"])
        self.assertTrue(state["locked_until_tomorrow"])
        self.assertIn("5 more correct Words", overall["next_goal"])

    def test_next_letters_open_after_words_and_rest_gate(self):
        active_letters = learning_module.starter_practice_letters + ["S", "O"]
        self.write_progress(active_letters, self.all_modes(1.0))
        self.write_learning_state(
            {
                "SO": {
                    "first_learning_date": "2000-01-01",
                    "letters": ["S", "O"],
                }
            },
            last_learning_start_date="2000-01-01",
        )
        for index in range(learning_module.word_ready_correct_attempts):
            storage.append_attempt(
                "word",
                {
                    "word": "AM",
                    "correct": True,
                    "timestamp": f"2026-06-21T00:0{index}:00+00:00",
                },
            )

        state = learning_module.get_practice_letter_state()

        self.assertEqual(["R", "K"], state["learning_letters"])

    def test_student_badges_reward_daily_accuracy_and_mastery(self):
        self.write_progress(learning_module.all_practice_letters, self.all_modes(1.0))
        self.write_learning_state(
            {
                learning_module.step_key(step): {
                    "first_learning_date": "2000-01-01",
                    "letters": step["letters"],
                }
                for step in learning_module.letter_unlock_steps
            },
            last_learning_start_date="2000-01-01",
        )
        original_loader = learning_module.load_today_attempts
        learning_module.load_today_attempts = lambda: self.make_attempts(total=20, correct=19)

        try:
            state = learning_module.get_practice_letter_state()
            overall = learning_module.get_learning_overall(state["active_letters"])
            daily = learning_module.daily_mission_summary()
            badges = learning_module.student_badges(overall, daily)
        finally:
            learning_module.load_today_attempts = original_loader

        labels = [badge["label"] for badge in badges["earned"]]
        self.assertIn("Daily Signal Complete", labels)
        self.assertIn("Clean Copy", labels)
        self.assertIn("First Signals Mastered", labels)
        self.assertEqual("Daily Signal Complete", badges["featured"]["label"])
        self.assertEqual("Try Again Champ", badges["next"]["label"])

    def test_daily_next_action_prefers_learning_now(self):
        state = {
            "active_letters": ["E", "T", "A", "N", "I", "M"],
            "learning_letters": ["S", "O"],
            "learning_status": None,
            "locked_until_tomorrow": False,
            "next_step": None,
        }

        action = learning_module.daily_next_action(state)
        coach = learning_module.daily_practice_coach(state)

        self.assertEqual("learn", action["mode"])
        self.assertEqual("Learn S O", action["title"])
        self.assertEqual("Practice Next", coach["headline"])
        self.assertEqual(["S", "O"], [item["letter"] for item in coach["practice_next"]])
        self.assertTrue(all(item["mode"] == "learn" for item in coach["practice_next"]))
        self.assertEqual("Learning", coach["boost_label"])
        self.assertEqual(["S", "O"], [item["letter"] for item in coach["signal_boost"]])

    def test_progress_details_show_learning_now_for_learn_mode(self):
        active_letters = learning_module.starter_practice_letters + ["S", "O"]
        self.write_progress(active_letters, self.all_modes(1.0))
        self.write_word_attempts(learning_module.word_ready_correct_attempts, learning_module.word_ready_correct_attempts)
        progress = storage.get_document("practice_progress")
        progress["R"] = {
            "learn": {
                "attempts": 7,
                "correct": 7,
                "last_seen": "2026-06-22T00:00:00+00:00",
                "streak": 7,
                "strength": 1.0,
            }
        }
        progress["K"] = {
            "learn": {
                "attempts": 9,
                "correct": 8,
                "last_seen": "2026-06-22T00:00:00+00:00",
                "streak": 5,
                "strength": 1.0,
            }
        }
        storage.set_document("practice_progress", progress)
        self.write_learning_state(
            {
                "SO": {
                    "first_learning_date": "2026-06-20",
                    "letters": ["S", "O"],
                }
            },
            last_learning_start_date="2026-06-20",
        )

        details = learning_module.get_progress_mode_details()

        self.assertEqual("Learning Now", details["learn"]["scope_label"])
        self.assertEqual("Learning R K", details["learn"]["summary_label"])
        self.assertEqual(["R", "K"], [item["letter"] for item in details["learn"]["letters"]])
        self.assertEqual(75, details["learn"]["score"]["mastery"])
        self.assertEqual("15/20 Learn", details["learn"]["score"]["completion_label"])
        self.assertEqual("R needs 3 more correct Learn tries", details["learn"]["score"]["next_goal"])
        self.assertEqual("Current Set", details["send"]["scope_label"])
        self.assertEqual(100, details["send"]["score"]["mastery"])

    def test_practice_coach_recommends_weakest_letter_and_mode(self):
        progress = {}

        for letter in learning_module.starter_practice_letters:
            progress[letter] = {
                mode: {
                    "attempts": 8,
                    "correct": 8,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 8,
                    "strength": 1.0,
                }
                for mode in learning_module.practice_modes
            }

        progress["M"]["listen"] = {
            "attempts": 3,
            "correct": 1,
            "last_seen": "2026-06-21T00:00:00+00:00",
            "streak": 0,
            "strength": 0.0,
        }
        storage.set_document("practice_progress", progress)

        state = {
            "active_letters": learning_module.starter_practice_letters,
            "learning_letters": [],
        }
        coach = learning_module.daily_practice_coach(state)
        first = coach["practice_next"][0]

        self.assertEqual("Practice Coach", coach["headline"])
        self.assertEqual("M", first["letter"])
        self.assertEqual("listen", first["mode"])
        self.assertEqual("Listen", first["mode_label"])
        self.assertEqual("0%", first["reason"])
        self.assertEqual("M", coach["signal_boost"][0]["letter"])

    def test_practice_coach_does_not_repeat_strong_letters_as_boosts(self):
        progress = {}

        for letter in learning_module.starter_practice_letters:
            progress[letter] = {
                mode: {
                    "attempts": 8,
                    "correct": 8,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 8,
                    "strength": 1.0,
                }
                for mode in learning_module.practice_modes
            }

        storage.set_document("practice_progress", progress)

        state = {
            "active_letters": learning_module.starter_practice_letters,
            "learning_letters": [],
        }
        coach = learning_module.daily_practice_coach(state)
        strong_letters = {item["letter"] for item in coach["strong_signals"]}
        boost_letters = {item["letter"] for item in coach["signal_boost"]}

        self.assertFalse(strong_letters & boost_letters)

    def test_daily_next_action_points_to_weakest_mode_when_no_learning_now(self):
        progress = {}

        for letter in learning_module.starter_practice_letters:
            progress[letter] = {
                mode: {
                    "attempts": 8,
                    "correct": 8,
                    "last_seen": "2026-06-21T00:00:00+00:00",
                    "streak": 8,
                    "strength": 1.0,
                }
                for mode in learning_module.practice_modes
            }

        for letter in learning_module.starter_practice_letters:
            progress[letter]["echo"]["strength"] = 0.25
        storage.set_document("practice_progress", progress)

        state = {
            "active_letters": learning_module.starter_practice_letters,
            "learning_letters": [],
            "locked_until_tomorrow": False,
            "next_step": {"letters": ["S", "O"], "threshold": 100, "label": "Signal Builder"},
        }
        action = learning_module.daily_next_action(state)

        self.assertEqual("echo", action["mode"])
        self.assertEqual("Practice Echo", action["title"])
        self.assertIn("most room", action["detail"])


if __name__ == "__main__":
    unittest.main()
