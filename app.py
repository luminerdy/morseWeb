"""morseWeb - web-based Morse code learning app.

Derived from morsePi (https://github.com/luminerdy/morsePi). The
spacebar is the keyer: the browser captures key timing, plays audio,
and posts results here. No GPIO, LEDs, or station hardware.

Phase 1: single-user, SQLite storage. Run locally:

    python3 app.py

then open http://localhost:5000
"""

from flask import Flask, jsonify, redirect, render_template, request, url_for

import learning
import storage
from learning import (
    available_word_practice_words,
    bonus_sprint_summary,
    choose_bonus_sprint_target,
    choose_new_practice_target,
    effort_summary,
    get_learning_overall,
    get_morse_timing,
    get_practice_letter_morse,
    get_practice_letters_for_mode,
    get_practice_timing,
    get_progress_mode_details,
    get_read_choices,
    get_unlocked_practice_letters,
    limited_text,
    load_all_effort_attempts,
    normalize_morse_timing,
    normalize_word_morse,
    practice_mode_score,
    practice_modes,
    progress_summary,
    save_morse_timing_settings,
    server_checked_keying_result,
    server_checked_letter_answer,
    word_practice_summary,
)
from learning import append_bonus_attempt, append_word_attempt
from morse import morse_to_text, text_to_morse
from practice_attempts import append_practice_attempt
from practice_progress import record_attempt

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

MAX_MESSAGE_CHARS = 160
MAX_ANSWER_CHARS = 20
MAX_WORD_CHARS = 20

last_message = ""
last_morse = ""


def get_practice_mode():
    mode = request.values.get("mode", "send")

    if request.is_json:
        data = request.get_json(silent=True) or {}
        mode = data.get("mode", mode)

    return mode if mode in practice_modes else "send"


def attempt_metadata():
    return {"student_id": storage.DEFAULT_USER_SLUG}


def safe_next_url(default_endpoint="practice", **default_values):
    next_url = request.form.get("next") or request.args.get("next") or ""

    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url

    return url_for(default_endpoint, **default_values)


def render_practice_template(template_name):
    mode = get_practice_mode()
    practice_letters = get_practice_letters_for_mode(mode)
    overall = get_learning_overall(practice_letters)

    if learning.practice_target not in practice_letters:
        choose_new_practice_target(mode)

    target = learning.practice_target
    expected_morse = text_to_morse(target)
    feedback = learning.practice_feedback

    if not feedback and overall["learning_letters"]:
        letters = " ".join(overall["learning_letters"])
        if mode == "learn":
            feedback = f"New letters unlocked: {letters}. Learn them here first."
        else:
            feedback = (
                f"New letters unlocked: {letters}. Use Learn mode first; "
                "they are not in this practice mode yet."
            )

    return render_template(
        template_name,
        mode=mode,
        modes=practice_modes,
        target=target,
        expected_morse=expected_morse,
        read_choices=get_read_choices(target, mode),
        feedback=feedback,
        progress=progress_summary(practice_letters, mode),
        score=practice_mode_score(practice_letters, mode),
        overall=overall,
        word_practice=word_practice_summary(overall["active_letters"]),
        letter_morse=get_practice_letter_morse(),
        progress_label=practice_modes[mode]["progress_label"],
        timing=get_practice_timing(mode, target),
    )


def practice_prompt_payload(mode):
    practice_letters = get_practice_letters_for_mode(mode)
    target = learning.practice_target

    return {
        "mode": mode,
        "target": target,
        "expected_morse": text_to_morse(target),
        "read_choices": get_read_choices(target, mode),
        "timing": get_practice_timing(mode, target),
        "progress": progress_summary(practice_letters, mode),
        "score": practice_mode_score(practice_letters, mode),
        "overall": get_learning_overall(practice_letters),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    global last_message, last_morse

    if request.method == "POST":
        last_message = limited_text(request.form.get("message", ""), MAX_MESSAGE_CHARS)
        last_morse = text_to_morse(last_message)

    return render_template(
        "index.html",
        message=last_message,
        morse=last_morse,
        timing=get_morse_timing(),
    )


@app.route("/timing-settings", methods=["POST"])
def timing_settings():
    save_morse_timing_settings({
        "character_wpm": request.form.get("character_wpm"),
        "effective_wpm": request.form.get("effective_wpm"),
        "tone_hz": request.form.get("tone_hz"),
    })
    return redirect(safe_next_url("index"))


@app.route("/practice")
def practice():
    return render_practice_template("practice.html")


@app.route("/practice/new", methods=["POST"])
def practice_new():
    mode = get_practice_mode()
    choose_new_practice_target(mode)
    return redirect(safe_next_url("practice", mode=mode))


@app.route("/practice/next", methods=["POST"])
def practice_next():
    mode = get_practice_mode()
    choose_new_practice_target(mode)
    return jsonify(practice_prompt_payload(mode))


@app.route("/practice/retry", methods=["POST"])
def practice_retry():
    mode = get_practice_mode()
    practice_letters = get_practice_letters_for_mode(mode)

    if learning.practice_target not in practice_letters:
        choose_new_practice_target(mode)

    return jsonify(practice_prompt_payload(mode))


@app.route("/practice/result", methods=["POST"])
def practice_result():
    data = request.get_json(silent=True) or {}
    letter = limited_text(data.get("target", learning.practice_target), 1).upper()
    mode = str(data.get("mode", "send"))
    answer = limited_text(data.get("answer", ""), MAX_ANSWER_CHARS)
    actual_morse = str(data.get("actual_morse", "") or "").strip()
    timing_events = data.get("timing_events") or []

    if mode not in practice_modes:
        mode = "send"

    expected_morse = normalize_word_morse(text_to_morse(letter))

    if mode in ("read", "listen"):
        answer, is_correct = server_checked_letter_answer(letter, answer)
        actual_morse = ""
    else:
        expected_morse, actual_morse, is_correct = server_checked_keying_result(letter, actual_morse)

    practice_letters = get_practice_letters_for_mode(mode)

    if letter not in practice_letters:
        return jsonify({
            "status": "ignored",
            "timing": get_practice_timing(mode, letter),
            "progress": progress_summary(practice_letters, mode),
            "score": practice_mode_score(practice_letters, mode),
            "overall": get_learning_overall(practice_letters),
        })

    record_attempt(letter, is_correct, practice_letters, mode)
    attempt_record = append_practice_attempt({
        "mode": mode,
        **attempt_metadata(),
        "target": letter,
        "expected_morse": expected_morse,
        "actual_morse": actual_morse,
        "answer": answer,
        "correct": is_correct,
        "timing": get_practice_timing(mode, letter),
        "timing_events": timing_events,
    })

    return jsonify({
        "status": "recorded",
        "attempt": attempt_record,
        "timing": get_practice_timing(mode, letter),
        "progress": progress_summary(practice_letters, mode),
        "score": practice_mode_score(practice_letters, mode),
        "overall": get_learning_overall(practice_letters),
    })


@app.route("/words/result", methods=["POST"])
def words_result():
    data = request.get_json(silent=True) or {}
    word = limited_text(data.get("word", ""), MAX_WORD_CHARS).upper()
    actual_morse = normalize_word_morse(str(data.get("actual_morse", "") or ""))
    expected_morse, actual_morse, is_correct = server_checked_keying_result(word, actual_morse)
    decoded = morse_to_text(actual_morse).upper() if actual_morse else ""
    elapsed_ms = data.get("elapsed_ms")

    try:
        elapsed_ms = max(0, int(round(float(elapsed_ms)))) if elapsed_ms is not None else None
    except (TypeError, ValueError):
        elapsed_ms = None

    if not word or word not in available_word_practice_words():
        return jsonify({"status": "ignored"}), 400

    attempt_record = append_word_attempt({
        "kind": "word-practice",
        **attempt_metadata(),
        "word": word,
        "expected_morse": expected_morse,
        "actual_morse": actual_morse,
        "decoded": decoded,
        "correct": is_correct,
        "elapsed_ms": elapsed_ms,
        "timing": get_morse_timing(),
        "timing_events": data.get("timing_events") or [],
    })

    return jsonify({
        "status": "recorded",
        "attempt": attempt_record,
    })


@app.route("/bonus/next", methods=["POST"])
def bonus_next():
    target = choose_bonus_sprint_target()

    return jsonify({
        "target": target,
        "expected_morse": text_to_morse(target),
        "timing": get_practice_timing("send", target),
    })


@app.route("/bonus/result", methods=["POST"])
def bonus_result():
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "")).strip()
    letter = limited_text(data.get("target", learning.practice_target), 1).upper()
    expected_morse, actual_morse, is_correct = server_checked_keying_result(
        letter,
        str(data.get("actual_morse", "") or "").strip(),
    )
    timing_events = data.get("timing_events") or []

    if not session_id:
        return jsonify({"status": "missing-session"}), 400

    if letter not in get_unlocked_practice_letters():
        return jsonify({
            "status": "ignored",
            "bonus": bonus_sprint_summary(session_id),
        })

    attempt_record = append_bonus_attempt({
        "kind": "signal-sprint",
        **attempt_metadata(),
        "session_id": session_id,
        "target": letter,
        "expected_morse": expected_morse,
        "actual_morse": actual_morse,
        "correct": is_correct,
        "timing": get_practice_timing("send", letter),
        "timing_events": timing_events,
    })

    return jsonify({
        "status": "recorded",
        "attempt": attempt_record,
        "timing": get_practice_timing("send", letter),
        "bonus": bonus_sprint_summary(session_id),
    })


@app.route("/progress")
def progress():
    mode = get_practice_mode()
    practice_letters = get_unlocked_practice_letters()
    effort = effort_summary(load_all_effort_attempts())

    return render_template(
        "progress.html",
        mode=mode,
        modes=practice_modes,
        overall=get_learning_overall(practice_letters),
        details=get_progress_mode_details(),
        effort=effort,
        letter_morse=get_practice_letter_morse(),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
