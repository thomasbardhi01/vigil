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
from typing import Any

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
