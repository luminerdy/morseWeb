"""Accounts and authentication for morseWeb.

Adults sign up with an email and become parents (the admin role is
granted with scripts/make_admin.py). Students are created by a parent
in the Family page and log in with a username - no child email, per the
COPPA design in the project plan. Email verification and password reset
use signed, expiring tokens; links are emailed (console-printed in dev).
"""

import re
import sqlite3
from functools import wraps

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template,
    request, url_for,
)
from flask_login import UserMixin, current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import emailer
import storage
from extensions import limiter, login_manager

bp = Blueprint("auth", __name__)

VERIFY_SALT = "morseweb-email-verify"
RESET_SALT = "morseweb-password-reset"
VERIFY_MAX_AGE_SECONDS = 60 * 60 * 24 * 3
RESET_MAX_AGE_SECONDS = 60 * 60 * 2
ADULT_PASSWORD_MIN = 8
CHILD_PASSWORD_MIN = 4
MAX_NAME_CHARS = 60


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.slug = row["slug"]
        self.name = row["name"]
        self.email = row["email"]
        self.role = row["role"]
        self.parent_id = row["parent_id"]
        self.email_verified = bool(row["email_verified"])
        self._active = bool(row["is_active"])

    @property
    def is_active(self):
        return self._active

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    try:
        row = storage.get_user(int(user_id))
    except (TypeError, ValueError):
        return None
    if row is None or not row["is_active"]:
        return None
    return User(row)


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _serializer(salt):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def _load_token(token, salt, max_age):
    try:
        return _serializer(salt).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def send_verification_email(user):
    token = _serializer(VERIFY_SALT).dumps(user["email"])
    link = url_for("auth.verify_email", token=token, _external=True)
    emailer.send_email(
        user["email"],
        "Verify your morseWeb email",
        f"Hi {user['name']},\n\nConfirm your email to activate your "
        f"morseWeb account:\n\n{link}\n\nThe link expires in 3 days.",
    )


def send_reset_email(user):
    token = _serializer(RESET_SALT).dumps(user["email"])
    link = url_for("auth.reset_password", token=token, _external=True)
    emailer.send_email(
        user["email"],
        "Reset your morseWeb password",
        f"Hi {user['name']},\n\nReset your morseWeb password here:"
        f"\n\n{link}\n\nThe link expires in 2 hours. If you did not ask "
        "for this, you can ignore it.",
    )


def normalize_email(value):
    return str(value or "").strip().lower()


def valid_email(value):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def normalize_username(value):
    return re.sub(r"[^a-z0-9-]", "", str(value or "").strip().lower())


def unique_slug(base):
    base = normalize_username(base) or "user"
    slug = base
    suffix = 2
    while storage.get_user_by_slug(slug) is not None:
        slug = f"{base}{suffix}"
        suffix += 1
    return slug


@bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    name = str(request.form.get("name", "")).strip()[:MAX_NAME_CHARS]
    email = normalize_email(request.form.get("email"))
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    error = None
    if not name:
        error = "Please enter your name."
    elif not valid_email(email):
        error = "Please enter a valid email address."
    elif len(password) < ADULT_PASSWORD_MIN:
        error = f"Password must be at least {ADULT_PASSWORD_MIN} characters."
    elif password != confirm:
        error = "Passwords do not match."

    if error:
        flash(error, "error")
        return render_template("signup.html", name=name, email=email), 400

    try:
        user_id = storage.create_user(
            slug=unique_slug(email.split("@")[0]),
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            role="parent",
        )
    except sqlite3.IntegrityError:
        # Do not reveal whether an email is registered.
        flash("If that email is new here, your account was created. Check your email.", "info")
        return redirect(url_for("auth.login"))

    try:
        send_verification_email(storage.get_user(user_id))
    except Exception:
        # The account exists; a broken mail backend must not 500 the flow.
        current_app.logger.exception("verification email failed")
        flash(
            "Account created, but the verification email could not be sent. "
            "Use 'Resend verification email' on the login page in a few minutes.",
            "error",
        )
        return redirect(url_for("auth.login"))

    flash("Account created. Check your email for a verification link.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/verify/<token>")
def verify_email(token):
    email = _load_token(token, VERIFY_SALT, VERIFY_MAX_AGE_SECONDS)
    user = storage.get_user_by_email(email) if email else None
    if user is None:
        flash("That verification link is invalid or expired.", "error")
        return redirect(url_for("auth.login"))

    if not user["email_verified"]:
        storage.update_user(user["id"], email_verified=1)
    flash("Email verified. You can log in now.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/verify/resend", methods=["POST"])
@limiter.limit("5 per hour")
def resend_verification():
    email = normalize_email(request.form.get("email"))
    user = storage.get_user_by_email(email) if valid_email(email) else None
    if user is not None and not user["email_verified"]:
        try:
            send_verification_email(user)
        except Exception:
            current_app.logger.exception("verification email failed")
    flash("If that address needs verification, a new link was sent.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    identifier = str(request.form.get("identifier", "")).strip()
    password = request.form.get("password", "")

    if "@" in identifier:
        user = storage.get_user_by_email(normalize_email(identifier))
    else:
        user = storage.get_user_by_slug(normalize_username(identifier))

    if (
        user is None
        or not user["password_hash"]
        or not check_password_hash(user["password_hash"], password)
        or not user["is_active"]
    ):
        flash("Wrong username/email or password.", "error")
        return render_template("login.html", identifier=identifier), 401

    if user["email"] and not user["email_verified"]:
        flash("Please verify your email first. Need a new link?", "unverified")
        return render_template("login.html", identifier=identifier, unverified_email=user["email"]), 403

    login_user(User(user))
    return redirect(request.args.get("next") if _safe_next(request.args.get("next")) else url_for("index"))


def _safe_next(next_url):
    return bool(next_url) and next_url.startswith("/") and not next_url.startswith("//")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Logged out. 73!", "info")
    return redirect(url_for("auth.login"))


@bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot.html")

    email = normalize_email(request.form.get("email"))
    user = storage.get_user_by_email(email) if valid_email(email) else None
    if user is not None:
        try:
            send_reset_email(user)
        except Exception:
            current_app.logger.exception("reset email failed")
    flash("If that email has an account, a reset link was sent.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/reset/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    email = _load_token(token, RESET_SALT, RESET_MAX_AGE_SECONDS)
    user = storage.get_user_by_email(email) if email else None
    if user is None:
        flash("That reset link is invalid or expired.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "GET":
        return render_template("reset.html", token=token)

    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    if len(password) < ADULT_PASSWORD_MIN:
        flash(f"Password must be at least {ADULT_PASSWORD_MIN} characters.", "error")
        return render_template("reset.html", token=token), 400
    if password != confirm:
        flash("Passwords do not match.", "error")
        return render_template("reset.html", token=token), 400

    storage.update_user(user["id"], password_hash=generate_password_hash(password))
    flash("Password updated. Log in with the new password.", "info")
    return redirect(url_for("auth.login"))
