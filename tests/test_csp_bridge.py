"""
Unit tests for the csp_bridge module
"""

import pytest
from csp_bridge import (
    build_csp_layout,
    build_csp_participants,
    build_csp_constraints,
    run_csp,
)


class MockVenueRow:
    """Mock venue row for testing."""

    def __init__(self, rows, cols, layout_json):
        self["rows"] = rows
        self["cols"] = cols
        self["layout_json"] = layout_json

    def __getitem__(self, key):
        return getattr(self, key, None)

    def __setitem__(self, key, value):
        setattr(self, key, value)


def _make_venue_layout_json(rows, cols, blocked=None, aisles=None):
    """Helper to create venue layout JSON."""
    seats = {}
    aisle_cols = aisles if aisles else {0, cols - 1}

    for r in range(rows):
        for c in range(cols):
            sid = f"R{r+1}C{c+1}"
            is_aisle = c in aisle_cols
            is_front = r == 0
            is_blocked = blocked and sid in blocked

            seat_type = "normal"
            if is_blocked:
                seat_type = "blocked"
            elif is_front:
                seat_type = "front"
            elif is_aisle:
                seat_type = "aisle"

            seats[sid] = {
                "id": sid,
                "row": r,
                "col": c,
                "type": seat_type,
                "label": "",
                "is_blocked": is_blocked,
                "is_aisle": is_aisle,
                "is_front": is_front,
            }

    import json
    return json.dumps({
        "schema_version": "1.0",
        "rows": rows,
        "cols": cols,
        "seats": seats,
    })


class TestBuildCSPLayout:
    """Tests for build_csp_layout function."""

    def test_build_layout_basic(self):
        """Test dims, blocked-seat flagging, and aisle detection together."""
        layout_json = _make_venue_layout_json(2, 4, blocked=["R1C2"])
        venue = MockVenueRow(2, 4, layout_json)

        layout = build_csp_layout(venue)

        assert layout.rows == 2
        assert layout.cols == 4
        assert layout.seats["R1C2"].is_blocked is True
        assert layout.seats["R1C1"].is_aisle is True
        assert layout.seats["R1C4"].is_aisle is True
        assert layout.seats["R1C2"].is_aisle is False


class TestBuildCSPParticipants:
    """Tests for build_csp_participants function."""

    def test_build_participants_maps_all_fields(self):
        """Test that name, group, needs_*, and reserved_seat all map through correctly."""
        data = [
            {"name": "Alice", "group": "Team A", "needs_front_row": 1},
            {"name": "Bob", "needs_aisle": 1, "reserved_seat": "R1C1"},
        ]

        participants = build_csp_participants(data)

        assert participants[0].name == "Alice"
        assert participants[0].group == "Team A"
        assert participants[0].needs_front_row is True
        assert participants[1].needs_aisle is True
        assert participants[1].reserved_seat == "R1C1"


class TestBuildCSPConstraints:
    """Tests for build_csp_constraints function."""

    @pytest.mark.parametrize("type_str", [
        "MUST_SIT_TOGETHER",   # pairwise
        "SAME_GROUP_TOGETHER", # group-based
        "SPECIFIC_SEAT",       # seat-based
    ])
    def test_build_constraints_type_mapping(self, type_str):
        """Test string->enum mapping for one representative of each constraint shape."""
        from seating_csp import ConstraintType

        data = [{"type": type_str, "participants": ["Alice"], "seat_id": "R1C1", "group": "A"}]
        constraints = build_csp_constraints(data)

        assert len(constraints) == 1
        assert constraints[0].constraint_type == ConstraintType[type_str]

    def test_build_constraints_invalid_type_skipped(self):
        """Test that invalid constraint types are skipped rather than raising."""
        data = [
            {"type": "INVALID_TYPE", "participants": ["Alice"]},
            {"type": "MUST_SIT_TOGETHER", "participants": ["Bob", "Carol"]},
        ]

        constraints = build_csp_constraints(data)

        assert len(constraints) == 1  # Only valid one included


class TestRunCSP:
    """Tests for run_csp function — the end-to-end integration path."""

    def test_run_csp_simple_success(self):
        """Test successful simple arrangement."""
        layout_json = _make_venue_layout_json(2, 2)
        venue = MockVenueRow(2, 2, layout_json)

        participants = [{"name": "Alice"}, {"name": "Bob"}]
        result, error = run_csp(venue, participants, [])

        assert result is not None
        assert error is None
        assert "Alice" in result["assignment"]
        assert "Bob" in result["assignment"]

    def test_run_csp_with_constraint(self):
        """Test arrangement with a constraint actually gets applied end-to-end."""
        layout_json = _make_venue_layout_json(1, 4)
        venue = MockVenueRow(1, 4, layout_json)

        participants = [{"name": "Alice"}, {"name": "Bob"}]
        constraints = [{"type": "MUST_SIT_TOGETHER", "participants": ["Alice", "Bob"]}]

        result, error = run_csp(venue, participants, constraints)

        assert result is not None
        from seating_csp import GridLayout
        temp_layout = GridLayout(1, 4)
        assert temp_layout.are_adjacent(
            result["assignment"]["Alice"], result["assignment"]["Bob"]
        )

    def test_run_csp_no_solution(self):
        """Test when no solution exists (not enough seats)."""
        layout_json = _make_venue_layout_json(1, 1)
        venue = MockVenueRow(1, 1, layout_json)

        participants = [{"name": "Alice"}, {"name": "Bob"}]
        result, error = run_csp(venue, participants, [])

        assert result is None
        assert error is not None

    def test_run_csp_contradictory_constraints(self):
        """Test contradictory constraints are caught end-to-end, not just in the solver."""
        layout_json = _make_venue_layout_json(1, 4)
        venue = MockVenueRow(1, 4, layout_json)

        participants = [{"name": "Alice"}, {"name": "Bob"}]
        constraints = [
            {"type": "MUST_SIT_TOGETHER", "participants": ["Alice", "Bob"]},
            {"type": "MUST_NOT_SIT_TOGETHER", "participants": ["Alice", "Bob"]},
        ]

        result, error = run_csp(venue, participants, constraints)

        assert result is None
        assert error is not None