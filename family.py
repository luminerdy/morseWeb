"""Parent-managed student accounts (the COPPA-relevant piece).

A parent creates each child account with a username and password - no
child email is collected. Creating a child requires the parent to check
a consent statement; the consent timestamp and the consenting parent
are stored on the child row.
"""

import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.security import generate_password_hash

import storage
from auth import (
    CHILD_PASSWORD_MIN, MAX_NAME_CHARS, normalize_username, role_required,
)

bp = Blueprint("family", __name__, url_prefix="/family")

CONSENT_STATEMENT = (
    "I am this child's parent or legal guardian and I consent to morseWeb "
    "storing their practice progress under the account I manage."
)


def _own_child_or_404(child_id):
    child = storage.get_user(child_id)
    if child is None or child["parent_id"] != current_user.id:
        abort(404)
    return child


@bp.route("")
@role_required("parent", "admin")
def family_home():
    children = storage.list_children(current_user.id)
    for child in children:
        child["usage"] = storage.user_usage(child["id"])
    return render_template(
        "family.html",
        children=children,
        consent_statement=CONSENT_STATEMENT,
        child_password_min=CHILD_PASSWORD_MIN,
    )


@bp.route("/children", methods=["POST"])
@role_required("parent", "admin")
def add_child():
    username = normalize_username(request.form.get("username"))
    name = str(request.form.get("name", "")).strip()[:MAX_NAME_CHARS]
    password = request.form.get("password", "")
    consent = request.form.get("consent") == "yes"

    error = None
    if not username:
        error = "Please choose a username (letters, numbers, dashes)."
    elif not name:
        error = "Please enter the child's display name."
    elif len(password) < CHILD_PASSWORD_MIN:
        error = f"Password must be at least {CHILD_PASSWORD_MIN} characters."
    elif not consent:
        error = "Parent consent is required to create a child account."

    if error is None:
        try:
            storage.create_user(
                slug=username,
                name=name,
                password_hash=generate_password_hash(password),
                role="student",
                parent_id=current_user.id,
                consent_at=storage.now_iso(),
                consent_by=current_user.id,
            )
        except sqlite3.IntegrityError:
            error = "That username is taken. Try another."

    if error:
        flash(error, "error")
    else:
        flash(f"Account for {name} created. They log in with the username '{username}'.", "info")
    return redirect(url_for("family.family_home"))


@bp.route("/children/<int:child_id>/password", methods=["POST"])
@role_required("parent", "admin")
def reset_child_password(child_id):
    child = _own_child_or_404(child_id)
    password = request.form.get("password", "")
    if len(password) < CHILD_PASSWORD_MIN:
        flash(f"Password must be at least {CHILD_PASSWORD_MIN} characters.", "error")
    else:
        storage.update_user(child["id"], password_hash=generate_password_hash(password))
        flash(f"Password updated for {child['name']}.", "info")
    return redirect(url_for("family.family_home"))


@bp.route("/children/<int:child_id>/active", methods=["POST"])
@role_required("parent", "admin")
def toggle_child_active(child_id):
    child = _own_child_or_404(child_id)
    now_active = 0 if child["is_active"] else 1
    storage.update_user(child["id"], is_active=now_active)
    flash(
        f"{child['name']} can {'now' if now_active else 'no longer'} log in.",
        "info",
    )
    return redirect(url_for("family.family_home"))
