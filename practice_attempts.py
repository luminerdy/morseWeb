import json
from datetime import datetime, timezone
from pathlib import Path


ATTEMPTS_PATH = Path("data/practice_attempts.jsonl")
MAX_TIMING_EVENTS = 240


def set_attempts_path(path):
    global ATTEMPTS_PATH
    ATTEMPTS_PATH = Path(path)


def rounded_ms(seconds):
    return int(round(seconds * 1000))


def average_duration(items):
    if not items:
        return None
    return int(round(sum(item.get("duration_ms", 0) for item in items) / len(items)))


def min_duration(items):
    if not items:
        return None
    return min(item.get("duration_ms", 0) for item in items)


def max_duration(items):
    if not items:
        return None
    return max(item.get("duration_ms", 0) for item in items)


def consistency_score(items):
    if len(items) < 2:
        return None

    durations = [item.get("duration_ms", 0) for item in items]
    average = sum(durations) / len(durations)
    if average <= 0:
        return None

    variance = sum((duration - average) ** 2 for duration in durations) / len(durations)
    coefficient = (variance ** 0.5) / average
    return max(0, min(100, int(round(100 - coefficient * 100))))


def ratio_score(actual, target):
    if actual is None or target <= 0:
        return None

    return max(0, min(100, int(round(100 - (abs(actual - target) / target) * 100))))


def average_score(values):
    scores = [value for value in values if value is not None]
    if not scores:
        return None

    return int(round(sum(scores) / len(scores)))


def rhythm_feedback(summary):
    if summary.get("symbol_count", 0) == 0:
        return ""

    spacing_score = summary.get("spacing_score")
    dash_ratio_score = summary.get("dash_ratio_score")
    dot_consistency = summary.get("dot_consistency")
    dash_consistency = summary.get("dash_consistency")

    if spacing_score is not None and spacing_score < 70:
        return "Add a little more space between letters."
    if dash_ratio_score is not None and dash_ratio_score < 70:
        return "Stretch dashes closer to three dot lengths."
    if dot_consistency is not None and dot_consistency < 70:
        return "Keep dots more even."
    if dash_consistency is not None and dash_consistency < 70:
        return "Keep dashes more even."
    if summary.get("overall_rhythm_score") is not None and summary["overall_rhythm_score"] >= 85:
        return "Rhythm is steady."

    return "Good practice data captured."


def timing_summary(events):
    symbols = [event for event in events if event.get("type") == "symbol"]
    gaps = [event for event in events if event.get("type") == "gap"]
    dots = [event for event in symbols if event.get("symbol") == "."]
    dashes = [event for event in symbols if event.get("symbol") == "-"]
    symbol_gaps = [event for event in gaps if event.get("gap_type", "symbol") == "symbol"]
    letter_gaps = [event for event in gaps if event.get("gap_type") == "letter"]
    word_gaps = [event for event in gaps if event.get("gap_type") == "word"]

    avg_dot_ms = average_duration(dots)
    avg_dash_ms = average_duration(dashes)
    avg_symbol_gap_ms = average_duration(symbol_gaps)
    avg_letter_gap_ms = average_duration(letter_gaps)
    dash_to_dot_ratio = round(avg_dash_ms / avg_dot_ms, 2) if avg_dot_ms and avg_dash_ms else None
    symbol_to_dot_ratio = round(avg_symbol_gap_ms / avg_dot_ms, 2) if avg_dot_ms and avg_symbol_gap_ms else None
    letter_to_symbol_ratio = round(avg_letter_gap_ms / avg_symbol_gap_ms, 2) if avg_symbol_gap_ms and avg_letter_gap_ms else None
    dash_ratio_score = ratio_score(dash_to_dot_ratio, 3)
    symbol_gap_score = ratio_score(symbol_to_dot_ratio, 1)
    spacing_score = ratio_score(letter_to_symbol_ratio, 3)
    dot_consistency = consistency_score(dots)
    dash_consistency = consistency_score(dashes)
    overall_rhythm_score = average_score([
        dot_consistency,
        dash_consistency,
        dash_ratio_score,
        symbol_gap_score,
        spacing_score,
    ])

    summary = {
        "dot_count": len(dots),
        "dash_count": len(dashes),
        "symbol_count": len(symbols),
        "gap_count": len(gaps),
        "symbol_gap_count": len(symbol_gaps),
        "letter_gap_count": len(letter_gaps),
        "word_gap_count": len(word_gaps),
        "avg_dot_ms": avg_dot_ms,
        "avg_dash_ms": avg_dash_ms,
        "avg_gap_ms": average_duration(gaps),
        "avg_symbol_gap_ms": avg_symbol_gap_ms,
        "avg_letter_gap_ms": avg_letter_gap_ms,
        "avg_word_gap_ms": average_duration(word_gaps),
        "min_letter_gap_ms": min_duration(letter_gaps),
        "max_letter_gap_ms": max_duration(letter_gaps),
        "dot_consistency": dot_consistency,
        "dash_consistency": dash_consistency,
        "dash_to_dot_ratio": dash_to_dot_ratio,
        "letter_to_symbol_gap_ratio": letter_to_symbol_ratio,
        "dash_ratio_score": dash_ratio_score,
        "symbol_gap_score": symbol_gap_score,
        "spacing_score": spacing_score,
        "overall_rhythm_score": overall_rhythm_score,
    }
    summary["primary_rhythm_feedback"] = rhythm_feedback(summary)

    return summary


def normalize_timing_events(events):
    normalized = []

    if not isinstance(events, list):
        return normalized

    for event in events[:MAX_TIMING_EVENTS]:
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")

        if event_type == "symbol":
            normalized.append({
                "type": "symbol",
                "symbol": event.get("symbol", ""),
                "duration_ms": max(0, int(round(float(event.get("duration_ms", 0)))))
            })
        elif event_type == "gap":
            normalized.append({
                "type": "gap",
                "gap_type": event.get("gap_type", "symbol"),
                "duration_ms": max(0, int(round(float(event.get("duration_ms", 0)))))
            })

    return normalized


def append_practice_attempt(record):
    ATTEMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    normalized = dict(record)
    normalized["timestamp"] = datetime.now(timezone.utc).isoformat()
    normalized["timing_events"] = normalize_timing_events(normalized.get("timing_events", []))
    normalized["timing_summary"] = timing_summary(normalized["timing_events"])

    with ATTEMPTS_PATH.open("a", encoding="utf-8") as attempts_file:
        attempts_file.write(json.dumps(normalized, sort_keys=True) + "\n")

    return normalized
