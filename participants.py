# the global roster page + its API

import sqlite3
from datetime import datetime

from flask import (
    Blueprint, flash, jsonify, redirect, render_template,
    request, session, url_for,
)

from auth import login_required
from database import get_db

participants_bp = Blueprint("participants", __name__)


def compute_stats(rows):
    groups = {r["group_name"] for r in rows if r["group_name"]}
    return {
        "total":  len(rows),
        "groups": len(groups),
        "front":  sum(1 for r in rows if r["needs_front_row"]),
        "aisle":  sum(1 for r in rows if r["needs_aisle"]),
    }


#    page   

@participants_bp.route("/participants")
@login_required
def participants_list():
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    all_rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name ASC",
        (session["user_id"],),
    ).fetchall()

    # search + group filtering happens here in Python, not in JS —
    # both come in as query params so the URL stays shareable/bookmarkable
    query        = request.args.get("q", "").strip()
    active_group = request.args.get("group", "").strip()

    filtered = list(all_rows)
    if active_group:
        filtered = [r for r in filtered if r["group_name"] == active_group]
    if query:
        q_lower = query.lower()
        filtered = [
            r for r in filtered
            if q_lower in r["name"].lower() or q_lower in (r["group_name"] or "").lower()
        ]

    all_groups = sorted({r["group_name"] for r in all_rows if r["group_name"]})
    stats      = compute_stats(all_rows)

    # ?edit=<id> puts the form panel into edit mode for that participant
    edit_participant = None
    edit_id = request.args.get("edit")
    if edit_id:
        edit_participant = db.execute(
            "SELECT * FROM participants WHERE id = ? AND user_id = ?",
            (edit_id, session["user_id"]),
        ).fetchone()

    return render_template(
        "participants.html",
        user=user,
        participants=filtered,
        stats=stats,
        query=query,
        active_group=active_group,
        all_groups=all_groups,
        edit_participant=edit_participant,
    )


@participants_bp.route("/participants/new", methods=["POST"])
@login_required
def participant_new():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("participants.participants_list"))

    now = datetime.utcnow().isoformat()
    db  = get_db()
    try:
        db.execute(
            """INSERT INTO participants
               (user_id, name, group_name, needs_front_row, needs_aisle, notes, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                session["user_id"],
                name,
                request.form.get("group_name", "").strip(),
                1 if request.form.get("needs_front_row") else 0,
                1 if request.form.get("needs_aisle")     else 0,
                request.form.get("notes", "").strip(),
                now,
            ),
        )
        db.commit()
        flash(f"Added {name}.", "success")
    except sqlite3.IntegrityError:
        flash(f"A participant named '{name}' already exists.", "error")

    return redirect(url_for("participants.participants_list"))


@participants_bp.route("/participants/<int:pid>/edit", methods=["POST"])
@login_required
def participant_edit(pid):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM participants WHERE id = ? AND user_id = ?",
        (pid, session["user_id"]),
    ).fetchone()
    if not row:
        flash("Participant not found.", "error")
        return redirect(url_for("participants.participants_list"))

    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("participants.participants_list", edit=pid))

    try:
        db.execute(
            """UPDATE participants
               SET name=?, group_name=?, needs_front_row=?, needs_aisle=?, notes=?
               WHERE id=?""",
            (
                name,
                request.form.get("group_name", "").strip(),
                1 if request.form.get("needs_front_row") else 0,
                1 if request.form.get("needs_aisle")     else 0,
                request.form.get("notes", "").strip(),
                pid,
            ),
        )
        db.commit()
        flash(f"Updated {name}.", "success")
    except sqlite3.IntegrityError:
        flash(f"A participant named '{name}' already exists.", "error")
        return redirect(url_for("participants.participants_list", edit=pid))

    return redirect(url_for("participants.participants_list"))


@participants_bp.route("/participants/<int:pid>/delete", methods=["POST"])
@login_required
def participant_delete(pid):
    db  = get_db()
    row = db.execute(
        "SELECT name FROM participants WHERE id = ? AND user_id = ?",
        (pid, session["user_id"]),
    ).fetchone()
    if row:
        db.execute("DELETE FROM participants WHERE id = ?", (pid,))
        db.commit()
        flash(f"Deleted {row['name']}.", "success")
    else:
        flash("Participant not found.", "error")
    return redirect(url_for("participants.participants_list"))


#    json api — unchanged. the arrangement editor's roster-import modal
#    fetches /api/participants directly via JS, so this has to keep working
#    exactly as before regardless of how the human-facing page is rendered.

@participants_bp.route("/api/participants", methods=["GET"])
@login_required
def api_participants_list():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name ASC",
        (session["user_id"],),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@participants_bp.route("/api/participants", methods=["POST"])
@login_required
def api_participant_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    now = datetime.utcnow().isoformat()
    db  = get_db()
    try:
        cur = db.execute(
            """INSERT INTO participants
               (user_id, name, group_name, needs_front_row, needs_aisle, notes, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                session["user_id"],
                name,
                (data.get("group_name") or "").strip(),
                1 if data.get("needs_front_row") else 0,
                1 if data.get("needs_aisle")     else 0,
                (data.get("notes") or "").strip(),
                now,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM participants WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"A participant named '{name}' already exists."}), 409


@participants_bp.route("/api/participants/<int:pid>", methods=["PUT"])
@login_required
def api_participant_update(pid):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM participants WHERE id = ? AND user_id = ?",
        (pid, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or row["name"]).strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        db.execute(
            """UPDATE participants
               SET name=?, group_name=?, needs_front_row=?, needs_aisle=?, notes=?
               WHERE id=?""",
            (
                name,
                (data.get("group_name", row["group_name"]) or "").strip(),
                1 if data.get("needs_front_row") else 0,
                1 if data.get("needs_aisle")     else 0,
                (data.get("notes", row["notes"]) or "").strip(),
                pid,
            ),
        )
        db.commit()
        updated = db.execute("SELECT * FROM participants WHERE id = ?", (pid,)).fetchone()
        return jsonify(dict(updated))
    except sqlite3.IntegrityError:
        return jsonify({"error": f"A participant named '{name}' already exists."}), 409


@participants_bp.route("/api/participants/<int:pid>", methods=["DELETE"])
@login_required
def api_participant_delete(pid):
    db  = get_db()
    row = db.execute(
        "SELECT id FROM participants WHERE id = ? AND user_id = ?",
        (pid, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM participants WHERE id = ?", (pid,))
    db.commit()
    return jsonify({"deleted": pid})