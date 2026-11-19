import json
import secrets

from flask import (
    Blueprint, Response, jsonify, render_template, request, session, url_for,
)

from auth import login_required
from database import get_db

sharing_bp = Blueprint("sharing", __name__)


def _share_url(token: str) -> str:
    return url_for("sharing.shared_view", token=token, _external=True)


def _own_arrangement(db, arr_id):
    return db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()


def _public_headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _not_found():
    html = ("<!DOCTYPE html><html><head><title>Link not found</title></head>"
            "<body style=\"font-family:Arial,sans-serif;text-align:center;margin-top:80px\">"
            "<h1>Link not found</h1>"
            "<p>This link is invalid or sharing was turned off by its owner.</p>"
            "</body></html>")
    return _public_headers(Response(html, status=404, mimetype="text/html"))

  
@sharing_bp.route("/api/arrangements/<int:arr_id>/share", methods=["GET"])
@login_required
def api_share_status(arr_id):
    row = _own_arrangement(get_db(), arr_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    token = row["share_token"]
    return jsonify({"shared": bool(token), "url": _share_url(token) if token else None})


@sharing_bp.route("/api/arrangements/<int:arr_id>/share", methods=["POST"])
@login_required
def api_share_create(arr_id):
    db  = get_db()
    row = _own_arrangement(db, arr_id)
    if not row:
        return jsonify({"error": "not found"}), 404

    token = row["share_token"]
    if not token:
        token = secrets.token_urlsafe(16) 
        db.execute("UPDATE arrangements SET share_token = ? WHERE id = ?", (token, arr_id))
        db.commit()
    return jsonify({"shared": True, "url": _share_url(token)})


@sharing_bp.route("/api/arrangements/<int:arr_id>/share", methods=["DELETE"])
@login_required
def api_share_revoke(arr_id):
    db = get_db()
    if not _own_arrangement(db, arr_id):
        return jsonify({"error": "not found"}), 404
    db.execute("UPDATE arrangements SET share_token = NULL WHERE id = ?", (arr_id,))
    db.commit()
    return jsonify({"shared": False, "url": None})


def _build_floors(venue_row, assign):
    layout = json.loads(venue_row["layout_json"])
    floors = layout.get("floors") or [{"rows": venue_row["rows"], "cols": venue_row["cols"]}]
    seats  = layout.get("seats", {})
    seat_to_name = {sid: name for name, sid in assign.items()}

    out = []
    for fi, fl in enumerate(floors):
        grid = []
        for r in range(fl["rows"]):
            line = []
            for c in range(fl["cols"]):
                sid  = f"R{r+1}C{c+1}" if fi == 0 else f"F{fi+1}R{r+1}C{c+1}"
                meta = seats.get(sid, {})
                if meta.get("is_blocked") or meta.get("type") == "blocked":
                    kind = "blocked"
                elif meta.get("is_front"):
                    kind = "front"
                elif meta.get("is_aisle"):
                    kind = "aisle"
                else:
                    kind = "normal"
                line.append({
                    "sid":  sid,
                    "type": kind,
                    "name": seat_to_name.get(sid),
                })
            grid.append(line)
        out.append({"name": (fl.get("name") or "").strip() or f"Floor {fi+1}", "grid": grid})
    return out


def _row_by_token(token):
    return get_db().execute(
        """SELECT a.*, v.name AS venue_name
           FROM arrangements a
           LEFT JOIN venues v ON a.venue_id = v.id
           WHERE a.share_token = ?""",
        (token,),
    ).fetchone()


@sharing_bp.route("/shared/<token>")
def shared_view(token):
    row = _row_by_token(token)
    if not row:
        return _not_found()

    parts  = json.loads(row["participants_json"])
    result = json.loads(row["result_json"]) if row["result_json"] else {}
    assign = result.get("assignment", {})
    p_map  = {p["name"]: p for p in parts}

    floors = []
    if row["venue_id"]:
        venue_row = get_db().execute(
            "SELECT * FROM venues WHERE id = ?", (row["venue_id"],)
        ).fetchone()
        if venue_row and assign:
            floors = _build_floors(venue_row, assign)

    seated = [
        {"name": n, "seat": s,
         "group": p_map.get(n, {}).get("group") or p_map.get(n, {}).get("group_name") or ""}
        for n, s in sorted(assign.items())
    ]
    resp = Response(render_template(
        "shared.html",
        name=row["name"],
        venue_name=row["venue_name"],
        status=row["status"],
        floors=floors,
        seated=seated,
        total=len(parts),
        violations=result.get("violations", []),
        token=token,
    ))
    return _public_headers(resp)


@sharing_bp.route("/shared/<token>/image.<fmt>")
def shared_image(token, fmt):
    if fmt not in ("png", "jpeg", "jpg"):
        return _public_headers(jsonify({"error": "unsupported format — use png or jpeg"})), 400
    if fmt == "jpg":
        fmt = "jpeg"

    row = _row_by_token(token)
    if not row:
        return _not_found()
    if not row["result_json"] or row["status"] != "solved":
        return _public_headers(jsonify({"error": "arrangement has not been solved yet"})), 400

    from export_routes import _build_seating_image
    data, mime, fname = _build_seating_image(row, fmt)
    resp = Response(
        data,
        mimetype=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
    return _public_headers(resp)