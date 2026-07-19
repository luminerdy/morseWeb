"""Learning-progression logic for morseWeb.

Extracted from morsePi's app.py (https://github.com/luminerdy/morsePi).
Contains no Flask, GPIO, or audio-hardware code: letter groups, unlock
gates, Farnsworth timing math, daily mission, practice coach, and badges.
"""

import json
import math
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import storage
from morse import text_to_morse, morse_to_text
from practice_attempts import (
    normalize_timing_events,
    rounded_ms,
    timing_summary,
)
from practice_progress import (
    all_mode_details,
    choose_next_letter,
    mode_score,
    overall_score,
    progress_summary,
    record_attempt,
    save_progress,
)

DEFAULT_CHARACTER_WPM = 12
DEFAULT_EFFECTIVE_WPM = 6
DEFAULT_TONE_HZ = 700
KEY_TONE_RETRY_SECONDS = 1.25

LETTER_GAP_THRESHOLD_SECONDS = 0.80
WORD_GAP_THRESHOLD_SECONDS = 1.50
DOT_DASH_THRESHOLD_UNITS = 2.5
DAILY_MISSION_GOAL = 20
DAILY_CELEBRATION_MORSE = "...-"
BONUS_SPRINT_GOAL = 20
EFFORT_MIN_SECONDS_PER_ATTEMPT = 20
EFFORT_MAX_GAP_SECONDS = 180
FOCUSED_PRACTICE_MINUTES = 10

starter_practice_letters = ["E", "T", "A", "N", "I", "M"]
learn_ready_attempts = 10
learn_ready_strength = 70
learn_ready_rest_hours = 3
word_ready_correct_attempts = 5
max_learning_groups_per_day = 2
letter_unlock_groups = [
    {"letters": ["S", "O"], "label": "Signal Builder"},
    {"letters": ["R", "K"], "label": "Rhythm Builder"},
    {"letters": ["D", "U"], "label": "Relay Builder"},
    {"letters": ["C", "W", "H", "L"], "label": "Word Builder"},
    {"letters": ["P", "F", "Y", "G"], "label": "Pattern Builder"},
    {"letters": ["B", "V", "J", "X"], "label": "Code Builder"},
    {"letters": ["Q", "Z"], "label": "Alphabet Builder"},
    {"letters": ["1", "2", "3", "4", "5"], "label": "Number Builder"},
    {"letters": ["6", "7", "8", "9", "0"], "label": "Full Station Operator"},
]
letter_unlock_steps = [
    {
        "threshold": 100,
        "letters": group["letters"],
        "label": group["label"]
    }
    for group in letter_unlock_groups
]
all_practice_letters = starter_practice_letters + [
    letter
    for group in letter_unlock_groups
    for letter in group["letters"]
]
alphabet_letters = [letter for letter in all_practice_letters if letter.isalpha()]
word_practice_unlock_letters = ["S", "O"]
word_practice_bank = [
    "AM", "AN", "AS", "AT", "IN", "IS", "IT", "ME", "NO", "ON", "SO", "TO",
    "EAT", "SAT", "SIT", "SET", "SEE", "SEA", "TEA", "TEN", "NET", "MEN",
    "MET", "MAT", "MAN", "SON", "NOT", "TOO", "ANT", "MOM", "MINE", "NAME",
    "MEAN", "MEAT", "MOON", "SOON", "TEAM", "TONE", "NOTE", "SEAT", "STEM",
    "STONE"
]

MAX_MORSE_CHARS = 600


def limited_text(value, max_chars):
    return str(value or "").strip()[:max_chars]


practice_target = "E"
practice_feedback = ""

practice_modes = {
    "send": {
        "label": "Send",
        "progress_label": "Send Progress"
    },
    "read": {
        "label": "Read",
        "progress_label": "Read Progress"
    },
    "listen": {
        "label": "Listen",
        "progress_label": "Listen Progress"
    },
    "echo": {
        "label": "Echo",
        "progress_label": "Echo Progress"
    },
    "learn": {
        "label": "Learn",
        "progress_label": "Learn Progress"
    }
}



def clamp_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    return max(minimum, min(parsed, maximum))


def default_morse_timing_settings():
    return {
        "character_wpm": DEFAULT_CHARACTER_WPM,
        "effective_wpm": DEFAULT_EFFECTIVE_WPM,
        "tone_hz": DEFAULT_TONE_HZ
    }


def normalize_morse_timing(settings):
    defaults = default_morse_timing_settings()
    character_wpm = clamp_int(settings.get("character_wpm"), defaults["character_wpm"], 5, 35)
    effective_wpm = clamp_int(settings.get("effective_wpm"), defaults["effective_wpm"], 3, character_wpm)
    tone_hz = clamp_int(settings.get("tone_hz"), defaults["tone_hz"], 400, 1000)

    return {
        "character_wpm": character_wpm,
        "effective_wpm": effective_wpm,
        "tone_hz": tone_hz
    }


def load_morse_timing_settings():
    loaded = storage.get_document("timing_settings", {})
    if not isinstance(loaded, dict):
        loaded = {}
    return normalize_morse_timing(loaded)


def save_morse_timing_settings(settings):
    storage.set_document("timing_settings", normalize_morse_timing(settings))


def get_morse_timing():
    settings = load_morse_timing_settings()
    character_wpm = settings["character_wpm"]
    effective_wpm = settings["effective_wpm"]
    tone_hz = settings["tone_hz"]

    character_dot_seconds = 1.2 / character_wpm
    spacing_dot_seconds = 1.2 / effective_wpm

    return {
        "character_wpm": character_wpm,
        "effective_wpm": effective_wpm,
        "tone_hz": tone_hz,
        "dot_seconds": character_dot_seconds,
        "dash_seconds": character_dot_seconds * 3,
        "symbol_gap_seconds": character_dot_seconds,
        "letter_gap_seconds": spacing_dot_seconds * 3,
        "word_gap_seconds": spacing_dot_seconds * 7,
        "dot_ms": round(character_dot_seconds * 1000),
        "dash_ms": round(character_dot_seconds * 3000),
        "symbol_gap_ms": round(character_dot_seconds * 1000),
        "letter_gap_ms": round(spacing_dot_seconds * 3000),
        "word_gap_ms": round(spacing_dot_seconds * 7000),
        "input_dash_threshold_ms": round(character_dot_seconds * DOT_DASH_THRESHOLD_UNITS * 1000)
    }


def get_dot_dash_threshold_seconds():
    return get_morse_timing()["input_dash_threshold_ms"] / 1000


def get_practice_timing(mode, target=None):
    timing = dict(get_morse_timing())
    practice_letters = get_unlocked_practice_letters()

    if mode not in ("listen", "echo"):
        timing["adapted"] = False
        timing["adapted_reason"] = ""
        return timing

    listen_score = mode_score(practice_letters, mode)
    target_summary = next(
        (item for item in progress_summary(practice_letters, mode) if item["letter"] == (target or practice_target)),
        None
    )
    target_needs_help = bool(
        target_summary
        and (target_summary["attempts"] < 3 or target_summary["accuracy"] < 70)
    )

    if listen_score["attempts"] < 10 or listen_score["accuracy"] < 70 or target_needs_help:
        character_wpm = max(8, timing["character_wpm"] - 2)
        effective_wpm = max(4, min(character_wpm, timing["effective_wpm"] - 1))
        character_dot_seconds = 1.2 / character_wpm
        spacing_dot_seconds = 1.2 / effective_wpm

        timing.update({
            "character_wpm": character_wpm,
            "effective_wpm": effective_wpm,
            "dot_seconds": character_dot_seconds,
            "dash_seconds": character_dot_seconds * 3,
            "symbol_gap_seconds": character_dot_seconds,
            "letter_gap_seconds": spacing_dot_seconds * 3,
            "word_gap_seconds": spacing_dot_seconds * 7,
            "dot_ms": round(character_dot_seconds * 1000),
            "dash_ms": round(character_dot_seconds * 3000),
            "symbol_gap_ms": round(character_dot_seconds * 1000),
            "letter_gap_ms": round(spacing_dot_seconds * 3000),
            "word_gap_ms": round(spacing_dot_seconds * 7000),
            "input_dash_threshold_ms": round(character_dot_seconds * DOT_DASH_THRESHOLD_UNITS * 1000),
            "adapted": True,
            "adapted_reason": "Slower Listen practice until accuracy improves"
        })
    else:
        timing["adapted"] = False
        timing["adapted_reason"] = ""

    return timing


morse_timing = load_morse_timing_settings()



def classify_gap(gap_seconds):
    if gap_seconds >= WORD_GAP_THRESHOLD_SECONDS:
        return "word"
    if gap_seconds >= LETTER_GAP_THRESHOLD_SECONDS:
        return "letter"
    return "symbol"



def today_key():
    return datetime.now().date().isoformat()


def parse_attempt_time(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_attempt_records(kind, today_only=False):
    attempts = storage.load_attempts(kind)
    if not today_only:
        return attempts

    today = today_key()
    return [
        attempt for attempt in attempts
        if str(attempt.get("timestamp", ""))[:10] == today
    ]


ATTEMPT_KINDS = ("practice", "word", "bonus")



def attempt_rhythm_summary(attempt):
    events = normalize_timing_events(attempt.get("timing_events", []))
    if events:
        return timing_summary(events)

    summary = attempt.get("timing_summary")
    if isinstance(summary, dict) and summary.get("symbol_count", 0):
        return summary

    return {}


def average_metric(items, key):
    values = [
        item.get("summary", {}).get(key)
        for item in items
        if item.get("summary", {}).get(key) is not None
    ]
    if not values:
        return None

    return int(round(sum(values) / len(values)))


def rhythm_trend_delta(items):
    scored = [
        item for item in items
        if item.get("summary", {}).get("overall_rhythm_score") is not None
    ]
    if len(scored) < 4:
        return None

    window = min(10, len(scored) // 2)
    early = scored[:window]
    recent = scored[-window:]
    early_average = average_metric(early, "overall_rhythm_score")
    recent_average = average_metric(recent, "overall_rhythm_score")
    if early_average is None or recent_average is None:
        return None

    return recent_average - early_average


def rhythm_trend_label(delta):
    if delta is None:
        return "Need more data"
    if delta >= 5:
        return f"Improving +{delta}"
    if delta <= -5:
        return f"Watch trend {delta}"
    return "Steady"


def load_today_attempts():
    return load_attempt_records("practice", today_only=True)


def load_today_effort_attempts():
    attempts = list(load_today_attempts())
    for kind in ("word", "bonus"):
        attempts.extend(load_attempt_records(kind, today_only=True))
    return attempts


def load_all_effort_attempts():
    attempts = []
    for kind in ATTEMPT_KINDS:
        attempts.extend(load_attempt_records(kind, today_only=False))
    return attempts


def effort_summary(attempts):
    timestamps = sorted(
        parsed for parsed in (parse_attempt_time(attempt.get("timestamp")) for attempt in attempts)
        if parsed is not None
    )
    attempt_count = len(timestamps)

    if not attempt_count:
        return {
            "attempts": 0,
            "seconds": 0,
            "minutes": 0,
            "label": "0 min",
        }

    seconds = attempt_count * EFFORT_MIN_SECONDS_PER_ATTEMPT

    for previous, current in zip(timestamps, timestamps[1:]):
        if previous.tzinfo and not current.tzinfo:
            current = current.replace(tzinfo=previous.tzinfo)
        elif current.tzinfo and not previous.tzinfo:
            previous = previous.replace(tzinfo=current.tzinfo)

        gap_seconds = max(0, int(round((current - previous).total_seconds())))
        if gap_seconds <= EFFORT_MAX_GAP_SECONDS:
            seconds += gap_seconds

    minutes = int(round(seconds / 60))
    if seconds > 0 and minutes == 0:
        minutes = 1

    if minutes < 60:
        label = f"{minutes} min"
    else:
        hours = minutes // 60
        remainder = minutes % 60
        label = f"{hours} hr {remainder} min" if remainder else f"{hours} hr"

    return {
        "attempts": attempt_count,
        "seconds": seconds,
        "minutes": minutes,
        "label": label,
    }


def has_try_again_win(attempts):
    sorted_attempts = sorted(
        (
            (parse_attempt_time(attempt.get("timestamp")), attempt)
            for attempt in attempts
            if parse_attempt_time(attempt.get("timestamp")) is not None
        ),
        key=lambda item: item[0],
    )
    saw_miss = False

    for _, attempt in sorted_attempts:
        if attempt.get("correct"):
            if saw_miss:
                return True
            continue

        saw_miss = True

    return False


def grit_coach_line(daily):
    if daily.get("try_again_win"):
        return "You missed one, tried again, and got stronger."

    effort = daily.get("effort", {})
    if effort.get("minutes", 0) >= FOCUSED_PRACTICE_MINUTES:
        return "You gave focused practice time. That is how Morse gets stronger."

    if daily.get("attempts", 0) > 0:
        return "Every careful try helps your signal grow."

    return "Start with one good try. Practice builds the signal."


def daily_mission_summary():
    attempts = load_today_attempts()
    effort_attempts = load_today_effort_attempts()
    effort = effort_summary(effort_attempts)
    try_again_win = has_try_again_win(effort_attempts)
    total = len(attempts)
    correct = sum(1 for attempt in attempts if attempt.get("correct"))
    letters = sorted({str(attempt.get("target", "")).upper() for attempt in attempts if attempt.get("target")})
    modes = sorted({str(attempt.get("mode", "")).title() for attempt in attempts if attempt.get("mode")})
    state = get_practice_letter_state()
    remaining = max(0, DAILY_MISSION_GOAL - total)
    accuracy = int(round((correct / total) * 100)) if total else 0
    attempt_progress = min(100, int(round((total / DAILY_MISSION_GOAL) * 100))) if DAILY_MISSION_GOAL else 100
    learning_focus = daily_learning_focus(state["learning_letters"])
    progress = attempt_progress
    completed = total >= DAILY_MISSION_GOAL

    if learning_focus["active"]:
        progress = int(round((attempt_progress + learning_focus["progress"]) / 2))
        completed = completed and learning_focus["complete"]

    next_action = daily_next_action(state)

    if completed:
        if state["learning_status"] and state["learning_status"].get("needs"):
            message = f"Daily mission complete. {state['learning_status']['next_need'].capitalize()}."
        else:
            message = "Daily mission complete."
    elif learning_focus["active"] and learning_focus["next_need"]:
        message = f"Daily mission: {learning_focus['next_need']}."
    elif state["learning_letters"]:
        message = f"Daily mission: practice today and spend time with {' '.join(state['learning_letters'])}."
    else:
        message = "Daily mission: review every active signal and keep your rhythm steady."

    summary = {
        "date": today_key(),
        "goal": DAILY_MISSION_GOAL,
        "attempts": total,
        "display_attempts": min(total, DAILY_MISSION_GOAL),
        "correct": correct,
        "remaining": remaining,
        "accuracy": accuracy,
        "effort": effort,
        "try_again_win": try_again_win,
        "attempt_progress": attempt_progress,
        "progress": progress,
        "completed": completed,
        "letters": letters,
        "letters_preview": letters[:8],
        "letters_remaining_count": max(0, len(letters) - 8),
        "modes": modes,
        "active_letters": state["active_letters"],
        "active_letters_preview": state["active_letters"][:12],
        "active_letters_remaining_count": max(0, len(state["active_letters"]) - 12),
        "learning_letters": state["learning_letters"],
        "learning_focus": learning_focus,
        "letter_morse": get_practice_letter_morse(),
        "message": message,
        "next_action": next_action,
        "coach": daily_practice_coach(state)
    }
    summary["grit_message"] = grit_coach_line(summary)
    return summary


def _normalized_attempt(record):
    normalized = dict(record)
    normalized["timestamp"] = datetime.now(timezone.utc).isoformat()
    normalized["timing_events"] = normalize_timing_events(normalized.get("timing_events", []))
    normalized["timing_summary"] = timing_summary(normalized["timing_events"])
    return normalized


def append_bonus_attempt(record):
    return storage.append_attempt("bonus", _normalized_attempt(record))


def append_word_attempt(record):
    return storage.append_attempt("word", _normalized_attempt(record))


def load_bonus_attempts(session_id=None):
    attempts = load_attempt_records("bonus")

    if session_id:
        attempts = [a for a in attempts if a.get("session_id") == session_id]

    return attempts


def bonus_sprint_summary(session_id):
    attempts = load_bonus_attempts(session_id)
    total = len(attempts)
    correct = sum(1 for attempt in attempts if attempt.get("correct"))
    streak = 0
    best_streak = 0

    for attempt in attempts:
        if attempt.get("correct"):
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0

    return {
        "goal": BONUS_SPRINT_GOAL,
        "attempts": total,
        "correct": correct,
        "remaining": max(0, BONUS_SPRINT_GOAL - total),
        "accuracy": int(round((correct / total) * 100)) if total else 0,
        "streak": streak,
        "best_streak": best_streak,
        "complete": total >= BONUS_SPRINT_GOAL,
    }


def choose_bonus_sprint_target():
    global practice_target
    practice_target = random.choice(get_unlocked_practice_letters())
    return practice_target


def student_badges(overall, daily):
    earned = []

    def add_badge(badge_id, label, detail, earned_when):
        badge = {
            "id": badge_id,
            "label": label,
            "detail": detail,
            "earned": bool(earned_when),
        }
        if badge["earned"]:
            earned.append(badge)
        return badge

    learning_focus = daily.get("learning_focus", {})
    add_badge(
        "daily-signal-complete",
        "Daily Signal Complete",
        "Finish today's practice count.",
        daily.get("completed"),
    )
    add_badge(
        "clean-copy",
        "Clean Copy",
        "Finish a daily mission with at least 90% accuracy.",
        daily.get("completed") and daily.get("accuracy", 0) >= 90,
    )
    add_badge(
        "focused-practice",
        "Focused Practice",
        f"Practice for {FOCUSED_PRACTICE_MINUTES} active minutes today.",
        daily.get("effort", {}).get("minutes", 0) >= FOCUSED_PRACTICE_MINUTES,
    )
    add_badge(
        "try-again-champ",
        "Try Again Champ",
        "Miss one, try again, and keep going.",
        daily.get("try_again_win"),
    )
    add_badge(
        "first-signals-mastered",
        "First Signals Mastered",
        "Master the first six signals.",
        overall.get("alphabet_mastered", 0) >= len(starter_practice_letters)
        and overall.get("current_mastery", 0) >= 100,
    )
    add_badge(
        "new-signals-ready",
        "New Signals Ready",
        "Complete the Learn burn-in for new signals.",
        learning_focus.get("active") and learning_focus.get("complete"),
    )
    add_badge(
        "signal-builder",
        "Signal Builder",
        "Master eight letters.",
        overall.get("alphabet_mastered", 0) >= 8,
    )

    if (
        learning_focus.get("active")
        and not learning_focus.get("complete")
        and daily.get("attempt_progress", 0) >= 100
    ):
        next_badge = {
            "label": "New Signals Ready",
            "detail": learning_focus.get("next_need") or "Finish the new-signal Learn work.",
        }
    elif daily.get("effort", {}).get("minutes", 0) < FOCUSED_PRACTICE_MINUTES:
        next_badge = {
            "label": "Focused Practice",
            "detail": f"{max(0, FOCUSED_PRACTICE_MINUTES - daily.get('effort', {}).get('minutes', 0))} active minutes left today.",
        }
    elif not daily.get("try_again_win"):
        next_badge = {
            "label": "Try Again Champ",
            "detail": "Keep going after a miss and get one right.",
        }
    elif not daily.get("completed"):
        next_badge = {
            "label": "Daily Signal Complete",
            "detail": f"{daily.get('remaining', 0)} signals left today.",
        }
    elif daily.get("accuracy", 0) < 90:
        next_badge = {
            "label": "Clean Copy",
            "detail": "Finish a daily mission at 90% accuracy or better.",
        }
    elif learning_focus.get("active") and not learning_focus.get("complete"):
        next_badge = {
            "label": "New Signals Ready",
            "detail": learning_focus.get("next_need") or "Finish the new-signal Learn work.",
        }
    elif overall.get("alphabet_mastered", 0) < 8:
        next_badge = {
            "label": "Signal Builder",
            "detail": "Unlock and master the next signal group.",
        }
    else:
        next_badge = {
            "label": "Keep Current",
            "detail": "Keep today's signals strong and watch for the next group.",
        }

    return {
        "earned": earned,
        "featured": earned[0] if earned else None,
        "next": next_badge,
    }


def daily_learning_focus(learning_letters):
    if not learning_letters:
        return {
            "active": False,
            "goal": 0,
            "correct": 0,
            "remaining": 0,
            "progress": 100,
            "complete": True,
            "next_need": "",
            "letters": []
        }

    items = progress_summary(learning_letters, "learn")
    goal = learn_ready_attempts * len(items)
    correct = sum(min(item["correct"], learn_ready_attempts) for item in items)
    remaining = max(0, goal - correct)
    progress = int(round((correct / goal) * 100)) if goal else 100
    needs = []

    for item in items:
        correct_remaining = max(0, learn_ready_attempts - item["correct"])
        if correct_remaining:
            needs.append(f"{item['letter']} needs {correct_remaining} more correct Learn tries")
            continue

        strength_remaining = max(0, learn_ready_strength - item["strength_percent"])
        if strength_remaining:
            needs.append(f"{item['letter']} needs {strength_remaining} more Learn strength points")

    return {
        "active": True,
        "goal": goal,
        "correct": correct,
        "remaining": remaining,
        "progress": min(100, progress),
        "complete": remaining == 0 and not needs,
        "next_need": needs[0] if needs else "",
        "letters": [
            {
                "letter": item["letter"],
                "correct": min(item["correct"], learn_ready_attempts),
                "goal": learn_ready_attempts,
                "remaining": max(0, learn_ready_attempts - item["correct"]),
                "progress": min(100, int(round((min(item["correct"], learn_ready_attempts) / learn_ready_attempts) * 100))) if learn_ready_attempts else 100
            }
            for item in items
        ]
    }


def mode_display_label(mode):
    return practice_modes.get(mode, {}).get("label", mode.title())


def daily_practice_coach(state):
    if state["learning_letters"]:
        letters = " ".join(state["learning_letters"])
        learning_items = progress_summary(state["learning_letters"], "learn")
        learning_order = {
            letter: index
            for index, letter in enumerate(state["learning_letters"])
        }
        boost_items = sorted(
            [
                {
                    "letter": item["letter"],
                    "strength": item["strength_percent"],
                    "attempts": item["attempts"],
                    "accuracy": item["accuracy"]
                }
                for item in learning_items
            ],
            key=lambda item: (item["strength"], item["attempts"], learning_order.get(item["letter"], 99))
        )

        return {
            "headline": "Practice Next",
            "message": f"Start with Learn for {letters}. New signals stay here until they are ready.",
            "practice_next": [
                {
                    "letter": item["letter"],
                    "mode": "learn",
                    "mode_label": "Learn",
                    "href": "/touch/practice/run?mode=learn",
                    "score": item["strength_percent"],
                    "reason": f"{min(item['correct'], learn_ready_attempts)}/{learn_ready_attempts}"
                }
                for item in learning_items[:3]
            ],
            "strong_label": "Mastered",
            "boost_label": "Learning",
            "strong_signals": strongest_letters(state["active_letters"]),
            "signal_boost": boost_items[:3]
        }

    active_letters = state["active_letters"]
    next_items = weakest_letter_mode_items(active_letters, limit=3)
    strong = strongest_letters(active_letters)
    strong_letters = {item["letter"] for item in strong}
    boost = weakest_letters(active_letters, exclude=strong_letters)

    if next_items:
        first = next_items[0]
        message = f"Try {first['mode_label']} with {first['letter']} next."
    else:
        message = "Start with any active signal. The coach will update after a few tries."

    return {
        "headline": "Practice Coach",
        "message": message,
        "practice_next": next_items,
        "strong_label": "Strong",
        "boost_label": "Boost",
        "strong_signals": strong,
        "signal_boost": boost
    }


def weakest_letter_mode_items(letters, limit=3):
    candidates = []

    for mode in practice_modes:
        for item in progress_summary(letters, mode):
            score = item["strength_percent"]
            attempts = item["attempts"]
            priority = score + min(attempts, 3) * 3

            candidates.append({
                "letter": item["letter"],
                "mode": mode,
                "mode_label": mode_display_label(mode),
                "href": f"/touch/practice/run?mode={mode}",
                "score": score,
                "attempts": attempts,
                "reason": "Start" if attempts == 0 else f"{score}%"
            } | {"priority": priority})

    candidates.sort(key=lambda item: (item["priority"], item["letter"], item["mode"]))

    return [
        {key: value for key, value in item.items() if key != "priority"}
        for item in candidates[:limit]
    ]


def letter_strength_rollup(letters):
    rollup = []

    for letter in letters:
        mode_items = [
            item for mode in practice_modes
            for item in progress_summary([letter], mode)
        ]
        attempts = sum(item["attempts"] for item in mode_items)
        strength = int(round(sum(item["strength_percent"] for item in mode_items) / len(mode_items))) if mode_items else 0
        accuracy_attempts = sum(item["attempts"] for item in mode_items)
        correct = sum(item["correct"] for item in mode_items)
        accuracy = int(round((correct / accuracy_attempts) * 100)) if accuracy_attempts else 0

        rollup.append({
            "letter": letter,
            "strength": strength,
            "attempts": attempts,
            "accuracy": accuracy
        })

    return rollup


def strongest_letters(letters, limit=3):
    practiced = [item for item in letter_strength_rollup(letters) if item["attempts"] > 0]
    practiced.sort(key=lambda item: (-item["strength"], -item["accuracy"], item["letter"]))
    return practiced[:limit]


def weakest_letters(letters, limit=3, exclude=None):
    exclude = set(exclude or [])
    rollup = [item for item in letter_strength_rollup(letters) if item["letter"] not in exclude]
    rollup.sort(key=lambda item: (item["strength"], item["attempts"], item["letter"]))
    return rollup[:limit]


def daily_next_action(state):
    if state["learning_letters"]:
        letters = " ".join(state["learning_letters"])
        status = state.get("learning_status") or {}
        focus = daily_learning_focus(state["learning_letters"])

        if focus["complete"] and status.get("needs"):
            next_need = status.get("next_need", "New signals can join practice after a short break.")
            needs_break = "break" in next_need
            return {
                "label": "Break" if needs_break else "Learn",
                "mode": "",
                "href": "/touch/daily",
                "title": "Take A Break" if needs_break else "Keep Learning",
                "detail": next_need.capitalize()
            }

        return {
            "label": "Learn",
            "mode": "learn",
            "href": "/touch/practice/run?mode=learn",
            "title": f"Learn {letters}",
            "detail": "New signals are waiting. Learn them before they join the other practice modes."
        }

    active_letters = state["active_letters"]
    mode_order = {mode: index for index, mode in enumerate(practice_modes)}
    mode_scores = [
        (mode, mode_score(active_letters, mode))
        for mode in practice_modes
    ]

    weakest_mode, weakest_score = min(
        mode_scores,
        key=lambda item: (item[1]["mastery"], item[1]["accuracy"], mode_order[item[0]])
    )
    mode_label = practice_modes[weakest_mode]["label"]

    if weakest_score["mastery"] < 100:
        return {
            "label": mode_label,
            "mode": weakest_mode,
            "href": f"/touch/practice/run?mode={weakest_mode}",
            "title": f"Practice {mode_label}",
            "detail": f"{mode_label} has the most room to improve today."
        }

    if state["locked_until_tomorrow"]:
        wait_status = state.get("unlock_wait_status") or {}
        return {
            "label": wait_status.get("label", "Next"),
            "mode": "",
            "href": wait_status.get("href", "/touch/daily"),
            "title": wait_status.get("title", "Keep Building"),
            "detail": wait_status.get("detail", "Finish the readiness work to open new signals.")
        }

    next_step = state["next_step"] or get_next_letter_unlock(active_letters)
    if next_step and next_step.get("letters"):
        letters = " ".join(next_step["letters"])
        return {
            "label": "Next",
            "mode": "",
            "href": "/touch/progress",
            "title": f"Next Signals: {letters}",
            "detail": "Keep today's active signals strong to unlock the next group."
        }

    return {
        "label": "Progress",
        "mode": "",
        "href": "/touch/progress",
        "title": "Review Progress",
        "detail": "All planned signals are open. Check progress for the next weak spot."
    }


def word_practice_unlocked(active_letters=None):
    letters = set(active_letters or get_unlocked_practice_letters())
    return all(letter in letters for letter in word_practice_unlock_letters)


def available_word_practice_words(active_letters=None):
    letters = set(active_letters or get_unlocked_practice_letters())

    if not word_practice_unlocked(letters):
        return []

    return [
        word for word in word_practice_bank
        if all(character in letters for character in word)
    ]


def word_practice_summary(active_letters=None):
    words = available_word_practice_words(active_letters)

    return {
        "unlocked": bool(words),
        "count": len(words),
        "unlock_letters": word_practice_unlock_letters,
        "words": words,
    }


def normalize_word_morse(value):
    value = limited_text(value, MAX_MORSE_CHARS)
    cleaned = "".join(character for character in value if character in ".-/ ")
    return " ".join(cleaned.split())


def server_checked_keying_result(target, actual_morse):
    expected_morse = normalize_word_morse(text_to_morse(target))
    actual_morse = normalize_word_morse(actual_morse)
    return expected_morse, actual_morse, bool(actual_morse and actual_morse == expected_morse)


def server_checked_letter_answer(target, answer):
    normalized_target = str(target).strip().upper()
    normalized_answer = str(answer or "").strip().upper()[:1]
    return normalized_answer, bool(normalized_answer and normalized_answer == normalized_target)


def word_practice_item(index=0, active_letters=None):
    words = available_word_practice_words(active_letters)

    if not words:
        return None

    normalized_index = index % len(words)
    word = words[normalized_index]

    return {
        "word": word,
        "morse": text_to_morse(word),
        "index": normalized_index,
        "next_index": (normalized_index + 1) % len(words),
        "total": len(words),
        "letters": [
            {
                "letter": letter,
                "morse": text_to_morse(letter),
            }
            for letter in word
        ],
    }


def load_word_attempts():
    return load_attempt_records("word")


def _unused_load_word_attempts():
    attempts = []
    for line in []:
        try:
            attempts.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return attempts


def word_progress_summary():
    summary = word_practice_summary()
    attempts = load_word_attempts()
    total = len(attempts)
    correct = sum(1 for attempt in attempts if attempt.get("correct"))
    unique_correct = sorted({
        str(attempt.get("word", "")).upper()
        for attempt in attempts
        if attempt.get("correct") and attempt.get("word")
    })
    accuracy = int(round((correct / total) * 100)) if total else 0

    if not summary["unlocked"]:
        return {
            "unlocked": False,
            "accuracy": 0,
            "correct": 0,
            "total": 0,
            "unique_correct": 0,
            "available": 0,
            "label": "Unlock after S O",
            "detail": "Known-letter words",
        }

    return {
        "unlocked": True,
        "accuracy": accuracy,
        "correct": correct,
        "total": total,
        "unique_correct": len(unique_correct),
        "available": summary["count"],
        "label": f"{len(unique_correct)}/{summary['count']} words",
        "detail": f"{correct}/{total} correct" if total else "No word tries yet",
    }


def timestamp_at_or_after(timestamp, started_at):
    if not timestamp:
        return False

    try:
        parsed = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return False

    if parsed.tzinfo and not started_at.tzinfo:
        started_at = started_at.replace(tzinfo=parsed.tzinfo)
    elif started_at.tzinfo and not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=started_at.tzinfo)

    return parsed >= started_at


def correct_word_attempts_since(started_at):
    return sum(
        1 for attempt in load_word_attempts()
        if attempt.get("correct") and timestamp_at_or_after(attempt.get("timestamp"), started_at)
    )


def learning_groups_started_today(state):
    today = today_key()
    return sum(
        1 for group_state in state.get("groups", {}).values()
        if str(group_state.get("first_learning_date", "")) == today
    )


def next_unlock_wait_status(active_letters, state, latest_group_state):
    if latest_group_state is None:
        return None

    if learning_groups_started_today(state) >= max_learning_groups_per_day:
        return {
            "label": "Tomorrow",
            "href": "/touch/daily",
            "title": "Come Back Tomorrow",
            "detail": "Great work. New signals can open tomorrow."
        }

    started_at = group_started_at(latest_group_state)
    rest = learning_rest_status(latest_group_state)
    correct_words = correct_word_attempts_since(started_at) if word_practice_unlocked(active_letters) else word_ready_correct_attempts
    words_remaining = max(0, word_ready_correct_attempts - correct_words)

    if words_remaining or not rest["ready"]:
        parts = []
        if words_remaining:
            parts.append(f"{words_remaining} more correct Word{'s' if words_remaining != 1 else ''}")
        if not rest["ready"]:
            parts.append(f"{rest['remaining_label']} of break time")

        return {
            "label": "Words" if words_remaining else "Break",
            "href": "/touch/words" if words_remaining else "/touch/daily",
            "title": "Practice Words" if words_remaining else "Take A Break",
            "detail": f"{' and '.join(parts)} before new signals can open."
        }

    return None


def step_key(step):
    return "".join(step["letters"])


def load_learning_state():
    loaded = storage.get_document("learning_state") or {}

    return {
        "groups": loaded.get("groups", {}) if isinstance(loaded.get("groups"), dict) else {},
        "last_learning_start_date": str(loaded.get("last_learning_start_date", ""))
    }


def save_learning_state(state):
    storage.set_document("learning_state", state)


def days_since(date_text):
    if not date_text:
        return 0

    try:
        start_date = datetime.fromisoformat(date_text).date()
    except ValueError:
        return 0

    return (datetime.now().date() - start_date).days + 1


def group_started_at(group_state):
    started_at = str(group_state.get("first_learning_started_at", ""))
    learned_since = str(group_state.get("first_learning_date", ""))

    if started_at:
        try:
            return datetime.fromisoformat(started_at)
        except ValueError:
            pass

    if not learned_since:
        return datetime.now()

    try:
        learned_date = datetime.fromisoformat(learned_since).date()
    except ValueError:
        return datetime.now()

    if learned_date == datetime.now().date():
        return datetime.now()

    try:
        return datetime.fromisoformat(f"{learned_date.isoformat()}T00:00:00")
    except ValueError:
        return datetime.now()


def hours_since(started_at):
    now = datetime.now(started_at.tzinfo) if started_at.tzinfo else datetime.now()
    return max(0, (now - started_at).total_seconds() / 3600)


def format_hours_remaining(hours):
    if hours <= 0:
        return "ready now"

    if hours < 1:
        minutes = max(1, int(round(hours * 60)))
        return f"about {minutes} minute{'s' if minutes != 1 else ''}"

    rounded = int(math.ceil(hours))
    return f"about {rounded} hour{'s' if rounded != 1 else ''}"


def learning_rest_status(group_state):
    started_at = group_started_at(group_state)
    elapsed_hours = hours_since(started_at)
    remaining_hours = max(0, learn_ready_rest_hours - elapsed_hours)

    return {
        "started_at": started_at.isoformat(timespec="seconds"),
        "elapsed_hours": elapsed_hours,
        "remaining_hours": remaining_hours,
        "remaining_label": format_hours_remaining(remaining_hours),
        "ready": remaining_hours <= 0,
    }


def learning_step_ready(step, group_state):
    progress = progress_summary(step["letters"], "learn")
    rest = learning_rest_status(group_state)

    practice_ready = all(
        item["correct"] >= learn_ready_attempts and item["strength_percent"] >= learn_ready_strength
        for item in progress
    )

    return practice_ready and rest["ready"]


def get_learning_step_status(step, group_state):
    progress = progress_summary(step["letters"], "learn")
    learned_since = str(group_state.get("first_learning_date", ""))
    days_learning = days_since(learned_since)
    rest = learning_rest_status(group_state)
    needs = []

    for item in progress:
        if item["correct"] < learn_ready_attempts:
            needs.append(f"{item['letter']} needs {learn_ready_attempts - item['correct']} more correct Learn tries")

        if item["strength_percent"] < learn_ready_strength:
            needs.append(f"{item['letter']} needs {learn_ready_strength - item['strength_percent']} more strength points")

    if not rest["ready"]:
        needs.append(f"take a short break; {rest['remaining_label']} left")

    return {
        "letters": step["letters"],
        "learned_since": learned_since,
        "started_at": rest["started_at"],
        "days_learning": days_learning,
        "rest_hours": rest["elapsed_hours"],
        "min_rest_hours": learn_ready_rest_hours,
        "ready": not needs,
        "needs": needs,
        "next_need": needs[0] if needs else "Ready to join practice"
    }


def get_practice_letter_state():
    active = list(starter_practice_letters)
    latest_group_state = None
    learning_step = None
    learning_status = None
    next_step = None
    locked_until_tomorrow = False
    unlock_wait_status = None
    state = load_learning_state()
    today = today_key()
    changed = False

    for index, step in enumerate(letter_unlock_steps):
        key = step_key(step)
        group_state = state["groups"].get(key)

        if group_state:
            if learning_step_ready(step, group_state):
                active.extend(letter for letter in step["letters"] if letter not in active)
                latest_group_state = group_state
                continue

            learning_step = step
            learning_status = get_learning_step_status(step, group_state)
            break

        scores = [mode_score(active, mode) for mode in practice_modes]

        if all(score["mastery"] >= step["threshold"] for score in scores):
            unlock_wait_status = next_unlock_wait_status(active, state, latest_group_state)
            if unlock_wait_status:
                next_step = step
                locked_until_tomorrow = True
                break

            group_state = {
                "letters": step["letters"],
                "first_learning_date": today,
                "first_learning_started_at": datetime.now().isoformat(timespec="seconds")
            }
            state["groups"][key] = group_state
            state["last_learning_start_date"] = today
            learning_step = step
            learning_status = get_learning_step_status(step, group_state)
            changed = True
            break
        else:
            stale_keys = [
                step_key(stale_step)
                for stale_step in letter_unlock_steps[index + 1:]
                if step_key(stale_step) in state["groups"]
            ]
            if stale_keys:
                for stale_key in stale_keys:
                    state["groups"].pop(stale_key, None)
                state["last_learning_start_date"] = ""
                changed = True

            next_step = step
            break

    if changed:
        save_learning_state(state)

    if learning_step is None and next_step is None:
        next_step = get_next_letter_unlock(active)

    learning_letters = learning_step["letters"] if learning_step else []

    return {
        "active_letters": [letter for letter in all_practice_letters if letter in active],
        "learning_letters": [letter for letter in all_practice_letters if letter in learning_letters],
        "learning_step": learning_step,
        "learning_status": learning_status,
        "next_step": next_step,
        "locked_until_tomorrow": locked_until_tomorrow,
        "unlock_wait_status": unlock_wait_status,
        "learn_ready_attempts": learn_ready_attempts,
        "learn_ready_strength": learn_ready_strength,
        "learn_ready_rest_hours": learn_ready_rest_hours,
        "word_ready_correct_attempts": word_ready_correct_attempts,
        "max_learning_groups_per_day": max_learning_groups_per_day
    }


def get_unlocked_practice_letters():
    return get_practice_letter_state()["active_letters"]


def get_practice_letters_for_mode(mode):
    state = get_practice_letter_state()

    if mode == "learn" and state["learning_letters"]:
        return state["learning_letters"]

    return state["active_letters"]


def get_next_letter_unlock(unlocked_letters):
    for step in letter_unlock_steps:
        if any(letter not in unlocked_letters for letter in step["letters"]):
            return step

    return {
        "threshold": None,
        "letters": [],
        "label": "All planned letters unlocked"
    }


def get_learning_overall(letters):
    state = get_practice_letter_state()
    overall = overall_score(state["active_letters"], practice_modes.keys())
    active_alphabet_count = sum(1 for letter in state["active_letters"] if letter in alphabet_letters)
    alphabet_total = len(alphabet_letters)
    alphabet_percent = int(round((active_alphabet_count / alphabet_total) * 100)) if alphabet_total else 100
    mode_masteries = [mode_score(state["active_letters"], mode)["mastery"] for mode in practice_modes]

    overall["current_mastery"] = overall["mastery"]
    overall["current_set_complete"] = bool(mode_masteries) and all(mastery >= 100 for mastery in mode_masteries)
    overall["alphabet_mastered"] = active_alphabet_count
    overall["alphabet_total"] = alphabet_total
    overall["alphabet_percent"] = alphabet_percent
    overall["alphabet_progress"] = f"{active_alphabet_count}/{alphabet_total}"
    overall["unlocked_letters"] = state["active_letters"]
    overall["active_letters"] = state["active_letters"]
    overall["learning_letters"] = state["learning_letters"]
    overall["learn_ready_attempts"] = state["learn_ready_attempts"]
    overall["learn_ready_strength"] = state["learn_ready_strength"]
    overall["learn_ready_rest_hours"] = state["learn_ready_rest_hours"]
    overall["word_ready_correct_attempts"] = state["word_ready_correct_attempts"]
    overall["max_learning_groups_per_day"] = state["max_learning_groups_per_day"]
    overall["learning_step"] = state["learning_step"]
    overall["learning_status"] = state["learning_status"]
    overall["learning_focus"] = daily_learning_focus(state["learning_letters"])
    overall["locked_until_tomorrow"] = state["locked_until_tomorrow"]
    overall["unlock_wait_status"] = state["unlock_wait_status"]
    overall["next_unlock"] = state["learning_step"] or state["next_step"] or get_next_letter_unlock(state["active_letters"])

    if state["learning_step"]:
        status = state["learning_status"] or {}
        overall["next_goal"] = status.get("next_need") or f"Learn {' '.join(state['learning_letters'])} before they join practice"
    elif state["locked_until_tomorrow"]:
        wait_status = state.get("unlock_wait_status") or {}
        overall["next_goal"] = wait_status.get("detail", "Finish the readiness work to open new signals.")
    elif overall["next_unlock"]["letters"]:
        threshold = overall["next_unlock"]["threshold"]
        points_to_unlock = max(0, threshold - min(mode_masteries))
        overall["next_goal"] = f"{points_to_unlock} current-set mastery points to unlock {' '.join(overall['next_unlock']['letters'])}"
    else:
        overall["next_goal"] = overall["next_unlock"]["label"]

    return overall


def get_progress_mode_details():
    state = get_practice_letter_state()
    details = all_mode_details(state["active_letters"], practice_modes.keys())

    for mode, mode_details in details.items():
        mode_details["scope"] = "current_set"
        mode_details["scope_label"] = "Current Set"
        mode_details["summary_label"] = "current set"
        mode_details["letters_label"] = "Current Set Letters"

    if state["learning_letters"]:
        learning_focus = daily_learning_focus(state["learning_letters"])
        learn_score = mode_score(state["learning_letters"], "learn")
        learn_score["mastery"] = learning_focus["progress"]
        learn_score["next_goal"] = learning_focus["next_need"] or learn_score["next_goal"]
        learn_score["completion_label"] = f"{learning_focus['correct']}/{learning_focus['goal']} Learn"

        details["learn"] = {
            "score": learn_score,
            "letters": progress_summary(state["learning_letters"], "learn"),
            "scope": "learning_now",
            "scope_label": "Learning Now",
            "summary_label": f"Learning {' '.join(state['learning_letters'])}",
            "letters_label": "Learning Now Letters"
        }

    return details


def practice_mode_score(letters, mode):
    score = mode_score(letters, mode)

    if mode == "learn":
        state = get_practice_letter_state()
        if state["learning_letters"] and list(letters) == state["learning_letters"]:
            learning_focus = daily_learning_focus(state["learning_letters"])
            score["mastery"] = learning_focus["progress"]
            score["next_goal"] = learning_focus["next_need"] or score["next_goal"]
            score["completion_label"] = f"{learning_focus['correct']}/{learning_focus['goal']} Learn"

    return score


def get_read_choices(target, mode="read"):
    choices = [target]
    practice_letters = get_practice_letters_for_mode(mode)
    others = [letter for letter in practice_letters if letter != target]
    choices.extend(random.sample(others, min(3, len(others))))
    return random.sample(choices, len(choices))


def get_practice_letter_morse():
    state = get_practice_letter_state()
    letters = state["active_letters"] + state["learning_letters"]
    return {letter: text_to_morse(letter) for letter in letters}


def choose_new_practice_target(mode="send"):
    global practice_target, practice_feedback

    practice_letters = get_practice_letters_for_mode(mode)
    practice_target = choose_next_letter(practice_letters, practice_target, mode)
    practice_feedback = ""


