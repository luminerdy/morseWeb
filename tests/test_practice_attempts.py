import unittest

from practice_attempts import MAX_TIMING_EVENTS, normalize_timing_events, timing_summary


class TimingSummaryTests(unittest.TestCase):
    def test_timing_summary_splits_gap_types_and_scores_rhythm(self):
        summary = timing_summary([
            {"type": "symbol", "symbol": ".", "duration_ms": 100},
            {"type": "gap", "gap_type": "symbol", "duration_ms": 100},
            {"type": "symbol", "symbol": "-", "duration_ms": 300},
            {"type": "gap", "gap_type": "letter", "duration_ms": 300},
            {"type": "symbol", "symbol": ".", "duration_ms": 110},
            {"type": "gap", "gap_type": "symbol", "duration_ms": 95},
            {"type": "symbol", "symbol": "-", "duration_ms": 310},
        ])

        self.assertEqual(2, summary["dot_count"])
        self.assertEqual(2, summary["dash_count"])
        self.assertEqual(2, summary["symbol_gap_count"])
        self.assertEqual(1, summary["letter_gap_count"])
        self.assertEqual(98, summary["avg_symbol_gap_ms"])
        self.assertEqual(300, summary["avg_letter_gap_ms"])
        self.assertEqual(300, summary["min_letter_gap_ms"])
        self.assertEqual(300, summary["max_letter_gap_ms"])
        self.assertGreaterEqual(summary["dot_consistency"], 95)
        self.assertGreaterEqual(summary["dash_consistency"], 95)
        self.assertGreaterEqual(summary["overall_rhythm_score"], 80)
        self.assertTrue(summary["primary_rhythm_feedback"])

    def test_timing_summary_handles_missing_letters_without_score_noise(self):
        summary = timing_summary([
            {"type": "symbol", "symbol": ".", "duration_ms": 100},
            {"type": "gap", "gap_type": "symbol", "duration_ms": 100},
            {"type": "symbol", "symbol": "-", "duration_ms": 300},
        ])

        self.assertIsNone(summary["avg_letter_gap_ms"])
        self.assertIsNone(summary["spacing_score"])
        self.assertIsNotNone(summary["overall_rhythm_score"])

    def test_normalize_timing_events_caps_large_browser_payloads(self):
        events = [
            {"type": "symbol", "symbol": ".", "duration_ms": 100}
            for _ in range(MAX_TIMING_EVENTS + 25)
        ]

        normalized = normalize_timing_events(events)

        self.assertEqual(MAX_TIMING_EVENTS, len(normalized))


if __name__ == "__main__":
    unittest.main()
