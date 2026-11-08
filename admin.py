# admin page: list of all accounts, add a planner, delete an account or reset pass

import secrets
import sqlite3
from datetime import datetime

from flask import (
    Blueprint, flash, jsonify, redirect, render_template,
    request, session, url_for,
)

from auth import admin_required, hash_password, login_required, validate_password
from database import get_db

admin_bp = Blueprint("admin", __name__)


def _generate_temp_password() -> str:
    lower   = "abcdefghijkmnopqrstuvwxyz"
    upper   = lower.upper()
    digits  = "23456789"
    symbols = "!@#$%*?"
    pool    = lower + upper + digits + symbols

    chars = [secrets.choice(upper), secrets.choice(lower),
             secrets.choice(digits), secrets.choice(symbols)]
    chars += [secrets.choice(pool) for _ in range(6)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


#    page   

@admin_bp.route("/admin")
@login_required
@admin_required
def admin_page():
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    users = db.execute(
        """SELECT id, username, email, role, force_password_change, created_at
           FROM users ORDER BY username COLLATE NOCASE ASC"""
    ).fetchall()
    return render_template("admin.html", user=user, users=[dict(r) for r in users])


#    add a planner   

@admin_bp.route("/admin/users", methods=["POST"])
@login_required
@admin_required
def admin_user_create():
    back = redirect(url_for("admin.admin_page"))

    username = request.form.get("username", "").strip()
    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if len(username) < 3:
        flash("Username must be at least 3 characters.", "error")
        return back
    if not email:
        flash("Email is required.", "error")
        return back
    pw_error = validate_password(password)
    if pw_error:
        flash(pw_error, "error")
        return back

    db = get_db()
    try:
        # force_password_change 
        db.execute(
            """INSERT INTO users
               (username, email, password, role, force_password_change, created_at)
               VALUES (?,?,?,?,?,?)""",
            (username, email, hash_password(password), "planner", 1,
             datetime.utcnow().isoformat()),
        )
        db.commit()
        flash(f"Planner '{username}' created. They must change the password at first login.",
              "success")
    except sqlite3.IntegrityError:
        flash("Username or email already taken.", "error")
    return back


#    account actions

@admin_bp.route("/api/admin/users/<int:uid>/reset-password", methods=["POST"])
@login_required
@admin_required
def api_admin_user_reset_password(uid):
    db  = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    temp_password = _generate_temp_password()
    db.execute(
        "UPDATE users SET password = ?, force_password_change = 1 WHERE id = ?",
        (hash_password(temp_password), uid),
    )
    db.commit()
    return jsonify({"username": row["username"], "temp_password": temp_password})


@admin_bp.route("/api/admin/users/<int:uid>", methods=["DELETE"])
@login_required
@admin_required
def api_admin_user_delete(uid):
    db  = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    if row["username"] == "admin":
        return jsonify({"error": "cannot delete the built-in admin account"}), 400
    if uid == session["user_id"]:
        return jsonify({"error": "cannot delete your own account"}), 400

    # cascade manually
    db.execute("DELETE FROM venues WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM participants WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM arrangements WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
    return jsonify({"deleted": uid})