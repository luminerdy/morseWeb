"""Admin dashboard.

Replaces morsePi's desktop admin reset: per-student reset that first
snapshots everything into progress_backups, plus a basic usage view and
account activation toggle. Admins are created with scripts/make_admin.py.
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

import storage
from auth import role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _user_or_404(user_id):
    user = storage.get_user(user_id)
    if user is None:
        abort(404)
    return user


@bp.route("")
@role_required("admin")
def admin_home():
    users = storage.list_users()
    for user in users:
        user["usage"] = storage.user_usage(user["id"])
        user["backups"] = storage.list_backups(user["id"])
    return render_template("admin.html", users=users)


@bp.route("/users/<int:user_id>/reset", methods=["POST"])
@role_required("admin")
def reset_user(user_id):
    user = _user_or_404(user_id)
    storage.backup_and_reset_user(
        user["id"], reason=f"admin reset by {current_user.slug}"
    )
    flash(f"Progress for {user['name']} was backed up and reset.", "info")
    return redirect(url_for("admin.admin_home"))


@bp.route("/users/<int:user_id>/active", methods=["POST"])
@role_required("admin")
def toggle_user_active(user_id):
    user = _user_or_404(user_id)
    if user["id"] == current_user.id:
        flash("You cannot deactivate your own admin account.", "error")
        return redirect(url_for("admin.admin_home"))
    now_active = 0 if user["is_active"] else 1
    storage.update_user(user["id"], is_active=now_active)
    flash(f"{user['name']} is now {'active' if now_active else 'deactivated'}.", "info")
    return redirect(url_for("admin.admin_home"))
