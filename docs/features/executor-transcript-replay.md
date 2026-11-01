---
id: executor-transcript-replay
feature: 'Record-and-replay executor transcripts (p3-10)'
phase: 'G2'
entry_points: '—'
core_code: '`tests/executors/test_replay.py`'
guardrails: 'Tier code. Fixtures are redacted NDJSON; a redaction test is required.'
tests: '`uv run pytest tests/executors/test_replay.py -q`'
status: planned
---
Redacted NDJSON executor transcripts are replayed through a fake CLI. Extends row `claude-executor`. Plan item p3-10.
