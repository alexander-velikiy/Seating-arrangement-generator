"""
test_seating_csp.py
===================
Unit tests for the seating_csp module (CSP solver core).

Scope note: dataclass field-storage tests (Participant/Constraint/Seat)
were intentionally dropped — if those fields were broken, the solver
tests below would fail immediately anyway, so they added latency
without independent coverage.

Tests cover:
- GridLayout construction, aisle/blocked-seat handling, adjacency, neighbors
- SeatingCSP: domain init, constraint solving (all constraint types), edge cases
- Post-hoc constraint verification, including the documented FRONT_ROW gap
  (FRONT_ROW is only enforced in _verify, not during backtracking search —
  needs_front_row on Participant is the path that's enforced during search)
"""

import pytest
from seating_csp import (
    Participant,
    Constraint,
    ConstraintType,
    GridLayout,
    SeatingCSP,
)


class TestGridLayout:
    """Tests for the GridLayout class."""

    def test_grid_layout_creation_and_seat_ids(self):
        """Test basic grid layout creation and seat ID generation."""
        layout = GridLayout(rows=3, cols=4)
        assert layout.rows == 3
        assert layout.cols == 4
        assert len(layout.seats) == 12
        assert "R1C1" in layout.seats
        assert "R3C4" in layout.seats

    def test_grid_layout_default_aisles(self):
        """Test default aisle columns (first and last) — this is the logic
        csp_bridge relies on to infer aisle columns from seat metadata."""
        layout = GridLayout(rows=2, cols=4)
        assert layout.seats["R1C1"].is_aisle is True
        assert layout.seats["R1C4"].is_aisle is True
        assert layout.seats["R1C2"].is_aisle is False
        assert layout.seats["R1C3"].is_aisle is False

    def test_grid_layout_blocked_and_available_seats(self):
        """Test blocked seats are flagged and excluded from available_seats()."""
        layout = GridLayout(rows=2, cols=2, blocked_seats=["R1C1"])
        assert layout.seats["R1C1"].is_blocked is True
        assert layout.seats["R1C2"].is_blocked is False

        available = layout.available_seats()
        assert len(available) == 3
        assert "R1C1" not in [s.seat_id for s in available]

    def test_grid_layout_adjacency(self):
        """Test adjacency check across horizontal, vertical, diagonal, and far cases."""
        layout = GridLayout(rows=3, cols=3)
        assert layout.are_adjacent("R1C1", "R1C2") is True   # horizontal
        assert layout.are_adjacent("R1C1", "R2C1") is True   # vertical
        assert layout.are_adjacent("R1C1", "R2C2") is False  # diagonal
        assert layout.are_adjacent("R1C1", "R1C3") is False  # far

    def test_grid_layout_neighbors(self):
        """Test neighbors method for center, corner, and blocked-adjacent seats."""
        layout = GridLayout(rows=3, cols=3, blocked_seats=["R1C2"])
        center_neighbors = GridLayout(rows=3, cols=3).neighbors("R2C2")
        assert len(center_neighbors) == 4

        corner_neighbors = GridLayout(rows=3, cols=3).neighbors("R1C1")
        assert len(corner_neighbors) == 2

        blocked_neighbors = layout.neighbors("R1C1")
        assert "R1C2" not in blocked_neighbors
        assert "R2C1" in blocked_neighbors


class TestSeatingCSP:
    """Tests for the SeatingCSP solver — the core algorithm."""

    def _make_simple_layout(self):
        return GridLayout(rows=2, cols=2)

    def _make_simple_participants(self):
        return [Participant(name="Alice"), Participant(name="Bob")]

    def test_seating_csp_not_enough_seats(self):
        """Test error when not enough seats."""
        layout = GridLayout(rows=1, cols=1)
        participants = [Participant(name="Alice"), Participant(name="Bob")]
        with pytest.raises(ValueError, match="Not enough seats"):
            SeatingCSP(participants, layout, [])

    def test_seating_csp_solve_simple(self):
        """Test solving a simple arrangement (also covers basic creation/domains)."""
        layout = self._make_simple_layout()
        participants = self._make_simple_participants()
        csp = SeatingCSP(participants, layout, [])

        assert len(csp.domains["Alice"]) == 4  # all 4 seats available

        result = csp.solve()
        assert result is not None
        assert result["Alice"] != result["Bob"]

    def test_seating_csp_must_sit_together(self):
        """Test MUST_SIT_TOGETHER constraint."""
        layout = GridLayout(rows=1, cols=4)
        participants = [Participant(name="Alice"), Participant(name="Bob")]
        constraints = [
            Constraint(constraint_type=ConstraintType.MUST_SIT_TOGETHER,
                       participants=["Alice", "Bob"]),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()

        assert result is not None
        assert layout.are_adjacent(result["Alice"], result["Bob"])

    def test_seating_csp_must_not_sit_together(self):
        """Test MUST_NOT_SIT_TOGETHER constraint."""
        layout = GridLayout(rows=1, cols=4)
        participants = [Participant(name="Alice"), Participant(name="Bob")]
        constraints = [
            Constraint(constraint_type=ConstraintType.MUST_NOT_SIT_TOGETHER,
                       participants=["Alice", "Bob"]),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()

        assert result is not None
        assert not layout.are_adjacent(result["Alice"], result["Bob"])

    def test_seating_csp_front_row_need(self):
        """Test participant needing front row (needs_front_row path, enforced during search)."""
        layout = GridLayout(rows=3, cols=2)
        participants = [
            Participant(name="Alice", needs_front_row=True),
            Participant(name="Bob"),
        ]
        csp = SeatingCSP(participants, layout, [])
        result = csp.solve()

        assert result is not None
        assert layout.seats[result["Alice"]].row == 0

    def test_seating_csp_aisle_need(self):
        """Test participant needing aisle seat."""
        layout = GridLayout(rows=2, cols=4)
        participants = [
            Participant(name="Alice", needs_aisle=True),
            Participant(name="Bob"),
        ]
        csp = SeatingCSP(participants, layout, [])
        result = csp.solve()

        assert result is not None
        assert layout.seats[result["Alice"]].is_aisle is True

    def test_seating_csp_reserved_seat(self):
        """Test participant with reserved seat."""
        layout = self._make_simple_layout()
        participants = [
            Participant(name="Alice", reserved_seat="R1C1"),
            Participant(name="Bob"),
        ]
        csp = SeatingCSP(participants, layout, [])
        result = csp.solve()

        assert result is not None
        assert result["Alice"] == "R1C1"

    def test_seating_csp_specific_seat_constraint(self):
        """Test SPECIFIC_SEAT constraint."""
        layout = self._make_simple_layout()
        participants = [Participant(name="Alice"), Participant(name="Bob")]
        constraints = [
            Constraint(constraint_type=ConstraintType.SPECIFIC_SEAT,
                       participants=["Alice"], seat_id="R2C2"),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()

        assert result is not None
        assert result["Alice"] == "R2C2"

    def test_seating_csp_contradictory_constraints(self):
        """Test detecting contradictory constraints (must + must-not sit together)."""
        layout = GridLayout(rows=1, cols=4)
        participants = [Participant(name="Alice"), Participant(name="Bob")]
        constraints = [
            Constraint(constraint_type=ConstraintType.MUST_SIT_TOGETHER,
                       participants=["Alice", "Bob"]),
            Constraint(constraint_type=ConstraintType.MUST_NOT_SIT_TOGETHER,
                       participants=["Alice", "Bob"]),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()

        assert result is None

    def test_seating_csp_same_group_together(self):
        """Test SAME_GROUP_TOGETHER constraint."""
        layout = GridLayout(rows=1, cols=4)
        participants = [
            Participant(name="Alice", group="Team A"),
            Participant(name="Bob", group="Team A"),
            Participant(name="Carol", group="Team B"),
        ]
        constraints = [
            Constraint(constraint_type=ConstraintType.SAME_GROUP_TOGETHER, group="Team A"),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()

        assert result is not None
        assert layout.are_adjacent(result["Alice"], result["Bob"])


class TestSeatingCSPVerify:
    """Tests for _verify — kept minimal, one per structurally distinct check.

    test_verify_front_row_violation is the most important test in this
    file: it documents that FRONT_ROW constraints are only caught here,
    post-hoc, and never enforced during backtracking search itself.
    """

    def test_verify_front_row_violation(self):
        """Test detecting FRONT_ROW violation."""
        layout = GridLayout(rows=2, cols=2)
        participants = [Participant(name="Alice")]
        constraints = [
            Constraint(constraint_type=ConstraintType.FRONT_ROW, participants=["Alice"]),
        ]
        csp = SeatingCSP(participants, layout, constraints, seed=42)
        assignment = {"Alice": "R2C1"}  # Not front row

        violations = csp._verify(assignment)
        assert len(violations) > 0
        assert "FRONT_ROW" in violations[0]

    def test_verify_must_sit_together_violation(self):
        """Test detecting MUST_SIT_TOGETHER violation."""
        layout = GridLayout(rows=2, cols=2)
        participants = [Participant(name="Alice"), Participant(name="Bob")]
        constraints = [
            Constraint(constraint_type=ConstraintType.MUST_SIT_TOGETHER,
                       participants=["Alice", "Bob"]),
        ]
        csp = SeatingCSP(participants, layout, constraints, seed=42)
        assignment = {"Alice": "R1C1", "Bob": "R2C2"}  # diagonal, not adjacent

        violations = csp._verify(assignment)
        assert len(violations) > 0
        assert "MUST_SIT_TOGETHER" in violations[0]

    def test_verify_same_group_apart_violation(self):
        """Test detecting SAME_GROUP_APART violation."""
        layout = GridLayout(rows=1, cols=3)
        participants = [
            Participant(name="Alice", group="Team A"),
            Participant(name="Bob", group="Team A"),
        ]
        constraints = [
            Constraint(constraint_type=ConstraintType.SAME_GROUP_APART, group="Team A"),
        ]
        csp = SeatingCSP(participants, layout, constraints, seed=42)
        assignment = {"Alice": "R1C1", "Bob": "R1C2"}  # adjacent

        violations = csp._verify(assignment)
        assert len(violations) > 0
        assert "SAME_GROUP_APART" in violations[0]