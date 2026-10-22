"""The coord loop end to end on a fixture repo (not ParkAgent):
request -> coord writes spec.md + plan.md -> spec gate -> inbox -> owner
approves -> planning -> two workers in parallel -> host checks + draft PRs
(against a local bare repo) -> worker_report.json -> job tree from one endpoint.

The executor here is a stand-in for the container that does what the harness
does (edit, report, commit); tests/jobs/test_coord_loop_docker.py runs the
real container."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth, git
from tests.test_devimage import FakeDocker
from vigild.api.app import create_app
from vigild.budget import Budget
from vigild.config import Config, RepoPolicy
from vigild.db import Store
from vigild.devimage import DevImages
from vigild.executors.base import EventSink, ExecOutcome, SessionSpec
from vigild.jobs.model import Role
from vigild.jobs.runner import JobRunner
from vigild.jobs.service import JobService
from vigild.services import Services, Tokens
from vigild.telemetry.spans import Telemetry
from vigild.workspace import Workspace

REPO = "o/fixture"

SPEC = """# Spec: document the rate limit

## Goal
The feature map and the runbook both describe the rate limit.

## Non-goals
- Changing the limit.

## Acceptance criteria
- AC1: the feature map names the rate limit. test: `grep -q 'rate limit' docs/feature-map.md`
- AC2: the runbook says how to change it. test: `grep -q 'RATE_LIMIT' docs/runbook.md`

## Files in scope
- `docs/feature-map.md`
- `docs/runbook.md`

## Files out of scope
- `src/**`

## Money paths
none

## Interfaces
- None shared: each worker edits its own file.

## Risks
- None.

## Rollback
Revert the PRs.
"""


def plan(job: str) -> str:
    workers = [
        {
            "task_id": f"{job}-w1",
            "goal": "feature map row",
            "why": "AC1",
            "value": 3,
            "risk": 1,
            "size": "XS",
            "test_cmd": "grep -q 'rate limit' docs/feature-map.md",
            "done_when": "AC1 holds",
            "files_in_scope": ["docs/feature-map.md"],
            "labels": ["docs"],
        },
        {
            "task_id": f"{job}-w2",
            "goal": "runbook section",
            "why": "AC2",
            "value": 3,
            "risk": 1,
            "size": "XS",
            "test_cmd": "grep -q 'RATE_LIMIT' docs/runbook.md",
            "done_when": "AC2 holds",
            "files_in_scope": ["docs/runbook.md"],
            "labels": ["docs"],
        },
    ]
    verify = [
        {"criterion": c, "level": 0, "why_not_higher": "a doc check has no property"}
        for c in ("AC1", "AC2")
    ]
    return (
        "# Plan\n\n## Notes addressed\n- keep it short: adopted\n\n## Workers\n```json\n"
        + json.dumps({"workers": workers, "verify": verify}, indent=1)
        + "\n```\n"
    )


EDITS = {
    "docs/feature-map.md": "# Feature map\n\n| rate limit | 10 req/min |\n",
    "docs/runbook.md": "# Runbook\n\nSet RATE_LIMIT in the env to change the limit.\n",
}


@dataclass
class StandIn:
    """Does what the container's harness does: run the agent's work, write the
    report and harness record, commit. Records concurrency."""

    coord_drafts: list[Callable[[str], tuple[str, str]]] = field(default_factory=list)
    worker_edit: Callable[[SessionSpec, dict[str, Any]], None] | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)
    running: int = 0
    max_running: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    barrier: threading.Barrier | None = None

    def run(self, spec: SessionSpec, gateway_token: str, on_event: EventSink) -> ExecOutcome:
        assert gateway_token.startswith("vgw_")
        assert spec.packet.startswith("# 1. Role and rules")
        self.calls.append((spec.role.value, spec.task_id or spec.job_id))
        with self.lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            if spec.role is Role.COORD:
                draft = (
                    self.coord_drafts.pop(0) if self.coord_drafts else (lambda j: (SPEC, plan(j)))
                )
                s, p = draft(spec.job_id)
                d = spec.clone / ".vigil" / spec.job_id
                d.mkdir(parents=True, exist_ok=True)
                (d / "spec.md").write_text(s)
                (d / "plan.md").write_text(p)
                git(spec.clone, "add", "-A")
                git(spec.clone, "commit", "-q", "--allow-empty", "-m", "coord: spec and plan")
                return ExecOutcome("done", 0, {"status": "done", "plugins": ["guard"]})
            if self.barrier:
                self.barrier.wait(timeout=10)  # both workers must be in flight at once
            task = json.loads((spec.clone / ".vigil" / "task.json").read_text())
            if self.worker_edit:
                self.worker_edit(spec, task)
            else:
                f = task["spec"]["files_in_scope"][0]
                (spec.clone / f).write_text(EDITS[f])
            d = spec.clone / ".vigil" / spec.job_id / spec.task_id  # type: ignore[operator]
            d.mkdir(parents=True, exist_ok=True)
            if not (d / "ask_coord.json").exists():
                (d / "worker_report.json").write_text(
                    json.dumps(
                        {
                            "task_id": spec.task_id,
                            "job_id": spec.job_id,
                            "test_before": "fail",
                            "test_after": "pass",
                            "files_changed": task["spec"]["files_in_scope"],
                            "summary": "documented it",
                            "self_check": {
                                "test_failed_first": True,
                                "outside_scope": [],
                                "not_done": "nothing",
                                "reviewer_would_flag": "wording",
                                "could_delete": "nothing",
                            },
                            "open_questions": [],
                            "provenance": "claude",
                        }
                    )
                )
            (d / "harness_tests.json").write_text(
                json.dumps(
                    {
                        "before": {"outcome": "fail"},
                        "after": {"outcome": "pass"},
                        "provenance": "human",
                    }
                )
            )
            git(spec.clone, "add", "-A")
            git(spec.clone, "commit", "-qm", f"worker {spec.task_id}")
            return ExecOutcome("done", 0, {"status": "done", "plugins": ["guard"]})
        finally:
            with self.lock:
                self.running -= 1


@dataclass
class BarePublisher:
    """GitHub stand-in: pushes to the local bare repo and records draft PRs."""

    prs: list[dict[str, Any]] = field(default_factory=list)

    def publish(
        self,
        clone: Path,
        *,
        repo: str,
        branch: str,
        base: str,
        title: str,
        body: str,
        scope: list[str],
    ) -> str:
        from vigild.github.publish import publish

        class Pulls:
            def create_pull(
                s,
                repo: str,
                *,
                head: str,
                base: str,
                title: str,
                body: str,
                draft: bool,
            ) -> str:
                self.prs.append(
                    {"head": head, "base": base, "title": title, "draft": draft, "body": body}
                )
                return f"https://github.com/{repo}/pull/{len(self.prs)}"

        return publish(
            clone,
            repo=repo,
            branch=branch,
            base=base,
            title=title,
            body=body,
            pulls=Pulls(),
            scope=scope,
        )


@dataclass
class World:
    client: TestClient
    store: Store
    budget: Budget
    standin: StandIn
    publisher: BarePublisher
    bare: Path
    tokens: Tokens
    images: DevImages
    runner: JobRunner


@pytest.fixture
def world(
    cfg: Config, tmp_path: Path, fixture_repo: dict[str, Path], tokens: Tokens
) -> Iterator[World]:
    cfg.repos.repos[REPO] = RepoPolicy(
        visibility="public",
        decider=["haiku"],
        backends=["claude-sonnet", "claude-opus", "claude-haiku"],
        dev_image="vigil/claude-executor:2.1.306",
        dev_image_check="true",
    )
    store = Store.open(":memory:")
    budget = Budget(store, cfg.budgets)
    from vigild.config import Secrets
    from vigild.gateway.service import Gateway

    gateway = Gateway(cfg, store, budget, Secrets({}))
    images = DevImages(cfg, store, FakeDocker())
    images.validate(REPO)
    standin, publisher = StandIn(), BarePublisher()
    runner = JobRunner(
        cfg,
        store,
        budget,
        gateway,
        standin,
        Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"])),
        publisher,
        Telemetry(),
        images,
        background=False,
    )
    jobs = JobService(cfg, store, runner)
    runner.jobs = jobs
    services = Services(cfg=cfg, store=store, tokens=tokens, jobs=jobs)
    with TestClient(create_app(services)) as c:
        yield World(
            c, store, budget, standin, publisher, fixture_repo["bare"], tokens, images, runner
        )


def _request(w: World) -> str:
    r = w.client.post(
        "/api/jobs",
        headers=auth(w.tokens.admin),
        json={
            "repo": REPO,
            "title": "Document the rate limit",
            "request": "The limit is undocumented.",
            "notes": ["keep it short"],
            "why": "support asks weekly",
            "value": 3,
            "risk": 1,
        },
    )
    assert r.status_code == 202, r.text
    return str(r.json()["id"])


def test_end_to_end(world: World) -> None:
    w = world
    w.standin.barrier = threading.Barrier(2)
    job = _request(w)

    # the coord drafted; the spec gate passed; the owner sees it in the inbox
    inbox = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()
    (item,) = inbox["specs"]
    assert item["job_id"] == job
    assert [x["task_id"] for x in item["body"]["workers"]] == [f"{job}-w1", f"{job}-w2"]
    assert w.store.get_job(job).state.value == "spec_pending"
    assert [c[0] for c in w.standin.calls] == ["coord"]

    # approve from the inbox: plan, then two workers in parallel
    r = w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})
    assert r.status_code == 200, r.text
    assert w.standin.max_running == 2
    assert w.store.get_job(job).state.value == "in_review"

    # two draft PRs, from the host, each branch with its own worker_report.json
    assert sorted(p["head"] for p in w.publisher.prs) == [f"vigil/{job}-w1", f"vigil/{job}-w2"]
    assert all(p["draft"] for p in w.publisher.prs)
    for n in (1, 2):
        files = git(w.bare, "ls-tree", "-r", "--name-only", f"vigil/{job}-w{n}")
        assert f".vigil/{job}/{job}-w{n}/worker_report.json" in files
        assert f".vigil/{job}/spec.md" in files and f".vigil/{job}/plan.md" in files
    assert git(w.bare, "log", "-1", "--format=%s", "main") == "seed"

    # the whole tree from one endpoint
    tree = w.client.get(f"/api/jobs/{job}/tree", headers=auth(w.tokens.read)).json()
    assert tree["job"]["state"] == "in_review"
    (coord,) = tree["sessions"]
    assert coord["role"] == "coord" and coord["status"] == "done"
    workers = coord["children"]
    assert sorted(x["role"] for x in workers) == ["worker", "worker"]
    assert all(x["status"] == "pr_open" and x["pr_url"] for x in workers)
    names = sorted(a["name"] for a in tree["artifacts"])
    assert names.count("worker_report.json") == 2
    assert {"spec.md", "plan.md", "approval.json", "spec_gate.json"} <= set(names)
    assert {t["state"] for t in tree["tasks"]} == {"pr_open"}
    # every reservation was settled
    assert w.budget.open_today() == 0


def test_coord_revises_after_a_gate_failure(world: World) -> None:
    w = world
    bad = SPEC.replace(" test: `grep -q 'RATE_LIMIT' docs/runbook.md`", "")
    w.standin.coord_drafts = [lambda j: (bad, plan(j))]
    job = _request(w)
    assert [c[0] for c in w.standin.calls] == ["coord", "coord"]
    (item,) = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["specs"]
    assert item["job_id"] == job


def test_coord_pages_the_owner_after_three_failed_drafts(world: World) -> None:
    w = world
    bad = SPEC.replace(" test: `grep -q 'RATE_LIMIT' docs/runbook.md`", "")
    w.standin.coord_drafts = [lambda j: (bad, plan(j))] * 3
    job = _request(w)
    inbox = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()
    assert inbox["specs"] == []
    assert any(q["job_id"] == job and "spec gate" in q["title"] for q in inbox["questions"])
    assert w.store.get_job(job).state.value == "spec_pending"


def _approve(w: World) -> str:
    job = _request(w)
    item = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["specs"][0]
    w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})
    return job


def test_daily_cap_halts_dispatch(world: World) -> None:
    w = world
    job = _request(w)
    # spend the day elsewhere: $4.50 of $5 is held, so no $1 worker fits
    w.budget.reserve(session_id=None, task_id="other-1", amount=2.0, purpose="worker")
    w.budget.reserve(session_id=None, task_id="other-2", amount=2.0, purpose="worker")
    w.budget.reserve(session_id=None, task_id="other-3", amount=0.5, purpose="worker")
    item = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["specs"][0]
    w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})
    assert [c[0] for c in w.standin.calls] == ["coord"]  # no worker started
    assert w.publisher.prs == []
    jobrow = w.store.get_job(job)
    assert jobrow.state.value == "blocked" and jobrow.blocked_from is not None
    pages = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
    assert any("daily" in p["title"] for p in pages)


def test_stale_dev_image_refuses_dispatch(world: World) -> None:
    w = world
    w.images.docker.image_id = "sha256:rebuilt"  # type: ignore[attr-defined]
    job = _request(w)
    assert w.standin.calls == []
    pages = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
    assert any(p["job_id"] == job and "dev image" in p["title"] for p in pages)


def test_ask_coord_files_a_question(world: World) -> None:
    w = world

    def ask(spec: SessionSpec, task: dict[str, Any]) -> None:
        d = spec.clone / ".vigil" / spec.job_id / str(spec.task_id)
        d.mkdir(parents=True, exist_ok=True)
        if spec.task_id and spec.task_id.endswith("w2"):
            (d / "ask_coord.json").write_text(json.dumps({"question": "Which env var name?"}))
        else:
            f = task["spec"]["files_in_scope"][0]
            (spec.clone / f).write_text(EDITS[f])

    w.standin.worker_edit = ask
    job = _approve(w)
    questions = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
    q = next(q for q in questions if q["kind"] == "ask_coord")
    assert q["job_id"] == job and q["body"]["question"] == "Which env var name?"
    assert q["body"]["coord_session_id"] == w.store.get_job(job).coord_session_id
    assert [p["head"] for p in w.publisher.prs] == [f"vigil/{job}-w1"]
    assert w.store.get_task(f"{job}-w2").state == "waiting"


def test_out_of_scope_worker_is_not_published(world: World) -> None:
    w = world

    def sneaky(spec: SessionSpec, task: dict[str, Any]) -> None:
        f = task["spec"]["files_in_scope"][0]
        (spec.clone / f).write_text(EDITS[f])
        (spec.clone / "README.md").write_text("sneaky\n")

    w.standin.worker_edit = sneaky
    job = _approve(w)
    assert w.publisher.prs == []
    assert {t.state for t in w.store.list_tasks(job)} == {"failed"}
    assert w.store.get_job(job).state.value == "building"
    pages = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
    assert any("acceptance" in p["title"] for p in pages)


def test_a_session_without_guard_fails_closed(world: World) -> None:
    w = world

    class NoGuard(StandIn):
        def run(self, spec: SessionSpec, gateway_token: str, on_event: EventSink) -> ExecOutcome:
            if spec.role is Role.COORD:
                return super().run(spec, gateway_token, on_event)
            return ExecOutcome(
                "failed", 3, {"status": "failed", "error": "guard not loaded"}, "guard not loaded"
            )

    w.runner.executor = NoGuard()
    job = _approve(w)
    assert w.publisher.prs == []
    assert {t.state for t in w.store.list_tasks(job)} == {"failed"}
