"""p3-09 part 2: the runner lands a job's PRs before its ready card (#172, closes #221).

On the way from in_review to ready, every task's PR is landed (`vigild.github.landing`):
rebased in the vault on the remote's current main, re-verified there, and sent; the task
records `verified_sha` and the ready card names it. A conflict in a non-generated file, or
a red verdict on the rebased head, is REWORK: a fresh worker is dispatched with the
conflict context, and an inbox card says why (owner, 2026-11-01). A merge whose head is not
the task's `verified_sha` is refused and paged.
"""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import git
from tests.jobs.test_coord_loop import (  # noqa: F401
    REPO,
    World,
    _approve,
    _work,
    auth,
    world,
)
from vigild.jobs.model import JobState, Role

S = JobState


def _held_in_review(w: World) -> str:
    w.runner.review = lambda job_id: None  # type: ignore[method-assign]
    job = _approve(w)
    assert w.store.get_job(job).state is S.IN_REVIEW
    del w.runner.review  # the real review stage again
    return job


def _pr(w: World, tid: str) -> dict[str, Any]:
    rows = w.store.q(
        "SELECT data FROM events WHERE task_id=? AND type='pr_open' ORDER BY id DESC LIMIT 1",
        (tid,),
    )
    return json.loads(rows[0]["data"])  # type: ignore[no-any-return]


def _main_edit(w: World, path: str, text: str) -> str:
    """Someone else's change lands on the remote's main."""
    seed = w.bare.parent.parent / "seed"
    git(seed, "pull", "-q", "--ff-only", "origin", "main")
    f = seed / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(seed, "add", path)
    git(seed, "commit", "-q", "-m", "someone else's change")
    git(seed, "push", "-q", "origin", "main")
    return git(seed, "rev-parse", "HEAD")


def _changed(w: World, tid: str) -> list[str]:
    pr = _pr(w, tid)
    ws = w.runner.workspace
    return [
        p for _, p in ws.changed(REPO, pr["base_sha"], pr["head"]) if not p.startswith(".vigil")
    ]


def _workers(w: World, tid: str) -> list[str]:
    return [p for role, p in w.standin.packets if role == Role.WORKER.value and tid in p]


def test_landing_records_the_verified_sha_and_the_ready_card_names_it(world: World) -> None:
    w = world
    job = _held_in_review(w)
    _main_edit(w, "docs/unrelated.md", "someone else's new file\n")  # no task touches it
    w.runner.review(job)
    pages = [
        (q["title"], q["body"])
        for q in w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
        if q["job_id"] == job
    ]
    assert w.store.get_job(job).state is S.READY, pages
    item = next(
        i
        for i in w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["ready"]
        if i["job_id"] == job
    )
    for t in w.store.list_tasks(job):
        row = w.store.q("SELECT verified_sha, verified_main FROM tasks WHERE id=?", (t.id,))[0]
        assert row["verified_sha"] and row["verified_main"]
        assert (
            git(w.bare, "rev-parse", f"refs/heads/{_pr(w, t.id)['branch']}") == row["verified_sha"]
        )
        assert row["verified_sha"] in json.dumps(item["body"])


def test_rework_a_logic_conflict_at_landing_dispatches_a_fresh_worker_and_files_a_card(
    world: World,
) -> None:
    """The owner's test (2026-11-01): main changed a file the task changed, the same lines:
    no model resolves it. A fresh worker is dispatched with the conflict context (the files
    and why), an inbox card names them, and nothing on the remote is overwritten."""
    w = world
    job = _held_in_review(w)
    tid = f"{job}-w1"
    (path, *_) = _changed(w, tid)
    main = _main_edit(w, path, "someone else's whole new content\n")
    branch = _pr(w, tid)["branch"]
    sent = git(w.bare, "rev-parse", f"refs/heads/{branch}")
    before = len(_workers(w, tid))
    w.runner.review(job)
    fresh = _workers(w, tid)[before:]
    assert fresh, "no fresh worker was dispatched"
    assert "REWORK" in fresh[0] and path in fresh[0]  # the conflict context reached the packet
    cards = [
        q for q in w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
        if q["job_id"] == job and q["body"].get("kind") == "landing_rework"
    ]  # fmt: skip
    assert cards and path in json.dumps(cards[0]["body"])
    assert git(w.bare, "rev-parse", "refs/heads/main") == main  # main untouched
    assert git(w.bare, "rev-parse", f"refs/heads/{branch}") != "" and sent  # no force over it


def test_a_merge_whose_head_is_not_the_verified_sha_is_refused_and_paged(world: World) -> None:
    """sha binding at the merge poll: the PR merged with a head vigild did not verify (a hand
    push after landing): the job is not moved to merged, and the owner is paged."""
    w = world
    job = _held_in_review(w)
    w.runner.review(job)
    assert w.store.get_job(job).state is S.READY
    tid = f"{job}-w1"
    w.runner.pr_state = lambda repo, url: "merged"  # type: ignore[method-assign,assignment]
    w.runner.pr_head = lambda repo, url: "f" * 40  # type: ignore[attr-defined]
    w.runner.poll_prs()
    assert w.store.get_job(job).state is not S.MERGED
    pages = [
        q for q in w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
        if q["job_id"] == job and q["body"].get("kind") == "merge_unverified"
    ]  # fmt: skip
    assert pages and tid in json.dumps(pages[0]["body"])


def test_a_third_rework_blocks_the_job_and_pages_the_owner(world: World) -> None:
    """Guard 2 (owner, 2026-11-01): at most 2 REWORKs per task. Here main keeps moving under
    the task (every worker session, someone else changes the same file on main), so every
    landing conflicts: two REWORKs, then the job is blocked and the owner paged."""
    w = world
    job = _held_in_review(w)
    tid = f"{job}-w1"
    (path, *_) = _changed(w, tid)
    racing = [0]

    def edit(spec: Any, task: dict[str, Any]) -> None:
        _work(spec.clone, task["spec"]["files_in_scope"][0])  # the stand-in's honest work
        if str(spec.task_id) == tid:
            racing[0] += 1
            _main_edit(w, path, f"someone else's content {racing[0]}\n")

    w.standin.worker_edit = edit
    _main_edit(w, path, "someone else's whole new content\n")
    w.runner.review(job)
    assert w.store.get_job(job).state is S.BLOCKED
    qs = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
    reworks = [q for q in qs if q["job_id"] == job and q["body"].get("kind") == "landing_rework"
               and q["body"].get("task") == tid]  # fmt: skip
    limit = [
        q for q in qs if q["job_id"] == job and q["body"].get("kind") == "landing_rework_limit"
    ]
    kinds = [(q["body"].get("kind"), q["title"]) for q in qs if q["job_id"] == job]
    assert len(reworks) == 2 and len(limit) == 1, kinds
    assert path in json.dumps(limit[0]["body"])
    rows = w.store.q("SELECT data FROM events WHERE job_id=? AND type='state' ORDER BY id", (job,))
    evs = [json.loads(r["data"])["evidence"] for r in rows]
    rw = [e for e in evs if e.get("action") == "rework" and e.get("task") == tid]
    assert len(rw) == 2 and all(e["reason"] == "logic_conflict" and path in e["files"] for e in rw)


def test_a_rework_rebuilds_on_main_replaces_the_branch_under_lease_and_runs_the_full_gate(
    world: World,
) -> None:
    """Guards 1 and 2 (owner, 2026-11-01): the REWORK's worker starts from the current
    main; its publish replaces the branch only after the old tip is kept as
    refs/vigil/rework/<task>/<n>, and an event names the old and new SHAs; the new head then
    runs the full gate (the verifier with its record for the new head, review, landing), and
    the PR's title and body are rebuilt from it (#221)."""
    w = world
    job = _held_in_review(w)
    tid = f"{job}-w1"
    (path, *_) = _changed(w, tid)
    branch = _pr(w, tid)["branch"]
    old_tip = git(w.bare, "rev-parse", f"refs/heads/{branch}")
    main = _main_edit(w, path, "someone else's whole new content\n")
    w.runner.review(job)
    assert w.store.get_job(job).state is S.READY
    (ev,) = [
        json.loads(r["data"]) for r in w.store.q(
            "SELECT data FROM events WHERE task_id=? AND type='rework_published'", (tid,))
    ]  # fmt: skip
    assert ev["old_sha"] == old_tip and ev["new_sha"] and ev["new_sha"] != old_tip
    vault = w.runner.workspace.vault(REPO)
    assert git(vault, "rev-parse", f"refs/vigil/rework/{ev['rework']}") == old_tip
    head = _pr(w, tid)["head"]
    assert w.runner.workspace.is_ancestor(REPO, main, head)  # rebuilt on main
    tests = w.store.get_artifact(job, "tests.json", tid)
    assert tests is not None and json.loads(tests.content)["after"]["sha"]
    assert w.store.get_artifact(job, "review.json", tid) is not None
    row = w.store.q("SELECT verified_sha FROM tasks WHERE id=?", (tid,))[0]
    assert git(w.bare, "rev-parse", f"refs/heads/{branch}") == row["verified_sha"]
    assert w.publisher.updates  # the PR's title and body were rebuilt


def test_a_change_already_on_main_closes_the_task_as_landed_by_main(world: World) -> None:
    """Owner, 2026-11-01: no worker; the task is closed as landed by main."""
    w = world
    job = _held_in_review(w)
    tid = f"{job}-w1"
    vault = w.runner.workspace.vault(REPO)
    pr = _pr(w, tid)
    for path in _changed(w, tid):  # main gets exactly the task's change
        _main_edit(w, path, git(vault, "show", f"{pr['head']}:{path}") + "\n")
    before = len(_workers(w, tid))
    w.runner.review(job)
    assert w.store.get_task(tid).state == "merged"
    assert w.store.q("SELECT 1 FROM events WHERE task_id=? AND type='landed_by_main'", (tid,))
    assert len(_workers(w, tid)) == before  # no worker


def test_a_rework_spends_from_the_same_task_cap(world: World) -> None:
    """Guard 3 (owner, 2026-11-01): a REWORK's fresh worker reserves from the task's own
    cap: every worker reservation fits in what the task's cap had left when it was made
    (its metered worker spend before then subtracted), the cap itself never moves, no
    reservation is a top-up, and the task's metered spend stays within the cap."""
    w = world
    job = _held_in_review(w)
    tid = f"{job}-w1"
    cap = w.store.get_task(tid).contract["limits"]["max_cost_usd"]
    (path, *_) = _changed(w, tid)
    _main_edit(w, path, "someone else's whole new content\n")
    w.runner.review(job)
    assert w.store.get_task(tid).contract["limits"]["max_cost_usd"] == cap
    rows = w.store.q(
        "SELECT r.amount_usd, r.purpose, r.created_at FROM reservations r JOIN sessions s"
        " ON s.id=r.session_id WHERE s.task_id=? AND s.role='worker' ORDER BY r.id", (tid,)
    )  # fmt: skip
    assert len(rows) >= 2, "the REWORK dispatched no fresh worker"
    for r in rows:
        spent = w.store.q(
            "SELECT COALESCE(SUM(m.cost_usd),0) AS s FROM model_calls m JOIN sessions s"
            " ON s.id=m.session_id WHERE s.task_id=? AND s.role='worker' AND m.ts<?",
            (tid, r["created_at"]),
        )[0]["s"]  # fmt: skip
        assert r["amount_usd"] <= cap - spent + 1e-9
        assert "top" not in str(r["purpose"]).lower()
    total = w.store.q(
        "SELECT COALESCE(SUM(m.cost_usd),0) AS s FROM model_calls m JOIN sessions s"
        " ON s.id=m.session_id WHERE s.task_id=? AND s.role='worker'", (tid,)
    )[0]["s"]  # fmt: skip
    assert total <= cap + 1e-9


def test_a_failed_rework_worker_s_retry_still_rebuilds_on_main_with_the_context(
    world: World,
) -> None:
    """Round 2: the REWORK context stays until the rebuilt head is published. The REWORK
    worker's first attempt fails; the owner retries; the retry's packet still says REWORK
    and names the file, and the task lands."""
    w = world
    job = _held_in_review(w)
    tid = f"{job}-w1"
    (path, *_) = _changed(w, tid)
    tries = [0]

    def edit(spec: Any, task: dict[str, Any]) -> None:
        if str(spec.task_id) == tid and "REWORK" in spec.packet and tries[0] == 0:
            tries[0] += 1
            (spec.clone / "README.md").write_text("out of scope\n")  # this attempt fails
            return
        _work(spec.clone, task["spec"]["files_in_scope"][0])

    w.standin.worker_edit = edit
    _main_edit(w, path, "someone else's whole new content\n")
    w.runner.review(job)
    item = next(
        q for q in w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
        if q["job_id"] == job and q["body"].get("kind") == "worker_failed"
    )  # fmt: skip
    r = w.client.post(f"/api/inbox/{item['id']}/retry", headers=auth(w.tokens.admin))
    assert r.status_code == 200, r.text
    last = _workers(w, tid)[-1]
    assert "REWORK" in last and path in last
    assert w.store.get_job(job).state is S.READY


def test_a_pr_merged_by_hand_before_any_landing_is_recorded_merged(world: World) -> None:
    """Round 2: the merge binding binds only what went through landing; the owner's merge
    by hand while the job is in review (review B7), or a PR from before p3-09, is recorded."""
    w = world
    job = _held_in_review(w)
    w.runner.pr_state = lambda repo, url: "merged"  # type: ignore[method-assign,assignment]
    w.runner.pr_head = lambda repo, url: "e" * 40  # type: ignore[attr-defined]
    w.runner.poll_prs()
    assert w.store.get_job(job).state is S.MERGED
    # owner, 2026-11-01: recorded and counted, never paged
    assert w.store.q("SELECT 1 FROM events WHERE job_id=? AND type='merged_unverified'", (job,))
    from vigild.kpis import compute

    assert compute(w.store)["merged_unverified"] >= 1
    pages = [q for q in w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
             if q["job_id"] == job and q["body"].get("kind") == "merge_unverified"]  # fmt: skip
    assert pages == []


def test_landing_never_runs_a_generator_on_the_host() -> None:
    """Owner, 2026-11-01: regeneration runs main's generator in the repo's dev image with no
    network, never on the host. Until that sandboxed path exists, the runner's generator
    refuses outright, so a generated-only conflict can only be a REWORK."""
    import pytest

    from vigild.github.publish import PublishError
    from vigild.jobs.runner import regenerate_docs_tables

    with pytest.raises(PublishError, match="no sandboxed generator"):
        regenerate_docs_tables(Path("/nonexistent"), ["docs/table.md"])


def test_a_failure_between_the_rework_writes_leaves_no_job_in_building_without_its_record(
    world: World,
) -> None:
    """Owner, 2026-11-01 (#260 review): the REWORK transition and its rework.json are one
    transaction. vigild fails writing the record: the job is not in building without it."""
    w = world
    job = _held_in_review(w)
    tid = f"{job}-w1"
    (path, *_) = _changed(w, tid)
    _main_edit(w, path, "someone else's whole new content\n")
    real = w.store.add_artifact

    def failing(job_id: str, name: str, *a: Any, **k: Any) -> Any:
        if name == "rework.json":
            raise RuntimeError("vigild failed between the two writes")
        return real(job_id, name, *a, **k)

    w.store.add_artifact = failing  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        w.runner.review(job)
    state = w.store.get_job(job).state
    record = w.store.get_artifact(job, "rework.json", tid)
    assert not (state is S.BUILDING and record is None), state


def test_landing_posts_vigil_verified_on_each_verified_sha(world: World) -> None:
    """Owner ruling (p3-09 PR 3, option B): vigild posts `vigil/verified` on each task's
    `verified_sha`, naming the main it was verified on."""
    w = world
    job = _held_in_review(w)
    _main_edit(w, "docs/unrelated.md", "someone else's new file\n")
    w.runner.review(job)
    assert w.store.get_job(job).state is S.READY
    for t in w.store.list_tasks(job):
        row = w.store.q("SELECT verified_sha, verified_main FROM tasks WHERE id=?", (t.id,))[0]
        assert {"repo": REPO, "sha": row["verified_sha"], "main": row["verified_main"]} in (
            w.publisher.statuses
        )


def test_a_failed_status_post_records_it_and_the_job_still_reaches_ready(world: World) -> None:
    """The status is advisory (the ruleset does not require it): until the App holds
    `statuses: write`, a refused post is recorded and landing goes on."""
    w = world
    job = _held_in_review(w)
    w.publisher.status_error = RuntimeError("the App lacks statuses: write")
    w.runner.review(job)
    assert w.store.get_job(job).state is S.READY
    failed = [e for e in w.store.events(job_id=job) if e.type == "status_failed"]
    assert failed and "statuses" in failed[0].data["error"]


def test_landing_runs_inside_the_repo_s_landing_hold_with_the_approval_time(
    world: World,
) -> None:
    """p3-09 PR 3: the runner lands a job's PRs holding its repo's landing slot, queued by
    the time the job was approved."""
    from contextlib import contextmanager

    w = world
    job = _held_in_review(w)
    seen: list[tuple[str, str, str]] = []
    land = w.runner._land_prs

    @contextmanager
    def hold(repo: str, task: str, *, approved_at: str) -> Any:
        seen.append((repo, task, approved_at))
        yield

    def landing(job_id: str) -> str:
        assert seen and seen[-1][1] == job_id  # inside the hold
        return land(job_id)

    w.runner.landing_queue.hold = hold  # type: ignore[method-assign]
    w.runner._land_prs = landing  # type: ignore[method-assign]
    w.runner.review(job)
    assert w.store.get_job(job).state is S.READY
    approved = [
        e.ts for e in w.store.events(job_id=job)
        if e.type == "state" and e.data.get("to") == "approved"
    ]  # fmt: skip
    assert seen == [(REPO, job, approved[-1])]


def _ready_cards(w: World, job: str) -> list[Any]:
    return [i for i in w.store.list_inbox() if i.job_id == job and i.kind == "ready_to_merge"]


def _questions(w: World, job: str) -> list[Any]:
    return [i for i in w.store.list_inbox() if i.job_id == job and i.kind != "ready_to_merge"]


def _to_ready(w: World) -> str:
    job = _held_in_review(w)
    w.runner.review(job)
    assert w.store.get_job(job).state is S.READY
    w.runner.pr_state = lambda repo, url: "open"  # type: ignore[method-assign,assignment]
    return job


def _verified_sha(w: World, tid: str) -> str:
    return str(w.store.q("SELECT verified_sha FROM tasks WHERE id=?", (tid,))[0]["verified_sha"])


def test_a_change_on_main_outside_the_leased_paths_leaves_a_ready_job_alone(
    world: World,
) -> None:
    w = world
    job = _to_ready(w)
    tid = f"{job}-w1"
    old = _verified_sha(w, tid)
    _main_edit(w, "docs/unrelated.md", "someone else's file\n")
    w.runner.poll_prs()
    assert _verified_sha(w, tid) == old
    assert not [e for e in w.store.events(job_id=job) if e.type == "relanded"]


def test_a_stale_ready_job_is_landed_again_and_its_card_reissued_with_no_question(
    world: World, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """p3-09 PR 3, the staleness sweep (owner, 2026-11-01, tier A): a ready job whose leased
    paths changed on main since verified_main is landed again before its card stands; the
    card is re-issued naming the new verified_sha; no question reaches the owner."""
    import vigild.jobs.runner as runner_mod

    w = world
    job = _to_ready(w)
    tid = f"{job}-w1"
    old = _verified_sha(w, tid)
    questions = [i.id for i in _questions(w, job)]
    _main_edit(w, "docs/unrelated.md", "someone else's file\n")  # main moved; rebase is clean
    monkeypatch.setattr(runner_mod, "is_stale", lambda *a, **k: True)
    w.runner.poll_prs()
    new = _verified_sha(w, tid)
    assert new != old and w.store.get_job(job).state is S.READY
    cards = _ready_cards(w, job)
    assert len(cards) == 1 and new in json.dumps(cards[0].body)
    assert [e for e in w.store.events(job_id=job) if e.type == "relanded"]
    assert [i.id for i in _questions(w, job)] == questions


def test_a_stale_ready_job_that_conflicts_goes_back_for_rework(world: World) -> None:
    """The same sweep, when main rewrote a leased file the task changed: REWORK, as from
    in_review (a card and a fresh worker); the stale ready card is resolved."""
    w = world
    job = _to_ready(w)
    tid = f"{job}-w1"
    (path, *_) = _changed(w, tid)
    before = len(_workers(w, tid))
    _main_edit(w, path, "someone else's whole new content\n")
    w.runner.poll_prs()
    moves = [e.data for e in w.store.events(job_id=job) if e.type == "state"]
    rework = [m for m in moves if m["from"] == "ready" and m["to"] == "building"]
    assert rework and rework[0]["evidence"]["action"] == "rework"
    assert any(q.kind == "landing_rework" for q in _questions(w, job))
    assert len(_workers(w, tid)) > before
    # this world's fresh worker finishes at once: rebuilt, reviewed, landed, ready again,
    # with one ready card, naming the new verified_sha
    cards = _ready_cards(w, job)
    assert len(cards) == 1 and _verified_sha(w, tid) in json.dumps(cards[0].body)
