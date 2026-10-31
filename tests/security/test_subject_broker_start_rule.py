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


def timeout_from_start(current_time: int, start: int, timeout: int) -> bool:
    """Return **True** if a call that started at *start* has timed out at *current_time*.

    A call has timed out when the time since it started strictly exceeds *timeout*.

    This is the fake-clock model used by the parallel-calls test: each
    call's timeout counts from when it starts running, not from when it
    was queued.  The ``start`` parameter is the real start time; the
    elapsed time is derived from it.
    """
    return (current_time - start) > timeout


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
        assert timeout_from_start(current_time=5, start=4, timeout=5) is False

    def test_timed_out(self) -> None:
        assert timeout_from_start(current_time=11, start=5, timeout=5) is True

    def test_exactly_at_timeout(self) -> None:
        assert timeout_from_start(current_time=10, start=5, timeout=5) is False


class TestTimeoutFromStartFakeClock:
    """AC2: a call's timeout counts from when it starts running, not when it was queued."""

    def test_queued_longer_than_timeout_still_succeeds(self) -> None:
        """Call 2 is queued for 9 s (behind 3 calls of 3 s each) but its own
        timeout of 3 s is measured from when it starts; it runs for 3 s, so it
        has *not* timed out (3 > 3 is False)."""
        call_start = 9  # call starts after 3 earlier calls * 3 s each
        current = 12  # 3 s of execution have elapsed since the call started
        timeout = 3
        assert timeout_from_start(current_time=current, start=call_start, timeout=timeout) is False

    def test_call_times_out_during_execution(self) -> None:
        """Call starts at t=0, runs for 4 s with timeout=3 → timed out."""
        assert timeout_from_start(current_time=4, start=0, timeout=3) is True

    def test_call_with_zero_wait(self) -> None:
        """Call runs immediately from t=0 for 2 s with timeout=5 → not timed out."""
        assert timeout_from_start(current_time=2, start=0, timeout=5) is False

    def test_call_with_zero_elapsed(self) -> None:
        """Call has just started; elapsed is 0, so never timed out."""
        assert timeout_from_start(current_time=5, start=5, timeout=3) is False
