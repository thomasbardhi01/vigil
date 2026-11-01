# Vigil web UI

The spec for the cockpit (phase 3, v2). vigild serves the UI on Tailscale
only. It is plain HTML, CSS and a little vanilla JS, with no build step, no
framework and no component library. Every number on screen comes from the
same REST API the CLI and the MCP server use (`docs/architecture.md`
decisions `web-ui-stack`, `api-auth`). Owner rulings R3, R17 and R22
(`docs/owner-rulings.md`) fix the page list, the room and the vocabulary.

## Look v2: Sonar, Watch Floor, Industrial

Owner, 2026-10-31. The reference image is
`docs/design/visual-identity-v2.png` (a ChatGPT exploration). Three layers:
*Sonar* is the brand (point clouds, sweeps, reconstruction), *Watch Floor*
is the product (cold control-room telemetry), *Industrial* is the world
around it (factories, shifts, tower, docs imagery). North star: "Nothing
moves unseen."
- There's no chrome, no cards with shadows and no gradients.
- **State is a word plus a glyph, never colour.** There is no red, green
  or yellow anywhere. The mock's BRIEF / CREW / GATE / LANDED chips are
  text in a hairline box, not coloured pills.

### Mark

The geometric V with a radar sweep replaces the character-drawn hat
silhouette.
- It ships as an inline SVG, at most 2 KB, two colours, legible at 16 px as
  the favicon and the terminal icon.
- White appears only in the mark.
- No literal bat imagery.
- The old `assets/mark.txt` hat is retired.

### Palette

These CSS variables are the only colours:

| Variable | Value | Use |
|---|---|---|
| `--void` | `#05080B` | Page. |
| `--graphite` | `#121A22` | Panels; hairlines at 30%. |
| `--steel` | `#364D61` | Idle state, borders, graph bodies. |
| `--sonar` | `#92DDF9` | Detection, attention, the selected row, verification, live activity. Used sparingly. |
| `--signal` | `#EAF6FC` | Primary text. |

- **Needs-you pair:** `--signal` text on a `--steel` background marks
  anything that needs you: cap reached, guard denial, failed, escalated.
- **Contrast is re-measured before the hexes are final.** The needs-you
  pair must pass WCAG AA at 12–13 px, as the 2026-10-22 measurement did for
  the old pair (`--ink` on `#346E93`, 4.69:1). Until that measurement is
  recorded here, the values above are provisional.
- **Borders** are hairlines only. **Corners** are never rounded more than
  2px. **Icons:** none from icon packs.

### Type

- **One heading per page:** wide, tracked uppercase.
- **Data** uses one monospace stack, 12px and 13px:
  `"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace`.
- **No web fonts are downloaded.** A font is used if it's installed, and
  the system font otherwise. That keeps the page weight budget and makes
  no outside requests.

### Imagery

- Renders appear on the landing page, as `/watch`'s ambient background and
  in empty states only.
- They are served from the repo, never fetched, each at most 200 KB. The
  page's data budget is unchanged: under 100 KB before images.
- Operational pages (`/`, `/jobs`, `/job/:id`, `/review`) stay flat: data
  first, atmosphere second.
- Further renders are generated as needed (ChatGPT is fine for source
  art). The repo keeps the files and their prompts.

### Motion

A sonar pulse on a new line, a line scan on a state change, a short
acquisition on verification. Nothing decorative, nothing looping.
`prefers-reduced-motion` turns all of it off.

### Nav labels and vocabulary

Nav labels are the vocabulary (R22); routes are R3's.

| Nav label | Route |
|---|---|
| Watch Floor | `/` |
| Lines | `/jobs` |
| a line | `/job/:id` |
| The Gate | `/review` |
| Factories | `/factories` |
| Crew | `/sessions` (live crew, role prompts linked) |
| Shifts | `/jobs?shift=` |
| Tower | the tower panel on `/budget` and `/sessions` |
| Rulings, Talk | keep their names |

`vigil floor` prints the mock's terminal view (one-screen status).

Vocabulary to visual, one language with each page its own character:

| Word | Looks like |
|---|---|
| watch floor | a wall of live signals |
| line | a signal moving through checkpoints |
| brief | a dossier |
| crew | assigned operators |
| gate | a clearance checkpoint |
| landed | confirmed, archived |
| factories | blueprints |
| shifts | time-coded windows |
| tower | the mast |

**Namespace note** (for the G3 brand card). The exploration found "Vigil
SOC" among unrelated projects using the name. The mark is kept adaptable to
a later master brand while `vigil` and `vigild` stay.

### Character graphs

Every chart and sparkline is text in a `<pre>`, updated live from the
stream. There is no canvas, no SVG and no charting library.

| Graph | Characters | Meaning |
|---|---|---|
| Sparkline | `▁▂▃▄▅▆▇█` | 8 levels, scaled to the window's max; the newest sample on the right |
| Bar | `█▓▒░` | `█` spent or used, `▓` reserved, `▒` the other series, `░` the rest of the cap |
| Timeline | `─┬┴│` | events on a time axis: `┬` starts, `┴` ends, `│` now |
| Meter | `[████████░░░░] 63%` | a block meter for GPU, VRAM, CPU, RAM, W, and tokens against a limit |
| Histogram | `▁…█` columns, one per confidence bucket | decider calibration |

**Live and stale.** Motion follows Look v2: nothing loops.
- While a source is live, the newest column is drawn in `--sonar`, and a
  new sample gets the sonar pulse once.
- A stale source (no sample for 10 s) goes still in `--steel`.
- `prefers-reduced-motion` turns all motion off.
- **The one exception** is `/watch`'s CRT effects (flicker, scanlines,
  beam, glow): on that page only, CSS only, off under
  `prefers-reduced-motion`, and toggled with `f`.

## Behaviour

- **Live data.** There is one stream per page: `GET /api/stream?topics=…`,
  in server-sent events format. The browser's `EventSource` can't send an
  `Authorization` header, so the UI reads the stream with `fetch()` and a
  roughly 30-line line parser. The session cookie rides along with it.
  The UI never polls: a page paints from its GETs once, then the stream
  keeps it current.
- **Stream topics.** A page asks only for the topics it shows:
  - `job` and `job:{id}`: jobs and one job's timeline;
  - `session`: live sessions and heartbeats;
  - `summary`: the header-strip numbers (queue, WIP, $ today, rates);
  - `inbox`: decision cards as they are filed, answered or cleared;
  - `talk:{id}`: one coordinator's thread;
  - new for `/watch` (phase 3): `code`, the active worker's latest edit;
    `events`, every event as it is stored; `tower`, GPU, VRAM, W and slots
    (empty before phase 5).
  - Every event and every `code` payload passes through one redactor,
    `vigild.redact.redact`, the same function the event log and the
    gateway use, before it is stored or published.
- **Login, not a stored token** (P7 is no, owner 2026-10-22). The UI never
  keeps a token, in storage or in page memory:
  - The login form posts the admin (or read) token once to
    `POST /api/login`. vigild answers with a `vigil_session` cookie and the
    page forgets the token.
  - The cookie is a random id, stored hashed in vigild: `HttpOnly`,
    `SameSite=Strict`, `Path=/`, 12 hours, absolute (log in again after).
  - `Secure` is set when the UI is reached over HTTPS through
    `tailscale serve` (`api.cookie_secure: true` in `configs/vigild.yaml`).
    Over plain HTTP on the tailnet it can't be set, because the browser
    would never send the cookie back; the tailnet's WireGuard encryption is
    the transport there.
  - Every write the UI makes carries `X-Vigil-UI: 1`; vigild refuses a
    cookie-authenticated write without it, so a cross-site form can't
    write even if a browser ignored SameSite.
  - On a 401 the UI shows the login form. `POST /api/logout` ends the
    session.
- **Where it's served.** The UI binds to the Mac's Tailscale address only,
  never `0.0.0.0`. The CLI and MCP keep bearer tokens.
- **A live row gets the sonar pulse** in `--sonar` once per update, for 600 ms.
- **Keyboard** (the full map is under `/` Inbox, "Navigation"):
  - `/` focuses the filter; `Esc` clears it.
  - `j` / `k` move the selected row; `Enter` opens it.
  - `g` then a letter jumps to a page; `⌘K` opens the palette.
  - `x` on `/job/:id` asks to kill the running session.
  - On `/job/:id`, `Enter` on a timeline line expands it.
  - `f` on `/watch` (only there) turns the CRT effects on and off; the
    choice isn't saved.
- **Pages, not overlays.** No modals: detail is a page, and expanding a
  timeline line opens it in place.
- **Width.** No page scrolls horizontally at 1280px. Long values (branch
  names, commands) are cut with `…`, and the full text is in the `title`.
- **Page weight** is under 100 KB per page, including the HTML, the CSS,
  every JS module and the mark. A test in `tests/web/` fails over the
  limit.
- **Before phase 5**, tower fields (GPU busy, slots, W, J/token) show
  `—`. They are never hidden, so the layout doesn't move when the tower
  arrives.


## Pages

Eleven pages, and nothing else (R3): ten live pages and `/learn`, which is
planned. `/new` is no longer a page: starting a job is a palette command
(`⌘K`, "new job") that opens the same inline form on the page you are on.
`/decider` is folded into `/factories`. Each page lists the API calls
behind it; the UI calls nothing else. A route marked "(planned, p3-nn)" is
not in the code yet. A **job** is the UI's word for a task (the API says
`tasks`): one contract, and every session (attempt, review, audit) it has
spawned.

| Page | Content | Primary actions | Reads |
|---|---|---|---|
| `/` Inbox | levels 1–4 across projects | answer card `1–4`, `o` override, `r` make rule, `s` settle, `h` snooze, `u` undo | `GET /api/inbox`, `GET /api/tasks`, `GET /api/cards` (planned, p3-17); stream `inbox`, `job`, `summary` |
| `/jobs` | the Board table, grouped by state; facets project, factory, origin | filter, open | `GET /api/jobs` |
| `/job/:id` | tree brief → coord → workers → reviewer → auditor; timeline; verdict; packet layers and dropped items; evidence bundle; PR rail with diff; `verified_sha` against head | kill, retry with reason, open on GitHub | `GET /api/jobs/{id}`, `/tree` |
| `/review` | ready-to-merge queue; the ladder | open on GitHub to merge | `GET /api/review/ladder`, `GET /api/landing` (planned, p3-09) |
| `/factories` | factory configs, scoreboard, rung per shape, decider calibration and labels | propose config change (draft PR); label a decision | `GET /api/metrics` (planned, p3-19), `GET /api/decider/report` |
| `/budget` | two meters, per-task cost, most-expensive list | none (caps change only by PR) | `GET /api/usage` (planned, p3-03, p3-60) |
| `/rulings` | every ruling with source card, status, draft PR, last cited | retire (draft PR) | `GET /api/rulings` (planned, p3-17) |
| `/sessions` | live sessions, heartbeats, container IDs | kill | `GET /api/sessions` |
| `/talk` | advisor and coord threads, brief cards inline | propose brief (advisor); approval only in the Inbox | see `/talk` |
| `/watch` | unchanged | none | see `/watch` |
| `/learn` | planned | none | none |

Primary actions that write go through the card or job routes the CLI uses.
The UI never merges.

### Information hierarchy on every page

1. **Header strip.** API $ today against pacing and the month; the
   subscription window with `resets_at`, or `unavailable`; breakers; queue
   depth; WIP per repo (`parkagent 2/4`); verifier wait. Tower fields
   (GPU busy, slots) show `—` before phase 5.
2. **Needs you.** Typed cards, sticky, FIFO within a kind, in the order
   page, breaker, brief or spec, ready-to-merge, question.
3. **In flight.** One line per job, grouped by state.
4. **Settled.** Counts only, expandable. Older settled items show as an
   `olderSettled` count.

Dollar figures read `$x.xx / $25.00`: the day cap is pacing only. The task
cap is $2 and the month cap is $200 (`configs/budgets.yaml`); all are hard
stops, and the UI shows them read-only.

### 1. `/`: Inbox (Watch Floor)

The home view: every running line and everything waiting on you, across
projects, in the four levels above.

**Decision card anatomy.**
- A one-line question naming the blocker.
- Two to four options, the recommended one marked, with a one-line
  rationale carrying its confidence.
- A free-text override.
- A scope selector: this run, this task, this factory, standing rule. A
  standing rule opens a draft PR to `docs/owner-rulings.md`.
- Evidence links: verdict, diff stat, cost, evidence bundle.
- An auto-clear condition.
- A `blocking` bit. A non-blocking question lets the run continue.
- Batch cards from one brief ("approve 3 specs": approve all, or review
  each).

**Card budget.** At most 10 cards a day. A breach is a weekly finding that
names the ruling which would have prevented it.

**Notifications** go out only for pages, breakers, and blocking cards older
than 30 minutes. Never on a finished turn.

**Reversibility.** Settle, snooze and pin each have a reverse (`u`). A
one-way door is a bug.

**Navigation.**
- `g i`, `g j`, `g r`, `g f`, `g b`, `g u` jump to Inbox, Jobs, Review,
  Factories, Budget, and the rulings page.
- `j` / `k` move; `Enter` opens; `Esc` closes; `/` filters.
- `⌘K` opens a palette over jobs, PRs, rulings, factories and commands,
  including settled and archived items. An ambiguous ID is rejected.
- Hover shows a preview card, not a pane.

**Density.**
- One line per job, at most 7 columns: id, project, state glyph and word,
  blocker or next step, verdict, `$` or window, age.
- State is a word plus a glyph, never colour.
- "Done" means the verifier's verdict.
- Numbers are right-aligned and tabular, and come from the gateway meter
  only.

**Mobile.** The "Needs you" level is served responsively over Tailscale.
Diff review, merge, budget edits and secrets are never on the phone.

**One app.**
- Primary: ideate in the Claude app through the MCP facade (read, and
  `propose_brief`); run the coord in Claude Code with Remote Control;
  approve on the Inbox over the tailnet.
- Fallback, when Claude is unavailable or for other people's stacks: the
  advisor lane in `/talk`, on an OpenRouter or tower model, with the same
  facade and the same scope.
- Claude Duet (Opus-only, waitlist, checks every few hours) and Claude Tag
  (Team and Enterprise Slack) are not control planes.

**Done when:** a seeded blocking card shows under Needs you with its
recommended option, `1` answers it, `u` undoes it, and the job moves to
In flight without a reload.

### 2. `/jobs`: Lines

The Board table: every job, grouped by state, with facets for project,
factory and origin. A `?shift=` filter shows one batch or overnight run.
Columns:
- id, repo, branch;
- tier, backend, state;
- turns, elapsed;
- tokens in/out, `$` or GPU-s;
- PR, CI, review rung, trace link (Phoenix).

- **Risk and readiness** (planned, Stage A, `docs/design.md` "Factory
  engineering"): the PR's merge-risk grade (`low`, `med`, `HIGH`) and, when
  the PR is UI-shaped and has neither a recording nor a before/after
  screenshot pair, `not ready for review`. Both are read from artifact
  rows. Neither is a gate, and neither changes a CI or review column.
  `not ready for review` reads the Evidence cell's `rec` mark and does not
  repeat it. The Evidence cell also carries the diagram mark, `diag`
  (`made`, `skipped` or `pending`), with its skip reason on hover.

Typing filters the table. `Enter` opens `/job/:id`.

**API:** `GET /api/jobs`, and the stream's `job` and `summary` topics.

**Done when:** a job started from the CLI shows on `/jobs` in its state's
group within a second of the transition.

### 3. `/job/:id`: a line

Three columns.

- **Left:**
  - the contract: goal, `test_cmd`, `done_when`, files in scope, out of
    scope;
  - limits;
  - `tier_reason`;
  - backend;
  - why, value and risk;
  - the decider's answers, each with its confidence and which backend
    answered.
- **Centre:** the live timeline, newest at the bottom, one line per
  event:
  - a model request, with model, tokens in/out/cache and latency;
  - a tool call, with its command or path;
  - a permission decision (allowed or denied, and by which layer);
  - a review finding;
  - a state change.

  Each line expands to full content.
- **Right:** meters for this job.
  - Tokens and cost against its cap.
  - GPU, CPU, RAM and W as per-second character sparklines.
  - J/token and GPU-s/token.
  - A link to the Phoenix trace.
- **Tree and verdict.** Above the timeline: the tree brief, coord,
  workers, reviewer, auditor; the verifier verdict; the packet layers and
  dropped items (p3-50); the evidence bundle.
- **PR rail.** The PR with its diff, and `verified_sha` against the PR
  head. A head that differs from `verified_sha` shows `stale`.
- **PR header** (planned, Stage A): the merge-risk grade beside the PR
  link, with its signals one line each: blast radius (the sensitive paths
  hit), rollback cost (migration, down step, schema or API change),
  swallowed errors (`not measured` until semgrep's false-positive rate is
  known) and the reviewer's alignment and drive-by input. A `HIGH` grade
  shows `owner look required`. It never shows a rung lower than the
  ladder's, and it is advisory. Below it, the PR footer's `vigil:`
  references (spec, plan, event-log range, gate digest, hidden-test
  categories, cost), each `made`, `pending` or `skipped`.
- **Kill.** `x` puts an inline line under the header: `kill pa-0142? y/n`.
  `y` stops the running job (`POST /api/jobs/{id}/kill`), the same call as
  `vigil kill`.
- **Retry with reason** takes a one-line reason, recorded on the event.

**API:**
- `GET /api/jobs/{id}` and `GET /api/jobs/{id}/tree`
- `GET /api/tasks/{id}`
- the timeline's paged events and one event's full content (planned,
  phase 3)
- `POST /api/jobs/{id}/kill`
- the stream's `job:{id}` topic

**Done when:** a finished job's timeline shows each model call, the
per-call costs sum to the job total within a cent, and the PR rail shows
`verified_sha == head`.

### 4. `/review`: The Gate

- **Ready-to-merge queue.** Verdict first, then findings by severity, the
  diff stat and a `verified_sha == head` badge. The owner opens the PR on
  GitHub to merge; the page has no merge button.
- **The trust ladder** (unchanged). For each task shape:
  - its rung, its starting rung and its limit (and why it stops there);
  - who reviews and who audits at that rung, and the audit rate;
  - a sparkline of the audit match rate;
  - false findings per PR;
  - its **last change**: old and new rung, the reason, the audit sample
    size and match rate behind it, and when (owner, 2026-10-23); the full
    history of promotions and demotions below it.

Money, auth and consent shapes are marked `rung 0 · fixed`, deps
`rung ≤ 1 · fixed`. Until a local reviewer passes its eval, the page says
so: no shape passes rung 1.

**API:** `GET /api/review/ladder`; the queue's `GET /api/landing`
(planned, p3-09).

**Done when:** a PR whose head differs from `verified_sha` shows as not
ready, and every shape shows its rung and last change.

### 5. `/factories`

Absorbs `/decider`.
- **Factory configs** and the scoreboard: a Pareto view per (model,
  harness, template).
- **Rung per shape**, read from the ladder.
- **Decider.** Every question asked today:
  - the question, and an excerpt of the state it was asked about;
  - the answer and its confidence, and the backend that answered;
  - what vigild did: acted, escalated, or waited;
  - agreement with your later label.
- **Labels** are set inline on the row: `l` opens a select in place, and
  `Enter` saves it. The CLI does the same with
  `vigil label <decision> <answer>`. The eval reads these labels.
- **Calibration:** a character histogram per backend, accuracy per
  confidence bucket against your labels.
- **Propose config change** opens a draft PR; the page never edits a
  config.

**API:** `GET /api/decider/report`; `GET /api/metrics` (planned, p3-19);
labels via `POST /api/decisions/{id}/label` (planned, phase 3).

**Done when:** a decision labelled inline shows in the calibration
histogram, and a proposed change appears as a draft PR.

### 6. `/budget`

- **Two meters on one row.**
  - API dollars, by the gateway: today against `$25.00` (pacing only),
    the month against `$200`, open reservations. Per day for the last 30
    days as character bars (`█` spent, `▓` reserved, `░` remaining).
  - The subscription window, by `usage_readings`, with its `stale_at`.
- **Per-task cost** per triple, and the most-expensive list.
- **WIP limits** per repo, with the open fleet PRs.
- **Tower panel** (`—` before phase 5).
- **Experiment line** (planned, Stage B, `docs/design.md` "Factory
  engineering"): the monthly experiment budget (proposed `$20`) as spent,
  reserved and remaining, split into task validation, experiment design and
  analysis review, scorer samples and proposal comparisons. It counts inside
  the month and never inside today's bar. Local arms cost `$0` and are not
  drawn. Greyed until 30 validated benchmark tasks.
- **Cost per merged PR** beside the caps, over 30 days, by shape and route,
  with the experiment line shown apart from it. Greyed until 10 merged PRs.
- Caps are read-only here. They live in `configs/budgets.yaml`, the same
  for every interface, and change only by PR.

**API:** `GET /api/usage` (planned, p3-03, p3-60); the stream's `summary` topic.

**Done when:** today's spend on the page equals the gateway's metered sum,
and the subscription meter reads `unavailable` when its reading is stale.

### 7. `/rulings`

Takes `/new`'s slot (R3). Every owner ruling, as indexed from
`docs/owner-rulings.md`:
- the ruling and its source card;
- its status;
- its draft PR, if one is open;
- when it was last cited.

**Retire** opens a draft PR that removes the ruling; the page edits
nothing itself.

**API:** `GET /api/rulings`, `POST /api/rulings/{id}/draft` (both planned,
p3-02).

**Done when:** a ruling made through a card's "standing rule" scope shows
here with its draft PR.

### 8. `/sessions`: Crew

Every live session Vigil knows about, each with what it is doing right
now, its last tool call and its container ID:
- vigil workers, reviewers and auditors, with their role prompts linked;
- any outside session that registers through the opt-in heartbeat
  endpoint, such as vigil-coord, or ParkAgent's coord if you wire it.

**Heartbeats.**
- **Endpoint:** `POST /api/heartbeat` (planned, phase 3) with
  `{name, repo, branch, doing, last_tool, at}`.
- **Token:** the heartbeat-scoped `VIGIL_HEARTBEAT_TOKEN`, which can
  write heartbeats and nothing else.
- **Expiry:** a heartbeat expires after 5 minutes.
- **Docs:** the phase 3 PR adds a "Heartbeats" section to the runbook.
- **Opt-in:** coord never adds it to ParkAgent; you do, if you want it.

**Kill** stops a session after the inline `y/n` line.

**API:** `GET /api/sessions`, `GET /api/heartbeats` (planned, phase 3), and
the stream's `session` topic.

**Done when:** a started worker appears with its last tool call within a
second, and a heartbeat disappears after 5 minutes.

### 9. `/talk`

A conversation with a coordinator (R17). One chat component, two lanes:
- **Coord lane:** a Claude Code session vigild launches through the Agent
  SDK (p3-52), streamed through the session proxy.
- **Advisor lane:** any model through the gateway (Claude API, OpenRouter,
  tower), with the facade's tools and the advisor scope.

The page is the web client of the bridge (`docs/design.md`, "Talking to
coordinators from anywhere").
- **Left:** the coordinators, each with its job and current backend.
- **Centre:** the thread, newest at the bottom.
  - Your messages are marked `human · web`.
  - Messages relayed from Claude or a local chat show their channel and
    relay model.
  - Brief cards render inline. A send box sits under the thread.
- **Backend switch:** a select above the thread.
  - Switching starts a fresh session on the new backend, with the thread
    as context, and the switch shows as a line in the thread.
  - A local backend is offered only for shapes at trust rung 3.
- **A conversation surface, not a decision surface.** The advisor can
  propose a brief. Nothing on `/talk` approves, merges, or dispatches;
  approval happens only in the Inbox. When a coord needs a decision, it
  files an inbox item, and the thread shows a link to it.

**API:** `GET /api/briefs`, `POST /api/briefs` (planned, p3-04);
`GET /api/coords`, `GET /api/coords/{id}/thread`,
`POST /api/coords/{id}/messages`, `POST /api/coords/{id}/backend` (planned,
phase 3); and the stream's `talk:{id}` topic.

**Done when:** a brief proposed in the advisor lane appears as an inbox
card, and the lane keeps working on an OpenRouter preset with Claude
unavailable.

### 10. `/watch`: Watch

Unchanged by v2, apart from the new ambient background (Imagery). A
full-screen ambient display, made to be left open on a screen. The page
fills the viewport and has no nav chrome. Going fullscreen is the
browser's own control: the page never calls the Fullscreen API.

**Layout.** A 12-column pane grid. No horizontal scroll at 1280px, and it
reads well at 1920px and wider (the panes grow; the type doesn't).

| Row | Panes (column span) |
|---|---|
| 1–2 | Live code stream (8, two rows tall) · Throughput (4) · Funnel (4) |
| 3 | Cost burn (4) · Tower meters (4) · Sessions (4) |
| 4 | Quality strip (12) |
| 5 | Event log (12) |

**Panes:**
- **Live code stream:** the active worker's latest edit, from the
  session proxy (phase 2), with its repo, file path and worker id. It is
  redacted on the server by `vigild.redact.redact`, the one redactor the
  event log and the gateway use, before it enters the stream. With no
  active worker, the last edit stays, in `--steel`.
- **Throughput:** jobs started and finished, and PRs opened and merged,
  per hour, as sparklines.
- **Funnel:** the count of jobs in each state, `spec_pending` through
  `done`, as bars.
- **Cost burn:** $ per hour, and today against the daily cap as a bar.
- **Tower meters:** GPU, VRAM, W and slots; `—` before phase 5, as
  everywhere.
- **Sessions:** a compact `/sessions`: one line per live session.
- **Quality strip:** the KPIs: first-pass merge rate, findings per PR by
  severity, revert + fix-job rate, cost per merged PR, median spec→merge.
- **Event log:** a tail of the event stream.

**CRT effects** (flicker, scanlines, beam, glow), on this page only:
- CSS only: no `<canvas>`, no SVG, no library, as everywhere.
- Off under `prefers-reduced-motion`.
- `f` toggles them; the toggle isn't saved.

**API:** the same API as every page. First paint from the summary, jobs,
sessions and budget reads; then one stream,
`GET /api/stream?topics=code,summary,session,events,tower` (planned, phase
3). No polling. The 100 KB page-weight limit applies.

**Depends on:** the phase 2 session proxy (the code stream) and phase 2
review data (the quality strip's findings); tower meters wait for phase 5.

**Done when:** `tests/web/test_watch.py` passes (see "Done when (phase 3)").

### 11. `/learn` (planned)

The owner's request names a Learn screen (owner ruling, 2026-10-23). It
reads and never writes policy.

**Greyed until the count is reached.** Every block below declares the run
count it needs (`docs/design.md` "Factory engineering"). Until then it shows
its name, the count needed and the count held (`merged 12 / 30`), and no
number or chart.

- **Stage A, from the first merged PRs:**
  - cost per merged PR (10 merged PRs);
  - autonomy rate: merged PRs with no owner code push (10);
  - human touches per PR: steers, takeovers, escalations answered, review
    overrides (10);
  - time from PR open to first owner review, and from open to merge (10);
  - 14-day revert rate (10 PRs at least 14 days old);
  - auditor-confirmed finding rate, random audit sample only (20 audited
    reviews).

  Each is a 30-day character sparkline with its latest value.
- **Stage B, 30 validated benchmark tasks in the repo:**
  - **Pareto view.** Cost on one axis and quality on the other, one point
    per named benchmark config, the non-dominated points joined and
    dominated ones dimmed. Each point carries its *n* and interval; a shape
    under 8 tasks reads `insufficient n` and is not ranked. The reference
    arm (the original merged run) is marked and is not a paired comparison.
    Results are split by whether a task is dated after the model's training
    cutoff. A job whose hidden tests were shown to a model reads `exposed`
    and is not plotted.
  - **Scorers.** Each scorer with its agreement over its owner-labelled
    runs (`n/30` until 30, then the rate). Below 30 labels or 80% it reads
    `uncalibrated` and none of its trends is drawn. The owner labels a run
    here.
- **Stage C, 60 merged Vigil jobs in the repo or the owner's switch:** open
  improvement-proposal PRs with the runs they cite and their replay
  comparison.

**API (planned, phase 3):** `GET /api/metrics`, `GET /api/benchmarks`,
`GET /api/scorers`, `POST /api/scorers/{id}/labels`.

**Done when:** every block shows its held-against-needed count, and none
shows a number below its count.

## Files

```text
vigild/web/
  index.html        one shell; routes by path
  app.css           the palette, type and hairlines; nothing else
  js/api.js         fetch (session cookie, X-Vigil-UI on writes) + stream reader
  js/glyphs.js      sparkline, bar, timeline, meter, histogram as pure functions over numbers → strings
  js/keys.js        / j k Enter Esc g ⌘K l, and f on /watch
  js/pages/*.js     one module per page
  assets/mark.svg   the V mark, inline in the shell and used as the favicon
  assets/img/*      renders (landing, /watch, empty states), each ≤200 KB
```

`glyphs.js` is pure and unit-tested: the same numbers always give the same
string.

## Done when (phase 3)

- A job started from the palette shows live on `/` and `/jobs`.
- Its `/job/:id` timeline shows each model call. The per-call costs sum
  to the job total within a cent.
- `/metrics` shows its counters.
- Each page is under 100 KB before images, with no horizontal scroll at
  1280px.
- `/`, `j`, `k`, `g`, `⌘K` and `Enter` work.
- The PR includes a screenshot of each of the eleven pages (`/learn`
  greyed).
- `/watch` (`tests/web/test_watch.py`):
  - a secret-shaped string planted in a worker's edit never reaches the
    `code` topic;
  - under `prefers-reduced-motion` the CRT effects are off;
  - after first paint the page makes no request but its one stream (no
    polling).
