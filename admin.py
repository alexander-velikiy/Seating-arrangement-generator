# admin dashboard: participant list -> drill into owner account + their
# seating layouts (arrangements). Deliberately narrow: the only actions
# exposed are delete / reset-password on the account, and delete / json /
# jpeg on a layout — nothing else.

import json
import secrets

from flask import Blueprint, Response, jsonify, render_template, request, session

from arrangements import arrangement_to_api
from auth import admin_required, hash_password, login_required
from database import get_db
from export_routes import _build_seating_image

admin_bp = Blueprint("admin", __name__)


def _generate_temp_password() -> str:
    # guarantees one char from each class validate_password() checks for,
    # then pads out and shuffles — avoids 'l'/'1'/'0'/'O' so it's readable
    # when handed to a user over chat/phone
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
    participants = db.execute(
        """SELECT p.id, p.name, p.group_name, p.needs_front_row, p.needs_aisle,
                  u.username as owner_username
           FROM participants p JOIN users u ON p.user_id = u.id
           ORDER BY p.name ASC"""
    ).fetchall()
    return render_template("admin.html", user=user,
                           participants=[dict(r) for r in participants])


#    participant detail (account + their layouts)   

@admin_bp.route("/api/admin/participants/<int:pid>")
@login_required
@admin_required
def api_admin_participant_detail(pid):
    db  = get_db()
    row = db.execute(
        """SELECT p.*, u.id as owner_id, u.username as owner_username,
                  u.email as owner_email, u.role as owner_role,
                  u.force_password_change as owner_force_password_change
           FROM participants p JOIN users u ON p.user_id = u.id
           WHERE p.id = ?""",
        (pid,),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    arr_rows = db.execute(
        """SELECT a.id, a.name, a.status, a.result_json, a.participants_json,
                  v.name as venue_name
           FROM arrangements a LEFT JOIN venues v ON a.venue_id = v.id
           WHERE a.user_id = ?
           ORDER BY a.updated_at DESC""",
        (row["user_id"],),
    ).fetchall()

    # an arrangement only counts as one of this participant's "layouts" if
    # they're actually seated in it — participants are stored inline as
    # JSON on the arrangement, not linked by id, so match on name
    layouts = []
    for a in arr_rows:
        names = [p.get("name") for p in json.loads(a["participants_json"])]
        if row["name"] in names:
            layouts.append({
                "id": a["id"], "name": a["name"], "status": a["status"],
                "venue_name": a["venue_name"],
                "downloadable": a["status"] == "solved" and bool(a["result_json"]),
            })

    return jsonify({
        "participant": {
            "id": row["id"], "name": row["name"], "group_name": row["group_name"],
            "needs_front_row": bool(row["needs_front_row"]),
            "needs_aisle": bool(row["needs_aisle"]),
        },
        "owner": {
            "id": row["owner_id"], "username": row["owner_username"],
            "email": row["owner_email"], "role": row["owner_role"],
            "force_password_change": bool(row["owner_force_password_change"]),
        },
        "layouts": layouts,
    })


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
    # returned once — there's no email delivery here, so the admin has to
    # hand this to the user directly
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

    # cascade manually: venues/participants/arrangements key off user_id
    # with no ON DELETE CASCADE, so an orphaned row would linger otherwise
    db.execute("DELETE FROM venues WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM participants WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM arrangements WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
    return jsonify({"deleted": uid})


#    layout (arrangement) actions   

@admin_bp.route("/api/admin/arrangements/<int:aid>", methods=["DELETE"])
@login_required
@admin_required
def api_admin_arrangement_delete(aid):
    db  = get_db()
    row = db.execute("SELECT id FROM arrangements WHERE id = ?", (aid,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM arrangements WHERE id = ?", (aid,))
    db.commit()
    return jsonify({"deleted": aid})


@admin_bp.route("/api/admin/arrangements/<int:aid>/export")
@login_required
@admin_required
def api_admin_arrangement_export(aid):
    db  = get_db()
    row = db.execute("SELECT * FROM arrangements WHERE id = ?", (aid,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    pretty   = json.dumps(arrangement_to_api(row), indent=2, ensure_ascii=False)
    safe     = "".join(c if c.isalnum() or c in "-_ " else "_" for c in row["name"])
    filename = f"arrangement_{safe.replace(' ', '_')}.json"
    return Response(
        pretty, mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_bp.route("/api/admin/arrangements/<int:aid>/image.<fmt>")
@login_required
@admin_required
def api_admin_arrangement_image(aid, fmt):
    if fmt not in ("png", "jpeg", "jpg"):
        return jsonify({"error": "unsupported format — use png or jpeg"}), 400
    if fmt == "jpg":
        fmt = "jpeg"

    db  = get_db()
    row = db.execute("SELECT * FROM arrangements WHERE id = ?", (aid,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    if not row["result_json"]:
        return jsonify({"error": "arrangement has not been solved yet"}), 400

    data, mime, fname = _build_seating_image(row, fmt)
    return Response(
        data, mimetype=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
