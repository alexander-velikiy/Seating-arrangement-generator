# predefined layouts
def _none(r, c, rows, cols):
    return False


def _auditorium(r, c, rows, cols):
    return c in (5, 11)


def _exam_hall(r, c, rows, cols):
    return (r + c) % 2 == 1


def _conference(r, c, rows, cols):
    return 1 <= r <= rows - 2 and 1 <= c <= cols - 2


def _theater(r, c, rows, cols):

    return c == cols // 2


def _event_hall(r, c, rows, cols):
    return r in (3, 6)



VENUE_PRESETS = {
    "classroom": {
        "label": "Classroom", "rows": 5, "cols": 6,
        "blocked": _none, "aisle_cols": None,
        "description": "5x6 open grid, aisle seats on both outer columns.",
    },
    "auditorium": {
        "label": "Auditorium", "rows": 12, "cols": 17,
        "blocked": _auditorium, "aisle_cols": {0, 4, 6, 10, 12, 16},
        "description": "12x17, three sections of 5 separated by two walkways.",
    },
    "exam_hall": {
        "label": "Exam Hall", "rows": 8, "cols": 10,
        "blocked": _exam_hall, "aisle_cols": None,
        "description": "8x10 checkerboard so no two candidates are adjacent.",
    },
    "conference": {
        "label": "Conference Room", "rows": 6, "cols": 8,
        "blocked": _conference, "aisle_cols": None,
        "description": "6x8 with the middle blocked out as the table; seating around the edge.",
    },
    "theater": {
        "label": "Theater", "rows": 12, "cols": 15,
        "blocked": _theater, "aisle_cols": {0, 6, 8, 14},
        "description": "12x15 with a centre aisle; seats next to either aisle count as aisle seats.",
    },
    "event_hall": {
        "label": "Event Hall", "rows": 9, "cols": 12,
        "blocked": _event_hall, "aisle_cols": None,
        "description": "9x12 floor with two walkway rows between three blocks of seats.",
    },
}


def build_preset_seats(venue_type: str):
    """Return (rows, cols, seats) for a venue type, or None if it has no preset."""
    p = VENUE_PRESETS.get(venue_type)
    if not p:
        return None

    rows, cols = p["rows"], p["cols"]
    aisle_cols = p["aisle_cols"] if p["aisle_cols"] is not None else {0, cols - 1}

    seats = {}
    for r in range(rows):
        for c in range(cols):
            sid        = f"R{r+1}C{c+1}"
            is_blocked = bool(p["blocked"](r, c, rows, cols))
            is_front   = (r == 0)
            is_aisle   = (c in aisle_cols) and not is_blocked

            if is_blocked:
                stype = "blocked"
            elif is_front:
                stype = "front"
            elif is_aisle:
                stype = "aisle"
            else:
                stype = "normal"

            seats[sid] = {
                "id": sid, "row": r, "col": c, "type": stype, "label": "",
                "is_blocked": is_blocked, "is_aisle": is_aisle, "is_front": is_front,
            }
    return rows, cols, seats


def all_presets() -> dict:
    out = {}
    for vtype, p in VENUE_PRESETS.items():
        rows, cols, seats = build_preset_seats(vtype)
        out[vtype] = {
            "label": p["label"], "description": p["description"],
            "rows": rows, "cols": cols, "seats": seats,
        }
    return out