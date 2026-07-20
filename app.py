"""morseWeb - web-based Morse code learning app.

Derived from morsePi (https://github.com/luminerdy/morsePi). The
spacebar is the keyer: the browser captures key timing, plays audio,
and posts results here. No GPIO, LEDs, or station hardware.

Phase 2: real accounts (admin/parent/student), parent-managed child
accounts, per-user data isolation, CSRF + rate limiting. Run locally:

    python3 app.py

then open http://localhost:5000. Environment:

    MORSEWEB_SECRET_KEY     session/token signing key (required in prod)
    MORSEWEB_SECURE_COOKIES set to 1 behind HTTPS
    MORSEWEB_BEHIND_PROXY   set to 1 when nginx fronts gunicorn
    MORSEWEB_EMAIL_BACKEND  "ses" in prod (see emailer.py)

In production this module is served by gunicorn (see deploy/).
"""

import os

from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_login import current_user, login_required

import learning
import storage
from extensions import csrf, limiter, login_manager
from learning import (
    available_word_practice_words,
    bonus_sprint_summary,
    choose_bonus_sprint_target,
    choose_new_practice_target,
    default_morse_timing_settings,
    effort_summary,
    get_learning_overall,
    get_morse_timing,
    get_practice_feedback,
    get_practice_letter_morse,
    get_practice_letters_for_mode,
    get_practice_target,
    get_practice_timing,
    get_progress_mode_details,
    get_read_choices,
    get_unlocked_practice_letters,
    limited_text,
    load_all_effort_attempts,
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
app.config["SECRET_KEY"] = os.environ.get("MORSEWEB_SECRET_KEY", "dev-only-not-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("MORSEWEB_SECURE_COOKIES") == "1"

if os.environ.get("MORSEWEB_BEHIND_PROXY") == "1":
    # Trust nginx's X-Forwarded-* so url_for(_external=True) builds the
    # real https links that go into verification/reset emails.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

csrf.init_app(app)
limiter.init_app(app)
login_manager.init_app(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in first."

import admin as admin_module
import auth as auth_module
import family as family_module

app.register_blueprint(auth_module.bp)
app.register_blueprint(family_module.bp)
app.register_blueprint(admin_module.bp)

MAX_MESSAGE_CHARS = 160
MAX_ANSWER_CHARS = 20
MAX_WORD_CHARS = 20


@app.before_request
def scope_storage_to_current_user():
    """Every document/attempt query in this request belongs to the
    logged-in user; no cross-request state."""
    if current_user.is_authenticated:
        storage.set_current_user(current_user.id)
    else:
        storage.clear_current_user()


def get_practice_mode():
    mode = request.values.get("mode", "send")

    if request.is_json:
        data = request.get_json(silent=True) or {}
        mode = data.get("mode", mode)

    return mode if mode in practice_modes else "send"


def attempt_metadata():
    return {"student_id": current_user.slug}


def safe_next_url(default_endpoint="practice", **default_values):
    next_url = request.form.get("next") or request.args.get("next") or ""

    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url

    return url_for(default_endpoint, **default_values)


def render_practice_template(template_name):
    mode = get_practice_mode()
    practice_letters = get_practice_letters_for_mode(mode)
    overall = get_learning_overall(practice_letters)

    if get_practice_target() not in practice_letters:
        choose_new_practice_target(mode)

    target = get_practice_target()
    expected_morse = text_to_morse(target)
    feedback = get_practice_feedback()

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
    target = get_practice_target()

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


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/healthz")
def healthz():
    """Deploy and uptime checks: confirms the app and database answer."""
    try:
        storage.get_user_by_slug(storage.DEFAULT_USER_SLUG)
    except Exception:
        return jsonify({"status": "database-error"}), 500
    return jsonify({"status": "ok"})


@app.route("/", methods=["GET", "POST"])
def index():
    message = ""
    if request.method == "POST":
        message = limited_text(request.form.get("message", ""), MAX_MESSAGE_CHARS)

    if current_user.is_authenticated:
        timing = get_morse_timing()
    else:
        timing = get_morse_timing(default_morse_timing_settings())

    return render_template(
        "index.html",
        message=message,
        morse=text_to_morse(message),
        timing=timing,
    )


@app.route("/timing-settings", methods=["POST"])
@login_required
def timing_settings():
    save_morse_timing_settings({
        "character_wpm": request.form.get("character_wpm"),
        "effective_wpm": request.form.get("effective_wpm"),
        "tone_hz": request.form.get("tone_hz"),
    })
    return redirect(safe_next_url("index"))


@app.route("/practice")
@login_required
def practice():
    return render_practice_template("practice.html")


@app.route("/practice/new", methods=["POST"])
@login_required
def practice_new():
    mode = get_practice_mode()
    choose_new_practice_target(mode)
    return redirect(safe_next_url("practice", mode=mode))


@app.route("/practice/next", methods=["POST"])
@login_required
def practice_next():
    mode = get_practice_mode()
    choose_new_practice_target(mode)
    return jsonify(practice_prompt_payload(mode))


@app.route("/practice/retry", methods=["POST"])
@login_required
def practice_retry():
    mode = get_practice_mode()
    practice_letters = get_practice_letters_for_mode(mode)

    if get_practice_target() not in practice_letters:
        choose_new_practice_target(mode)

    return jsonify(practice_prompt_payload(mode))


@app.route("/practice/result", methods=["POST"])
@login_required
def practice_result():
    data = request.get_json(silent=True) or {}
    letter = limited_text(data.get("target", get_practice_target()), 1).upper()
    mode = str(data.get("mode", "send"))
    answer = limited_text(data.get("answer", ""), MAX_ANSWER_CHARS)
    actual_morse = str(data.get("actual_morse", "") or "").strip()
    timing_events = data.get("timing_events") or []

    if mode not in practice_modes:
        mode = "send"

    expected_morse = learning.normalize_word_morse(text_to_morse(letter))

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
@login_required
def words_result():
    data = request.get_json(silent=True) or {}
    word = limited_text(data.get("word", ""), MAX_WORD_CHARS).upper()
    actual_morse = learning.normalize_word_morse(str(data.get("actual_morse", "") or ""))
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
@login_required
def bonus_next():
    target = choose_bonus_sprint_target()

    return jsonify({
        "target": target,
        "expected_morse": text_to_morse(target),
        "timing": get_practice_timing("send", target),
    })


@app.route("/bonus/result", methods=["POST"])
@login_required
def bonus_result():
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "")).strip()
    letter = limited_text(data.get("target", get_practice_target()), 1).upper()
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
@login_required
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
