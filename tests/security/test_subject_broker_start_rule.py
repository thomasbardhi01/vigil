"""Helpers and tests for the subject-broker parallel-calls start/end rule.

Pure functions exercised by a non-docker test (this file).
The docker probe in ``test_subject_broker_docker.py`` imports
``intervals_overlap`` and records per-call start/end events so the
parallel-calls assertion checks non-overlap without any wall-clock bound.
"""

from __future__ import annotations


def intervals_overlap(intervals: list[tuple[int, int]]) -> bool:
    """Return **True** if any two intervals in *intervals* overlap.

    An interval is ``(start, end)`` and two intervals overlap when
    one starts before the other ends (touching at the boundary is
    **not** considered overlapping).
    """
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            si, ei = intervals[i]
            sj, ej = intervals[j]
            if si < ej and sj < ei:
                return True
    return False


def timeout_from_start(start: int, elapsed: int, timeout: int) -> bool:
    """Return **True** if a call that started *start* seconds ago has timed out.

    A call has timed out when *elapsed* strictly exceeds *timeout*.

    This is the fake-clock model used by the parallel-calls test: each
    call records its real start time, and the elapsed time is computed
    from the wall-clock difference at check-out.
    """
    return elapsed > timeout


# ---------------------------------------------------------------------------
# Tests for the helpers
# ---------------------------------------------------------------------------


class TestIntervalsOverlap:
    def test_no_overlap(self) -> None:
        intervals: list[tuple[int, int]] = [(0, 1), (2, 3), (4, 5)]
        assert intervals_overlap(intervals) is False

    def test_two_overlap(self) -> None:
        intervals: list[tuple[int, int]] = [(0, 2), (1, 3)]
        assert intervals_overlap(intervals) is True

    def test_adjacent_no_overlap(self) -> None:
        # touching at boundary is NOT overlapping
        intervals: list[tuple[int, int]] = [(0, 1), (1, 2)]
        assert intervals_overlap(intervals) is False

    def test_three_overlap(self) -> None:
        intervals: list[tuple[int, int]] = [(0, 5), (1, 3), (2, 4)]
        assert intervals_overlap(intervals) is True

    def test_nested_overlap(self) -> None:
        intervals: list[tuple[int, int]] = [(0, 10), (3, 5)]
        assert intervals_overlap(intervals) is True

    def test_empty(self) -> None:
        intervals: list[tuple[int, int]] = []
        assert intervals_overlap(intervals) is False

    def test_single(self) -> None:
        intervals: list[tuple[int, int]] = [(0, 5)]
        assert intervals_overlap(intervals) is False


class TestTimeoutFromStart:
    def test_not_timed_out(self) -> None:
        assert timeout_from_start(0, 1, 5) is False

    def test_timed_out(self) -> None:
        assert timeout_from_start(0, 6, 5) is True

    def test_exactly_at_timeout(self) -> None:
        assert timeout_from_start(0, 5, 5) is False
