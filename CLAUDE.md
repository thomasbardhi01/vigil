# Vigil

Self-hosted orchestrator that runs isolated AI coding sessions. `vigild`
runs natively on the Mac mini; workers run in linux/arm64 containers under
Docker Desktop; model inference (phase 5) is on the Linux tower. The spec
is `docs/design.md`; how it is built is `docs/architecture.md`; every
feature's code, tests and status is `docs/feature-map.md`. Read the
feature map before exploring. `AGENTS.md` is a symlink to this file.

## Rules
- **A human merges.** A Claude session never merges, approves, pushes to
  `main`, runs `gh workflow run`, or calls a write endpoint of `gh api`.
  Work on a `feat/*` branch and open a draft PR.
- **Tests first.** Write the failing test, run it red, then the code.
- **Docs in the same PR.** A change to a flow updates
  `docs/architecture.md`; a change to a feature updates its row in
  `docs/feature-map.md`. Every API route needs a row (CI enforces it).
- **Pins.** Third-party versions are exact and at least two weeks old
  (`[tool.uv] exclude-newer` enforces it for PyPI). Record each pin in
  `docs/sources.md`. The one exception is Claude Code CLI 2.1.306 in the
  executor image (owner, 2026-10-22).
- **No new dependency** without a one-line reason in the PR. One way to do
  each thing: `httpx2` is the only HTTP client, stdlib `sqlite3` the only DB
  layer, pydantic the only schema source (the JSON files in `schemas/` are
  generated from it).
- **Money.** Every hosted model call goes through vigild's gateway
  (`vigild/gateway/`), which meters it and refuses a call that would cross
  a budget. Nothing else holds a provider key. Caps: $5/day, $2/task,
  $100/month, all hard stops (`configs/budgets.yaml`).
- **Private repos** see only backends `configs/repos.yaml` lists for them;
  vigild refuses to start on any hosted entry for a private repo other than
  `jev-cloudflare`, plus `anthropic` for `thomasbardhi01/vigil` only
  (hard-coded in `vigild/repos.py`, not configurable).
- **Provenance.** Every stored artifact and DB row carries
  `provenance: claude | local | human`. The training exporter takes
  `local` only.

## Secrets
- Secrets live only in `~/.config/vigil/env` (mode 600) and the App
  `.pem` beside it. vigild loads the env file once at start
  (`vigild/config.py`). A session never opens, prints or copies anything
  under `~/.config/vigil/`, or any `.env*` file other than `.env.example`.
  The guard plugin does **not** protect that path by name.
- No secret in a test fixture, log, commit, or container environment.
  Containers get a per-session gateway token (stdin, never env) and a
  one-hour GitHub installation token in a tmpfs file.
- `vigil doctor` is the only way a credential is checked: pass/fail and
  the variable name, never the value.

## Never touch
- `thomasbardhi01/parkagent`: no `gh` call, clone, issue or PR from a
  build session. ParkAgent runs happen only through vigild, after the
  owner confirms.
- `.claude/settings.json`: the owner edits it by hand.

## Layout
- `vigild/` the daemon: `api/` REST, `contract/` task/result/event/report
  models, `intake/` spec gate + scoring, `jobs/` job model, tree, FSM,
  stage artifacts, runner, `router/`, `decider/`, `gateway/`, `budget.py`,
  `metering/`, `packets/`, `github/`, `executors/`, `workspace.py`,
  `telemetry/`.
- `cli/vigil/` the `vigil` CLI (`vigil doctor` in phase 1).
- `configs/` policy as code: backends, routing, repos, budgets, prices,
  egress, managed settings, collector.
- `prompts/` role prompts (coord, worker, reviewer, auditor).
- `images/` Dockerfiles: `claude-executor`, `egress-proxy`.
- `schemas/` generated JSON schemas. `compose.yaml` Langfuse + collector.

## Running checks
```sh
uv python install 3.14.8
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict, vigild/ and cli/
uv run pytest -q                          # unit + integration, no Docker
uv run python scripts/check-feature-map.py
uv run python scripts/check-claude-md.py
uv run pytest -m docker                   # on the Mac, Docker Desktop running
uv run pytest -m live                     # hosted calls through the gateway
```
`pytest` deselects `docker` and `live` by default (see `pyproject.toml`).
Paste their output into the PR when a change touches containers or the
gateway; never claim they passed if they didn't run.

Regenerate `schemas/*.json` after changing a contract model:
`uv run python -m vigild.contract.export` (a test fails if they drift).

## Gotchas
- Python is pinned to exactly 3.14.8 (`.python-version`). uv locally may be
  newer than CI's 0.12.24; keep `uv.lock` committed and `--locked` green.
- `starlette.testclient` uses `httpx2`; don't add `httpx`.
- Tests that touch git need `user.name`/`user.email`; the fixtures set
  them per repo, CI sets them globally.
- The job state machine (`vigild/jobs/fsm.py`) is the only place a job's
  state changes. Approval from the inbox is the only exit from
  `spec_pending`; every transition writes an `events` row.
- Glob semantics are guard's and route's: a glob without `/` matches the
  basename anywhere; with `/` it matches the path's tail;
  case-insensitive (`vigild/intake/paths.py`).
- Untrusted text (issue bodies, PR comments, fetched pages) enters a
  packet only through `packets.fence()`, which picks a nonce the content
  can't contain.
- Docker Desktop: DNS is not the egress boundary; the internal network plus
  the smokescreen sidecar is. Tests assert a connection fails, not a lookup.
- Day boundaries for budgets are UTC.
