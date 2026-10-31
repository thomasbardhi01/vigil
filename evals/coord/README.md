# Coord evals (p3-14)

Cases drawn from real coord incidents. Each file in `cases/` is one incident. A
case lists what happened, what coord did, what coord should do, a check a
grader can apply to a coord transcript or its outputs, and the phase-3 item or
PR that prevents it at the system level. The first eight come from the phase-2
close-out retrospective (week of 2026-10-25, closed 2026-10-31, tag `phase-2`).

Front matter keys: `id`, `title`, `date`, `incident` (where it surfaced),
`prevented_by` (issues/PRs), `gate` (phase-3 gate, if any), `status`
(`prevented` when the preventing change has merged, `open` otherwise).

A case is graded on coord behaviour, not on the system: given the same
situation, does coord take the "expected" action and pass the "check"?
