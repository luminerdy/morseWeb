import random
from datetime import datetime, timezone

import storage


DEFAULT_MODE = "send"

RANKS = [
    "First Signal",
    "Signal Scout",
    "Code Cadet",
    "Junior Operator",
    "Station Helper",
    "Clear Copy",
    "Relay Ready",
    "Telegraph Pro"
]


LETTER_UNLOCKS = [
    {"level": 1, "letters": ["E", "T"], "label": "First Signals"},
    {"level": 2, "letters": ["A", "N"], "label": "First Pair"},
    {"level": 3, "letters": ["I", "M"], "label": "Short Copy"},
    {"level": 4, "letters": ["S", "O"], "label": "Signal Builder"},
    {"level": 5, "letters": ["R", "K"], "label": "Rhythm Builder"},
    {"level": 6, "letters": ["D", "U"], "label": "Relay Builder"}
]


def empty_record():
    return {
        "attempts": 0,
        "correct": 0,
        "streak": 0,
        "strength": 0.0,
        "last_seen": ""
    }


def load_progress(letters):
    progress = load_all_progress()

    for letter in letters:
        progress[letter] = normalize_letter_progress(progress.get(letter, {}))

    return {letter: progress[letter] for letter in letters}


def load_all_progress():
    progress = storage.get_document("practice_progress", {})
    if not isinstance(progress, dict):
        progress = {}

    return {
        letter: normalize_letter_progress(value)
        for letter, value in progress.items()
    }


def load_progress_for_update(letters):
    progress = load_all_progress()

    for letter in letters:
        progress[letter] = normalize_letter_progress(progress.get(letter, {}))

    return progress


def save_progress(progress):
    storage.set_document("practice_progress", progress)


def normalize_record(record):
    attempts = max(0, int(record.get("attempts", 0)))
    correct = max(0, min(int(record.get("correct", 0)), attempts))
    streak = max(0, int(record.get("streak", 0)))
    strength = max(0.0, min(float(record.get("strength", 0.0)), 1.0))

    return {
        "attempts": attempts,
        "correct": correct,
        "streak": streak,
        "strength": strength,
        "last_seen": str(record.get("last_seen", ""))
    }


def normalize_letter_progress(value):
    if not isinstance(value, dict):
        value = {}

    if "attempts" in value or "correct" in value or "strength" in value:
        return {DEFAULT_MODE: normalize_record(value)}

    modes = {}

    for mode, record in value.items():
        if isinstance(record, dict):
            modes[mode] = normalize_record(record)

    if DEFAULT_MODE not in modes:
        modes[DEFAULT_MODE] = empty_record()

    return modes


def get_record(progress, letter, mode):
    letter_progress = progress.get(letter, {})
    record = letter_progress.get(mode)

    if record is None:
        record = empty_record()
        letter_progress[mode] = record
        progress[letter] = letter_progress

    return record


def record_attempt(letter, is_correct, letters, mode=DEFAULT_MODE):
    progress = load_progress_for_update(letters)
    record = get_record(progress, letter, mode)

    record["attempts"] += 1
    record["last_seen"] = datetime.now(timezone.utc).isoformat()

    if is_correct:
        record["correct"] += 1
        record["streak"] += 1
        record["strength"] = min(1.0, record["strength"] + 0.18 + min(record["streak"], 4) * 0.02)
    else:
        record["streak"] = 0
        record["strength"] = max(0.0, record["strength"] - 0.35)

    progress[letter][mode] = normalize_record(record)
    save_progress(progress)
    return progress


def choose_next_letter(letters, current_letter="", mode=DEFAULT_MODE):
    progress = load_progress(letters)
    candidates = [letter for letter in letters if letter != current_letter] or list(letters)
    weights = []

    for letter in candidates:
        record = get_record(progress, letter, mode)
        strength = record["strength"]
        attempts = record["attempts"]
        streak = record["streak"]

        weight = 0.35 + (1.0 - strength) * 2.0

        if attempts == 0:
            weight += 1.2

        if attempts > 0 and streak == 0:
            weight += 0.7

        if streak >= 3:
            weight *= 0.55

        weights.append(max(weight, 0.1))

    return random.choices(candidates, weights=weights, k=1)[0]


def progress_summary(letters, mode=DEFAULT_MODE):
    progress = load_progress(letters)
    summary = []

    for letter in letters:
        record = get_record(progress, letter, mode)
        attempts = record["attempts"]
        accuracy = int(round((record["correct"] / attempts) * 100)) if attempts else 0

        summary.append({
            "letter": letter,
            "attempts": attempts,
            "correct": record["correct"],
            "streak": record["streak"],
            "strength": round(record["strength"], 2),
            "strength_percent": int(round(record["strength"] * 100)),
            "accuracy": accuracy
        })

    return summary


def mode_score(letters, mode=DEFAULT_MODE):
    summary = progress_summary(letters, mode)
    total_attempts = sum(item["attempts"] for item in summary)
    total_correct = sum(item["correct"] for item in summary)
    mastery = int(round(sum(item["strength_percent"] for item in summary) / len(summary))) if summary else 0
    best_streak = max((item["streak"] for item in summary), default=0)
    accuracy = int(round((total_correct / total_attempts) * 100)) if total_attempts else 0
    level = min(5, mastery // 20 + 1)
    next_level_mastery = min(level * 20, 100)
    points_to_next = max(0, next_level_mastery - mastery)

    if mastery >= 80:
        title = "Sharp Copy"
    elif mastery >= 60:
        title = "Getting Strong"
    elif mastery >= 40:
        title = "Finding Rhythm"
    elif mastery >= 20:
        title = "Warming Up"
    else:
        title = "First Signals"

    if mastery == 100:
        next_goal = "Level complete"
    elif level >= 5:
        next_goal = f"{points_to_next} mastery {'point' if points_to_next == 1 else 'points'} to complete"
    else:
        next_goal = f"{points_to_next} mastery {'point' if points_to_next == 1 else 'points'} to Level {min(level + 1, 5)}"

    return {
        "mode": mode,
        "level": level,
        "title": title,
        "mastery": mastery,
        "accuracy": accuracy,
        "streak": best_streak,
        "attempts": total_attempts,
        "next_goal": next_goal
    }


def all_mode_details(letters, modes):
    return {
        mode: {
            "score": mode_score(letters, mode),
            "letters": progress_summary(letters, mode)
        }
        for mode in modes
    }


def overall_score(letters, modes):
    progress = load_progress(letters)
    records = []

    for letter in letters:
        for mode in modes:
            records.append(get_record(progress, letter, mode))

    total_attempts = sum(record["attempts"] for record in records)
    total_correct = sum(record["correct"] for record in records)
    mastery = int(round((sum(record["strength"] for record in records) / len(records)) * 100)) if records else 0
    accuracy = int(round((total_correct / total_attempts) * 100)) if total_attempts else 0
    best_streak = max((record["streak"] for record in records), default=0)
    level = min(len(RANKS), mastery // 13 + 1)
    next_level_mastery = min(level * 13, 100)
    points_to_next = max(0, next_level_mastery - mastery)
    unlocked_letters = unlocked_letters_for_level(level)
    next_unlock = next_unlock_for_level(level)

    if mastery == 100:
        next_goal = "Top rank reached"
    else:
        next_goal = f"{points_to_next} mastery {'point' if points_to_next == 1 else 'points'} to Level {min(level + 1, len(RANKS))}"

    return {
        "level": level,
        "rank": RANKS[level - 1],
        "mastery": mastery,
        "accuracy": accuracy,
        "streak": best_streak,
        "attempts": total_attempts,
        "unlocked_letters": [letter for letter in unlocked_letters if letter in letters],
        "next_unlock": next_unlock,
        "next_goal": next_goal
    }


def unlocked_letters_for_level(level):
    unlocked = []

    for unlock in LETTER_UNLOCKS:
        if unlock["level"] <= level:
            unlocked.extend(unlock["letters"])

    return unlocked


def next_unlock_for_level(level):
    for unlock in LETTER_UNLOCKS:
        if unlock["level"] > level:
            return {
                "level": unlock["level"],
                "letters": unlock["letters"],
                "label": unlock["label"]
            }

    return {
        "level": None,
        "letters": [],
        "label": "All planned letters unlocked"
    }
