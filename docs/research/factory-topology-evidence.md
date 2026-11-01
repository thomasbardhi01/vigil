# Factory topology: in-house evidence (read-only, gathered 2026-11-01)

In-house evidence for the factory topology and advisor seats research (owner, 2026-11-01; the research plan is `claude/research/factory-topology-research-plan.md` in the owner's project, not in this repo). Feeds experiments #37a and #37b (baselines) and R32 (the advisor reservation's size). Facts only; every number has its query or file beside it.

Sources: `~/vigil-data/vigil.db` (sqlite3 -readonly), `git show origin/main:configs/*.yaml`, `git log origin/main`.

## 1. Jobs, merged PRs and spend by repo since phase 2

**Phase-2 start date used: 2026-10-27.** Basis: `git log origin/main` shows "Phase 2a: the pipeline (#28)" merged 2026-10-27
(plan: docs/plans/phase-2a.md, branch work from 2026-10-23). The repo's first commit is 2026-10-22.
Caveat: the DB's first job is 2026-10-23T20:02Z (pa-0001, a ParkAgent phase-1 run, before 2a merged) and the first
vigil job (vi-0001) has its first event 2026-10-28T00:06Z. Tables below cover the **whole DB** (2026-10-23 to 2026-11-01);
a "since 2026-10-27" cut is given for spend.

### Jobs by repo and final state (bench excluded)
```sql
select repo,state,count(*) from jobs where source!='bench' and provenance!='eval-only' group by 1,2;
```
| repo | merged | abandoned | spec_pending (open) | total |
|---|---|---|---|---|
| thomasbardhi01/vigil | 19 | 10 | 2 | 31 |
| thomasbardhi01/parkagent | 2 | 1 | 0 | 3 |

All 34 jobs have source='human', created 2026-10-23..2026-10-31 (jobs: `select source,count(*),min(created_at),max(created_at) from jobs group by 1`).
Per-day job counts were not queried (gap).

### Merged PRs
```sql
select j.repo, count(*) from jobs j where state='merged' group by 1;                       -- vigil 19, parkagent 2
select json_extract(data,'$.repo'),count(*) from events where type='pr_merged' group by 1;  -- 22 rows, repo field null
```
Job-merged: vigil 19, parkagent 2 (21). The `pr_merged` event count is 22; its data has no repo field, so it is not attributed.
Tasks:
```sql
select j.repo,t.state,t.tier,count(*) from tasks t left join jobs j on j.id=t.job_id group by 1,2,3;
```
| repo | task state | tier | n |
|---|---|---|---|
| vigil | merged | claude-sonnet | 19 |
| vigil | superseded | claude-sonnet | 19 |
| vigil | abandoned | claude-sonnet | 15 |
| vigil | abandoned | claude-opus | 1 |
| vigil | abandoned | local | 1 |
| parkagent | merged | claude-sonnet | 3 |
| parkagent | superseded | claude-sonnet | 1 |

### Metered spend by repo (bench shown separately)
```sql
select coalesce(m.repo,j.repo) r, m.provenance, count(*), round(sum(cost_usd),2), min(substr(ts,1,10)), max(substr(ts,1,10))
from model_calls m left join jobs j on j.id=m.job_id group by 1,2;
```
| repo | provenance | calls | USD | first | last |
|---|---|---|---|---|---|
| vigil | claude | 1677 | 76.53 | 2026-10-28 | 2026-11-01 |
| vigil | local (tower-qwen) | 179 | 0.00 | 2026-10-30 | 2026-10-31 |
| parkagent | claude | 94 | 7.39 | 2026-10-23 | 2026-10-27 |

Total non-bench: $83.92 (`select round(sum(cost_usd),2) from model_calls where provenance!='eval-only'`).
Per day, all rows incl. bench (`group by substr(ts,1,10)`): 10-23 $1.97; 10-26 $1.74; 10-27 $3.68; 10-28 $16.59; 10-29 $21.18; 10-30 $23.91; 10-31 $14.34; 11-01 $1.39.
Since 2026-10-27 inclusive = $81.09 (includes $0.87 bench on 10-29); 10-23 and 10-26 rows ($3.71) are ParkAgent phase-1 runs.

### Presets/models per call, and roles
```sql
select coalesce(m.repo,j.repo), backend_preset, model, purpose, count(*), round(sum(cost_usd),2)
from model_calls m left join jobs j on j.id=m.job_id where m.provenance!='eval-only' group by 1,2,3,4;
select j.repo,s.role,s.backend_preset,count(*),round(sum(s.cost_usd),2)
from sessions s left join jobs j on j.id=s.job_id where s.provenance!='eval-only' group by 1,2,3;
```
Every model_calls row has purpose='session' (no separate purpose for review, audit or decider; role is on `sessions`).
| repo | preset / model | calls | USD |
|---|---|---|---|
| vigil | claude-opus / claude-opus-5-5 | 600 | 46.25 |
| vigil | claude-sonnet / claude-sonnet-5-5 | 1077 | 30.29 |
| vigil | tower-qwen / qwen3.6-35b-a3b | 179 | 0.00 |
| parkagent | claude-opus / claude-opus-5-5 | 53 | 5.80 |
| parkagent | claude-sonnet / claude-sonnet-5-5 | 41 | 1.59 |

Sessions by role, n ($):
| repo | coord | worker | reviewer | auditor |
|---|---|---|---|---|
| vigil | opus 69 ($33.05); sonnet 9 ($1.54) | sonnet 90 ($24.13); opus 1 ($0.63); tower-qwen 11 ($0) | sonnet 53 ($4.62) | opus 50 ($12.57) |
| parkagent | opus 9 ($4.72) | sonnet 6 ($1.14) | sonnet 4 ($0.45) | opus 4 ($1.07) |

Review rungs: reviewer is always claude-sonnet and auditor claude-opus, consistent with rungs 0/1 of configs/review.yaml
(rungs 2/3 use tower-qwen as reviewer; none observed). The `ladder` table (current rung per repo) was not queried (gap).
Task tiers: claude-sonnet (all merged), claude-opus (1 abandoned), local (1 abandoned).

### Bench / eval-only (one line)
```sql
select count(*) from jobs where provenance='eval-only' or source='bench';             -- 0
select count(*),round(sum(cost_usd),2) from model_calls where provenance='eval-only';  -- 11, 0.87
```
Bench: 0 jobs; 11 model_calls, $0.87, all 2026-10-29, repo thomasbardhi01/parkagent, job_id null.

## 2. configs/*.yaml settings per repo (origin/main)

| Setting | File | Current value(s) | Status |
|---|---|---|---|
| `intake` | repos.yaml | parkagent true; vigil absent | varies today |
| `decider` | repos.yaml | both `[haiku, jev]` | varies today (same values) |
| `backends` | repos.yaml | parkagent `[claude-sonnet, claude-opus, claude-haiku]`; vigil adds `tower-qwen` | varies today |
| `worker_overflow` | repos.yaml | both `[]` | varies today |
| `auto_merge` | repos.yaml | both false | varies today |
| `dev_dockerfile` | repos.yaml | images/dev/parkagent.Dockerfile; images/dev/vigil.Dockerfile | varies today |
| `dev_lockfiles`, `dev_suites`, `dev_excluded`, `dev_image_tools`, `runner_config` | repos.yaml | per repo (pnpm/node/prisma/iOS vs uv/pytest) | varies today |
| `ladder_pinned_paths` | repos.yaml | vigil only: vigild/gateway/**, budget.py, metering/**, configs/budgets.yaml, review/ladder.py, docs/owner-rulings.md | varies today |
| `money_paths` | routing.yaml | src/billing/**, src/auth/**, **/payments/**, **/consent/**, **/stripe*, **/wallet/**, fly.toml, *Config.xcconfig (ParkAgent-shaped) | could vary |
| `architecture_labels`, `local_labels`, `xs_labels` | routing.yaml | [architecture, migration]; [tests, docs, deps, lint, copy, ui-small]; [docs, lint] | could vary |
| `coord` rules | routing.yaml | escalation/architecture/pinned/default -> claude-opus; tests-docs and fix S/M -> claude-sonnet | could vary |
| `tiers`, `fallback`, `fallbacks` | routing.yaml | spec->claude-sonnet; local->tower-qwen; fallback claude-sonnet; sonnet<->opus | could vary |
| `escalate_attempt`, `escalate_review_rounds` | routing.yaml | 3; 2 | could vary |
| `reviewer`, `auditor`, `coord_packet` | routing.yaml | claude-sonnet; claude-opus; classic | could vary |
| `shapes` (rung, max_rung) | review.yaml | docs/tests/feature/fix/refactor rung 0; deps rung 1 max 1; money/auth/consent max_rung 0 | could vary (keyed by PR shape) |
| `rungs` | review.yaml | 0,1: sonnet/opus audit 1.00; 2: tower-qwen/sonnet 0.25; 3: tower-qwen/sonnet 0.10 | could vary (state in DB `ladder`) |
| `verify_weight`, `level0_audit_factor`, `local_reviewer_eval` | review.yaml | {0:0.5,1:1.0,3:1.5}; 2.0; null | could vary |
| `wip_per_repo` | budgets.yaml | 4 (name says per repo, one value) | could vary |
| `per_task_usd` | budgets.yaml | 2.00 | could vary |
| `decider_fallback_per_repo_usd` | budgets.yaml | 1.00 | could vary |
| `review_session_usd`, `audit_session_usd`, `hidden_tests_session_usd`, `coord_session_usd`, `decider_call_usd`, `session_max_output_tokens` | budgets.yaml | 0.40; 0.80; 1.00; 2.00; 0.01; 16384 | could vary |
| `daily_usd`, `monthly_usd`, `experiment_monthly_usd`, `bench_task_usd` | budgets.yaml | 25.00; 200.00; 30.00; 1.50 | fleet-wide by nature |
| `scheduler.sessions` | vigild.yaml | 3 (sessions at once, every job) | could vary |
| `scheduler.intake_poll_seconds`, `pr_poll_seconds`, `resume_attempts`, `checkpoint_seconds` | vigild.yaml | 300; 120; 2; 30 | could vary |
| `breakers.repo_failures`, `verifier_unknowns` | vigild.yaml | 3; 3 (counted per repo, one threshold) | could vary |
| `breakers.backend_errors`, `backend_cooldown_seconds`, `max_escalations_per_day` | vigild.yaml | 3; 300; 5 | fleet/backend-wide |
| `container.memory`, `pids_limit`, `uid`, `verifier_memory`, `verifier_concurrency` | vigild.yaml | 4g; 512; 10001; 6g; 1 | could vary (memory, verifier) |
| `fleet_coord` | vigild.yaml | claude-opus | could vary |
| `roles.<role>` egress allow-lists | egress.yaml | coord/reviewer/auditor/hidden_test_author []; worker pypi.org, files.pythonhosted.org; deps adds registry.npmjs.org | could vary (ParkAgent is pnpm; worker list is Python-only) |
| `presets` (`min_task_usd` claude-sonnet 0.60; `live` flags) | backends.yaml | sonnet, opus, haiku, tower-qwen live; tower-fast, openrouter live:false | global; per-repo availability via repos.yaml `backends` |
| `decider_routes` | backends.yaml | haiku, jev-cloudflare, jev-openrouter, lfm-tower | global (jev route by visibility is in code) |
| `hosts[]` memory_gb, cpus, uses | sandbox_hosts.yaml | one host `local`: 11 GB, 8 CPUs, [jobs, bench] | could vary |
| `models` prices | prices.yaml | as_of 2026-10-22 | global |

Not examined: managed-settings.json, otel-collector.yaml.

## 3. Tower admission records since #217

**#217** = commit 437b2ab "Tower dispatch budgets context tokens, not slots; a task too big for the pool routes to the fallback",
merged to origin/main **2026-10-31 10:35 -04:00 (14:35 UTC)**. Touches vigild/scheduler/capacity.py, jobs/runner.py, router/rules.py, db.py.
Predecessor #216 (2026-10-31): dispatch up to llama-server's slot count; context overflow never trips backend_errors.
Tower went live in #68 (2026-10-28).

What the code records (capacity.py on main): `context_budget` events with outcome `queued` or `admitted`
(preset, n_ctx, budget, expected_peak, reserved); `backend_capacity` events (n_ctx, total_slots, ok) on each /props read.

```sql
select type,count(*) from events where type like '%context%' or type like '%slot%' or type like '%admit%'; -- no rows
select substr(ts,1,10),count(*),sum(json_extract(data,'$.ok')),group_concat(distinct json_extract(data,'$.n_ctx')),
  group_concat(distinct json_extract(data,'$.total_slots')) from events where type='backend_capacity' group by 1;
```
- **`context_budget` events: 0 in the production DB.** No tower work has been dispatched since #217: the last
  tower-qwen call was 2026-10-31T13:31:26Z and the last tower-qwen session was created 13:29:17Z, an hour before #217
  merged (`select max(ts) from model_calls where backend_preset='tower-qwen'`). Queue waits and slot use since #217
  are therefore **not recorded** because nothing ran, not because the records are missing.
  The 13 `queued` / 10 `dequeued` events (2026-10-28..30) are budget queues for coord ("3.18 of 5.00 used; 2.00 more"), not tower.
- `backend_capacity`: 25 events, all ok=true, total_slots=4. 10-31: 20 (n_ctx 65536 and 131072 both seen); 11-01: 5 (n_ctx 131072).
  Pool size is recorded; per-session occupancy is not.

Tower usage (`backend_preset='tower-qwen'`):
```sql
select substr(ts,1,10),count(*),count(distinct session_id),round(sum(tokens_in)/1e6,2),max(latency_ms)
from model_calls where backend_preset='tower-qwen' group by 1;
```
| day | calls | sessions | input tokens (M) | max call latency (ms) |
|---|---|---|---|---|
| 2026-10-30 | 79 | 4 | 0.23 | 22570 |
| 2026-10-31 | 100 | 6 | 0.25 | 30682 |
| 2026-11-01 | 0 | 0 | - | - |

Sessions (11 tower-qwen worker sessions in `sessions`; one created 10-29 is `waiting`, never started):
10-30: 4 (failed 1, killed 1, pr_open 2); 10-31: 6 (failed 4, pr_open 2).
Max concurrency: not derivable from a recorded field. `started_at - created_at` is 3-16 s (median 8.5 s, n=10) but that is container
start, **not** a recorded queue wait. Longest worker run 5.7 min.

Refusals:
```sql
select substr(ts,1,10),substr(json_extract(data,'$.reason'),1,60),count(*) from events
where type='gateway_refused' and ts>='2026-10-31' group by 1,2;
```
- 10-31: 25 "tower-qwen: its backend breaker is open"; 8 "session output cap is 16384 tokens per call". 11-01: 3 output-cap.
  (Whole-day counts; not split at the 14:35 UTC merge time.)
- All-time gateway_refused: 66 (10-23:1, 10-28:7, 10-29:15, 10-30:7, 10-31:33, 11-01:3). `breaker` events: 39 (not broken down).
- No dedicated event for "task too big for the pool, routed to fallback"; it may appear in `coord_routed` (56 events), not inspected.

Queue-wait medians/maxima and slot occupancy: **not recorded**.
