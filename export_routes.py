# export and download endpoints

import csv
import io
import json
import re
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, session

from auth import login_required
from database import get_db

export_bp = Blueprint("export_routes", __name__)

# floor 1 ids are "R1C1", upper floors "F2R1C1"
_SEAT_RE = re.compile(r"^(?:F(\d+))?R(\d+)C(\d+)$")


def _split_seat_id(seat_id: str):
    """-> (floor, row, col) all 1-based, or None if it isn't a seat id."""
    m = _SEAT_RE.match(seat_id or "")
    if not m:
        return None
    return int(m.group(1) or 1), int(m.group(2)), int(m.group(3))


@export_bp.route("/export")
@login_required
def export_hub():
    db  = get_db()
    uid = session["user_id"]

    user   = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    venues = db.execute(
        "SELECT id, name, rows, cols, venue_type, updated_at"
        " FROM venues WHERE user_id = ? ORDER BY name",
        (uid,),
    ).fetchall()
    arrangements = db.execute(
        """SELECT a.id, a.name, a.status, a.updated_at, a.participants_json,
                  a.constraints_json, a.result_json, v.name as venue_name
           FROM arrangements a
           LEFT JOIN venues v ON a.venue_id = v.id
           WHERE a.user_id = ? ORDER BY a.name""",
        (uid,),
    ).fetchall()
    participant_count = db.execute(
        "SELECT COUNT(*) as cnt FROM participants WHERE user_id = ?", (uid,)
    ).fetchone()["cnt"]

    return render_template(
        "export.html",
        user=user,
        venues=venues,
        arrangements=arrangements,
        participant_count=participant_count,
    )


#participants 

@export_bp.route("/api/export/participants.json")
@login_required
def export_participants_json():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name",
        (session["user_id"],),
    ).fetchall()
    payload = {
        "exported_at":  datetime.utcnow().isoformat(),
        "count":        len(rows),
        "participants": [dict(r) for r in rows],
    }
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="participants.json"'},
    )


@export_bp.route("/api/export/participants.csv")
@login_required
def export_participants_csv():
    db   = get_db()
    rows = db.execute(
        "SELECT name, group_name, needs_front_row, needs_aisle, notes, created_at"
        " FROM participants WHERE user_id = ? ORDER BY name",
        (session["user_id"],),
    ).fetchall()
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["name", "group", "needs_front_row", "needs_aisle", "notes", "created_at"])
    for r in rows:
        w.writerow([
            r["name"], r["group_name"],
            "yes" if r["needs_front_row"] else "no",
            "yes" if r["needs_aisle"]     else "no",
            r["notes"], r["created_at"],
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="participants.csv"'},
    )


#arrangements

@export_bp.route("/api/export/arrangements/<int:arr_id>/assignment.csv")
@login_required
def export_arrangement_csv(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    parts  = json.loads(row["participants_json"])
    result = json.loads(row["result_json"]) if row["result_json"] else {}
    assign = result.get("assignment", {})
    p_map  = {p["name"]: p for p in parts}

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["participant", "group", "seat", "floor", "row", "col",
                "needs_front_row", "needs_aisle", "status"])

    if assign:
        for name, seat_id in sorted(assign.items()):
            p = p_map.get(name, {})
            parsed = _split_seat_id(seat_id)
            floor_n, row_n, col_n = parsed if parsed else ("", "", "")
            w.writerow([
                name,
                p.get("group") or p.get("group_name") or "",
                seat_id, floor_n, row_n, col_n,
                "yes" if p.get("needs_front_row") else "no",
                "yes" if p.get("needs_aisle")     else "no",
                row["status"],
            ])
    else:
        # if not solved yet export the roster with blank seat columns
        for p in parts:
            w.writerow([
                p["name"],
                p.get("group") or p.get("group_name") or "",
                "", "", "", "",
                "yes" if p.get("needs_front_row") else "no",
                "yes" if p.get("needs_aisle")     else "no",
                row["status"],
            ])

    safe  = "".join(c if c.isalnum() or c in "-_ " else "_" for c in row["name"])
    fname = f"arrangement_{safe.replace(' ', '_')}_assignment.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# chart image (png/jpeg) 

def _build_seating_image(row, fmt: str):
    """Draw the seating chart with Pillow. Returns (bytes, mimetype, filename)."""
    from PIL import Image, ImageDraw, ImageFont

    parts      = json.loads(row["participants_json"])
    result     = json.loads(row["result_json"]) if row["result_json"] else {}
    assign     = result.get("assignment", {})
    p_map      = {p["name"]: p for p in parts}

    db        = get_db()
    venue_row = (
        db.execute("SELECT * FROM venues WHERE id = ?", (row["venue_id"],)).fetchone()
        if row["venue_id"] else None
    )
    if venue_row:
        layout      = json.loads(venue_row["layout_json"])
        # venues saved before multi-floor support have no floors key
        floors      = layout.get("floors") or [
            {"rows": venue_row["rows"], "cols": venue_row["cols"]}]
        seats_meta  = layout.get("seats", {})
    else:
        # no venue on record, just infer the floor grids from the seat ids we have
        dims = {}
        for s in assign.values():
            parsed = _split_seat_id(s)
            if parsed:
                f, r, c = parsed
                old_r, old_c = dims.get(f, (1, 1))
                dims[f] = (max(old_r, r), max(old_c, c))
        n_floors = max(dims) if dims else 1
        floors = [{"rows": dims.get(f, (1, 1))[0], "cols": dims.get(f, (1, 1))[1]}
                  for f in range(1, n_floors + 1)]
        seats_meta = {}
    multi      = len(floors) > 1
    grid_cols  = max(f["cols"] for f in floors)

    GROUP_PALETTE = [
        (240,165,0),(59,130,246),(34,197,94),(168,85,247),
        (236,72,153),(249,115,22),(20,184,166),(239,68,68),
    ]
    groups      = sorted({p.get("group") or p.get("group_name") or ""
                          for p in parts if p.get("group") or p.get("group_name")})
    # note: this cycles through the palette by index, which is a different
    # scheme than the hash-based coloring the browser editor uses — same
    # group can end up a different color in the exported image vs the UI
    group_color = {g: GROUP_PALETTE[i % len(GROUP_PALETTE)] for i, g in enumerate(groups)}

    CELL   = 80
    GAP    = 6
    MARGIN = 48
    HDR    = 56
    LABEL_W = 34

    # floors are stacked top to bottom; with several floors each one gets a
    # title line above its column labels (FH), plus some air before the next one
    FH      = 34 if multi else 0
    F_SPACE = 48
    base_y  = HDR + MARGIN//2
    tops, y_off = [], 0
    for fl in floors:
        tops.append(base_y + y_off + FH)  # y of this floor's first row
        y_off += FH + fl["rows"] * (CELL + GAP) + (F_SPACE if multi else 0)
    y_end = tops[-1] + floors[-1]["rows"] * (CELL + GAP) - GAP  # bottom of last row

    W = MARGIN + LABEL_W + grid_cols * (CELL + GAP) - GAP + MARGIN
    H = y_end + 72  # same bottom space the single-floor image always had

    BG     = (11, 14, 20)
    PANEL  = (22, 28, 44)
    BORDER = (31, 43, 69)
    TEXT   = (232, 236, 244)
    MUTED  = (107, 122, 155)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    try:
        font_sm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    except Exception:
        font_sm = font_bold = font_name = ImageFont.load_default()

    draw.text((MARGIN, 14), row["name"], font=font_bold, fill=TEXT)
    status_color = (34,197,94) if row["status"]=="solved" else \
                   (239,68,68) if row["status"]=="infeasible" else (240,165,0)
    draw.text((MARGIN, 34),
              f"Status: {row['status'].upper()}  ·  {len(assign)}/{len(parts)} seated",
              font=font_sm, fill=status_color)

    seat_to_name = {v: k for k, v in assign.items()}

    for f, fl in enumerate(floors):
        top = tops[f]
        if multi:
            fname_txt = (fl.get("name") or "").strip() or f"Floor {f+1}"
            draw.text((MARGIN, top-58), fname_txt, font=font_bold, fill=TEXT)

        for c in range(fl["cols"]):
            cx = MARGIN + LABEL_W + c*(CELL+GAP) + CELL//2
            draw.text((cx, top-38), f"C{c+1}", font=font_sm, fill=MUTED, anchor="mm")

        for r in range(fl["rows"]):
            ry = top + r*(CELL+GAP)
            draw.text((MARGIN+LABEL_W-6, ry+CELL//2), f"R{r+1}",
                      font=font_sm, fill=MUTED, anchor="rm")
            for c in range(fl["cols"]):
                # floor 1 ids stay R1C1, upper floors are F2R1C1
                sid   = f"R{r+1}C{c+1}" if f == 0 else f"F{f+1}R{r+1}C{c+1}"
                smeta = seats_meta.get(sid, {})
                x0, y0 = MARGIN+LABEL_W+c*(CELL+GAP), ry
                x1, y1 = x0+CELL, y0+CELL
                radius  = 6

                if smeta.get("is_blocked") or smeta.get("type") == "blocked":
                    draw.rounded_rectangle([x0,y0,x1,y1], radius=radius,
                                           fill=(13,16,23), outline=BORDER)
                    draw.line([x0+12,y0+12,x1-12,y1-12], fill=MUTED, width=2)
                    draw.line([x1-12,y0+12,x0+12,y1-12], fill=MUTED, width=2)
                elif sid in seat_to_name:
                    pname = seat_to_name[sid]
                    p     = p_map.get(pname, {})
                    color = group_color.get(p.get("group") or p.get("group_name") or "",
                                            (59,130,246))
                    bg    = tuple(max(0, v-180) for v in color)
                    draw.rounded_rectangle([x0,y0,x1,y1], radius=radius,
                                           fill=bg, outline=color, width=2)
                    draw.rounded_rectangle([x0,y0,x1,y0+4], radius=2, fill=color)
                    short = pname if len(pname)<=10 else pname[:9]+"…"
                    draw.text((x0+CELL//2, y0+CELL//2), short,
                              font=font_name, fill=TEXT, anchor="mm")
                else:
                    oc = (59,80,150) if smeta.get("is_front") else \
                         (30,90,60)  if smeta.get("is_aisle") else BORDER
                    draw.rounded_rectangle([x0,y0,x1,y1], radius=radius,
                                           fill=PANEL, outline=oc)

    # group legend, if there's room for it
    leg_x, leg_y = MARGIN, y_end + GAP + 8
    if leg_y+20 < H and groups:
        draw.text((leg_x, leg_y), "Groups: ", font=font_sm, fill=MUTED)
        leg_x += 55
        for g in groups[:6]:
            c = group_color.get(g, (100,100,100))
            draw.rectangle([leg_x, leg_y+2, leg_x+10, leg_y+12], fill=c)
            draw.text((leg_x+14, leg_y), g, font=font_sm, fill=MUTED)
            leg_x += 14 + len(g)*7 + 10

    buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, format="JPEG", quality=92, optimize=True)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    buf.seek(0)

    safe  = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in row["name"])
    fname = f"arrangement_{safe.replace(' ','_')}.{fmt}"
    return buf.getvalue(), mime, fname


@export_bp.route("/api/export/arrangements/<int:arr_id>/image.<fmt>")
@login_required
def export_arrangement_image(arr_id, fmt):
    if fmt not in ("png", "jpeg", "jpg"):
        return jsonify({"error": "unsupported format — use png or jpeg"}), 400
    if fmt == "jpg":
        fmt = "jpeg"

    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    if not row["result_json"]:
        return jsonify({"error": "arrangement has not been solved yet"}), 400

    data, mime, fname = _build_seating_image(row, fmt)
    return Response(
        data,
        mimetype=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

#sample csv download
@export_bp.route("/api/export/participants_template.csv")
@login_required
def export_participants_template():
    buf = io.StringIO()
    csv.writer(buf).writerow(["name", "group", "needs_front_row", "needs_aisle", "notes"])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="participants_template.csv"'},
    )