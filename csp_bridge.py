# connector for csp solver

import json
from datetime import datetime

from seating_csp import (
    Constraint,
    ConstraintType,
    GridLayout,
    Participant,
    SeatingCSP,
)


# ConstraintType enum
_CTYPE_MAP: dict[str, ConstraintType] = {
    "MUST_SIT_TOGETHER":     ConstraintType.MUST_SIT_TOGETHER,
    "MUST_NOT_SIT_TOGETHER": ConstraintType.MUST_NOT_SIT_TOGETHER,
    "SAME_GROUP_TOGETHER":   ConstraintType.SAME_GROUP_TOGETHER,
    "SAME_GROUP_APART":      ConstraintType.SAME_GROUP_APART,
    "FRONT_ROW":             ConstraintType.FRONT_ROW,
    "NEAR_AISLE":            ConstraintType.NEAR_AISLE,
    "SPECIFIC_SEAT":         ConstraintType.SPECIFIC_SEAT,
    "RESERVED_SEAT":         ConstraintType.RESERVED_SEAT,
}


def build_csp_layout(venue_row) -> GridLayout:
    """Turn a venues table row into a GridLayout."""
    layout = json.loads(venue_row["layout_json"])
    seats  = layout.get("seats", {})
    rows   = venue_row["rows"]
    cols   = venue_row["cols"]

    blocked = [
        sid for sid, s in seats.items()
        if s.get("is_blocked") or s.get("type") == "blocked"
    ]
    # support for no floor layout
    floors = [dict(f) for f in layout.get("floors") or [{"rows": rows, "cols": cols}]]

    aisle_by_floor: dict[int, set[tuple[int, int]]] = {}
    front_by_floor: dict[int, set[int]] = {}
    for s in seats.values():
        fno = s.get("floor", 1)
        if s.get("is_aisle") or s.get("type") == "aisle":
            aisle_by_floor.setdefault(fno, set()).add((s["row"], s["col"]))
        if s.get("type") == "front" and not s.get("is_blocked"):
            front_by_floor.setdefault(fno, set()).add(s["row"])
    for i, fl in enumerate(floors):
        found = aisle_by_floor.get(i + 1)
        fl["aisle_cells"] = sorted(found) if found else None
        # allow only first or last row
        fr = front_by_floor.get(i + 1, set())
        fl["front_row"] = next(iter(fr)) if len(fr) == 1 else 0

    return GridLayout(
        rows=floors[0]["rows"],
        cols=floors[0]["cols"],
        blocked_seats=blocked,
        floors=floors,
    )


def build_csp_participants(participants_data: list) -> list[Participant]:
    return [
        Participant(
            name=p["name"],
            group=p.get("group") or None,
            needs_front_row=bool(p.get("needs_front_row")),
            needs_aisle=bool(p.get("needs_aisle")),
            reserved_seat=p.get("reserved_seat") or None,
        )
        for p in participants_data
    ]


def build_csp_constraints(constraints_data: list) -> list[Constraint]:
    result = []
    for c in constraints_data:
        ctype = _CTYPE_MAP.get(c.get("type", ""))
        if not ctype:
            continue
        result.append(
            Constraint(
                constraint_type=ctype,
                participants=c.get("participants", []),
                group=c.get("group") or None,
                seat_id=c.get("seat_id") or None,
            )
        )
    return result


def run_csp(
    venue_row,
    participants_data: list,
    constraints_data: list,
) -> tuple[dict | None, str | None]:
    """
    Build the CSP objects, run the solver, return (result, error) — only
    one of the two will be non-None.

    result contains:
      assignment - name -> seat_id
      violations - anything _verify() caught after solving
      solved_at  - timestamp
      stats      - a few counts for the UI
    """
    try:
        layout       = build_csp_layout(venue_row)
        participants = build_csp_participants(participants_data)
        constraints  = build_csp_constraints(constraints_data)

        csp    = SeatingCSP(participants, layout, constraints)
        assign = csp.solve()

        if assign is None:
            return None, (
                "No valid arrangement found. "
                "Check that constraints are not contradictory and that "
                "enough seats are available."
            )

        violations = csp._verify(assign)
        return {
            "assignment": assign,
            "violations": violations,
            "solved_at":  datetime.utcnow().isoformat(),
            "stats": {
                "participants": len(participants_data),
                "seats_used":   len(assign),
                "violations":   len(violations),
            },
        }, None

    except ValueError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"Solver error: {exc}"