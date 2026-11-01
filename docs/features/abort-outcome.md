---
id: abort-outcome
feature: 'Abort outcome (p3-07)'
phase: 'G1'
entry_points: '—'
core_code: '`vigild/jobs/fsm.py`, `prompts/worker.md`'
guardrails: 'Tier pinned. Terminal, reward 0, no tamper flag.'
tests: '`uv run pytest tests/jobs/test_fsm.py -k abort tests/jobs/test_kill_followup.py tests/contract -q`'
status: planned
---
Adds the FSM edge `building -> aborted` as a terminal outcome with reward 0 and no tamper flag, plus one sentence in `prompts/worker.md`. Changes rows `job-state-machine`, `task-contract`, `worker-stop-hook`. Plan item p3-07.
