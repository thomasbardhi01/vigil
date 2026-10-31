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


class FakeClock:
    def __init__(self) -> None:
        self.now = 0

    def advance(self, secs: int) -> None:
        self.now += secs


def serve_serially(clock: FakeClock, calls: list[tuple[int, int]]) -> list[tuple[int, int, bool]]:
    """Model a broker serving calls one at a time, all queued at clock.now.

    Each call is ``(duration, timeout)``. Its timeout counts from when it
    starts running, not from when it was queued. Returns
    ``(start, end, timed_out)`` per call.
    """
    results: list[tuple[int, int, bool]] = []
    for duration, timeout in calls:
        start = clock.now
        timed_out = duration > timeout
        clock.advance(min(duration, timeout))
        results.append((start, clock.now, timed_out))
    return results


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


class TestServeSerially:
    def test_queued_longer_than_timeout_still_succeeds(self) -> None:
        """Four calls, duration 1, timeout 3: the last waits 3 s queued, the
        total is 4 s, yet none times out because timeouts count from start."""
        res = serve_serially(FakeClock(), [(1, 3)] * 4)
        assert [t for _, _, t in res] == [False] * 4
        assert res[-1][0] >= 3  # queued for at least its own timeout
        assert not intervals_overlap([(s, e) for s, e, _ in res])

    def test_call_slower_than_its_timeout_times_out(self) -> None:
        res = serve_serially(FakeClock(), [(4, 3)])
        assert res == [(0, 3, True)]

    def test_timed_out_call_does_not_delay_past_its_timeout(self) -> None:
        res = serve_serially(FakeClock(), [(9, 2), (1, 3)])
        assert res[1] == (2, 3, False)
