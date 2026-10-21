"""
Tests for multi-floor venues (balconies etc.)
"""

import json

import pytest
from csp_bridge import build_csp_layout, run_csp
from export_routes import _split_seat_id
from seating_csp import (
    Constraint,
    ConstraintType,
    GridLayout,
    Participant,
    SeatingCSP,
    make_seat_id,
)
from venues import build_layout_json, parse_floors


class MockVenueRow:
    """Mock venue row, same idea as in test_csp_bridge."""

    def __init__(self, rows, cols, layout_json):
        self.data = {"rows": rows, "cols": cols, "layout_json": layout_json}

    def __getitem__(self, key):
        return self.data[key]


def _theater_row():
    # main floor 3x4 + balcony 2x3
    floors = [{"name": "Stalls", "rows": 3, "cols": 4}, {"name": "Balcony", "rows": 2, "cols": 3}]
    layout = build_layout_json(3, 4, floors=floors)
    return MockVenueRow(3, 4, json.dumps(layout))


class TestSeatIds:
    def test_floor_one_keeps_plain_ids(self):
        assert make_seat_id(1, 2, 3) == "R2C3"

    def test_upper_floor_gets_prefix(self):
        assert make_seat_id(2, 1, 1) == "F2R1C1"

    def test_split_seat_id(self):
        assert _split_seat_id("R2C3") == (1, 2, 3)
        assert _split_seat_id("F2R10C12") == (2, 10, 12)
        assert _split_seat_id("nope") is None


class TestGridLayoutFloors:
    def test_single_floor_unchanged(self):
        layout = GridLayout(rows=3, cols=4)
        assert layout.floor_count == 1
        assert len(layout.seats) == 12
        assert all(s.floor == 1 for s in layout.seats.values())

    def test_floors_have_own_sizes(self):
        layout = GridLayout(rows=3, cols=4, floors=[
            {"rows": 3, "cols": 4}, {"rows": 2, "cols": 3}])
        assert layout.floor_count == 2
        assert len(layout.seats) == 12 + 6
        assert "F2R2C3" in layout.seats
        assert "F2R3C1" not in layout.seats  # balcony only has 2 rows

    def test_adjacency_never_crosses_floors(self):
        layout = GridLayout(rows=2, cols=2, floors=[
            {"rows": 2, "cols": 2}, {"rows": 2, "cols": 2}])
        assert layout.are_adjacent("R1C1", "R1C2") is True
        assert layout.are_adjacent("F2R1C1", "F2R1C2") is True
        assert layout.are_adjacent("R1C1", "F2R1C1") is False

    def test_neighbors_stay_on_floor(self):
        layout = GridLayout(rows=2, cols=2, floors=[
            {"rows": 2, "cols": 2}, {"rows": 2, "cols": 2}])
        assert sorted(layout.neighbors("F2R1C1")) == ["F2R1C2", "F2R2C1"]

    def test_every_floor_has_a_front_row(self):
        layout = GridLayout(rows=2, cols=3, floors=[
            {"rows": 2, "cols": 3}, {"rows": 2, "cols": 3}])
        front = {s.seat_id for s in layout.front_row_seats()}
        assert front == {"R1C1", "R1C2", "R1C3", "F2R1C1", "F2R1C2", "F2R1C3"}

    def test_aisle_cols_are_per_floor(self):
        layout = GridLayout(rows=1, cols=4, floors=[
            {"rows": 1, "cols": 4},
            {"rows": 1, "cols": 4, "aisle_cols": [1]},
        ])
        assert layout.seats["R1C1"].is_aisle is True
        assert layout.seats["F2R1C1"].is_aisle is False
        assert layout.seats["F2R1C2"].is_aisle is True


class TestSolverAcrossFloors:
    def test_must_sit_together_needs_same_floor(self):
        # 1 seat per floor, so the pair can never be adjacent -> no solution
        layout = GridLayout(rows=1, cols=1, floors=[
            {"rows": 1, "cols": 1}, {"rows": 1, "cols": 1}])
        parts = [Participant("A"), Participant("B")]
        cons = [Constraint(ConstraintType.MUST_SIT_TOGETHER, participants=["A", "B"])]
        assert SeatingCSP(parts, layout, cons, seed=1).solve() is None

    def test_reserved_balcony_seat(self):
        layout = GridLayout(rows=2, cols=2, floors=[
            {"rows": 2, "cols": 2}, {"rows": 2, "cols": 2}])
        parts = [Participant("A", reserved_seat="F2R2C2"), Participant("B")]
        result = SeatingCSP(parts, layout, [], seed=1).solve()
        assert result["A"] == "F2R2C2"

    def test_front_row_can_be_balcony_front(self):
        # main floor is full of blocked seats except the back row, so the only
        # front-row seats left are in the balcony
        layout = GridLayout(rows=2, cols=2,
                            blocked_seats=["R1C1", "R1C2"],
                            floors=[{"rows": 2, "cols": 2}, {"rows": 1, "cols": 2}])
        parts = [Participant("A", needs_front_row=True)]
        result = SeatingCSP(parts, layout, [], seed=1).solve()
        assert result["A"] in ("F2R1C1", "F2R1C2")

    def test_capacity_counts_all_floors(self):
        layout = GridLayout(rows=1, cols=2, floors=[
            {"rows": 1, "cols": 2}, {"rows": 1, "cols": 2}])
        parts = [Participant(f"P{i}") for i in range(4)]
        result = SeatingCSP(parts, layout, [], seed=1).solve()
        assert len(set(result.values())) == 4


class TestBridge:
    def test_build_layout_from_floors(self):
        layout = build_csp_layout(_theater_row())
        assert layout.floor_count == 2
        assert len(layout.seats) == 12 + 6
        assert layout.seats["F2R1C1"].floor == 2

    def test_old_layout_without_floors_key(self):
        # layout json saved before multi-floor support
        old = {"rows": 2, "cols": 3, "seats": {
            f"R{r+1}C{c+1}": {"row": r, "col": c} for r in range(2) for c in range(3)}}
        layout = build_csp_layout(MockVenueRow(2, 3, json.dumps(old)))
        assert layout.floor_count == 1
        assert len(layout.seats) == 6

    def test_blocked_balcony_seat_is_respected(self):
        data = json.loads(_theater_row()["layout_json"])
        data["seats"]["F2R1C1"]["is_blocked"] = True
        layout = build_csp_layout(MockVenueRow(3, 4, json.dumps(data)))
        assert layout.seats["F2R1C1"].is_blocked is True

    def test_run_csp_end_to_end(self):
        parts = [{"name": f"P{i}"} for i in range(16)]  # 18 seats total
        result, err = run_csp(_theater_row(), parts, [])
        assert err is None
        seats = set(result["assignment"].values())
        assert len(seats) == 16
        assert any(s.startswith("F2") for s in seats)  # main floor only has 12


class TestVenueLayoutBuilder:
    def test_single_floor_layout_matches_old_shape(self):
        layout = build_layout_json(2, 3)
        assert len(layout["seats"]) == 6
        assert "R2C3" in layout["seats"]
        assert len(layout["floors"]) == 1

    def test_multi_floor_ids_and_fields(self):
        layout = build_layout_json(2, 2, floors=[
            {"name": "Main", "rows": 2, "cols": 2},
            {"name": "Balcony", "rows": 1, "cols": 3}])
        assert len(layout["seats"]) == 4 + 3
        assert layout["seats"]["F2R1C3"]["floor"] == 2
        assert layout["seats"]["R1C1"]["floor"] == 1
        assert layout["rows"] == 2 and layout["cols"] == 2  # floor 1

    def test_seat_overrides_apply_on_upper_floor(self):
        layout = build_layout_json(
            1, 1,
            seats_override={"F2R1C1": {"type": "blocked", "is_blocked": True}},
            floors=[{"rows": 1, "cols": 1}, {"rows": 1, "cols": 1}])
        assert layout["seats"]["F2R1C1"]["is_blocked"] is True
        assert layout["stats"]["blocked"] == 1


class TestParseFloors:
    def test_no_floors_is_fine(self):
        assert parse_floors({}, 5, 5) == (None, None)

    def test_valid(self):
        floors, err = parse_floors({"floors": [{"rows": 3, "cols": 4}, {"rows": 2, "cols": 5}]}, 3, 4)
        assert err is None and len(floors) == 2

    @pytest.mark.parametrize("bad", [
        [{"rows": 0, "cols": 4}],
        [{"rows": 31, "cols": 4}],
        [{"rows": "x", "cols": 4}],
        [{"cols": 4}],
        [{"rows": 1, "cols": 1}] * 7,
        "not a list",
    ])
    def test_invalid(self, bad):
        floors, err = parse_floors({"floors": bad}, 1, 1)
        assert floors is None and err
