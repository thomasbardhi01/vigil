"""Turning submissions into jobs, filing specs for approval, and approving.

Every piece of work runs inside a job, and every job waits in
`spec_pending` until the owner approves its spec from the inbox:
- a complete task (test_cmd + done_when) becomes a one-worker job whose
  spec.md and plan.md vigild writes from the contract (provenance human);
- a task without them, or a free-form request, becomes a job whose coord
  drafts spec.md and plan.md (the spec-writing task of routing rule 1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigild.config import Config, ConfigError
from vigild.contract.models import Score, Source, Task
from vigild.db import Store
from vigild.intake.paths import matches_any
from vigild.intake.scoring import IntakeOutcome, score
from vigild.intake.spec_gate import check_job_spec, check_task
from vigild.jobs.artifacts import parse_plan, parse_spec
from vigild.jobs.fsm import Actor, TransitionError, transition
from vigild.jobs.model import InboxItem, Job, JobState
from vigild.provenance import Provenance


class Runner(Protocol):
    def on_job_created(self, job_id: str, needs_spec: bool) -> None: ...
    def on_approved(self, job_id: str) -> None: ...


class SubmitError(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class NotFound(KeyError):
    pass


class Conflict(ValueError):
    pass


@dataclass
class SubmitOutcome:
    state: str
    task_id: str | None
    job_id: str | None = None
    needs_spec: bool = False
    reasons: list[str] = field(default_factory=list)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str
    base: str = "main"
    title: str
    request: str
    notes: list[str] = Field(default_factory=list)
    why: str
    value: Score
    risk: Score
    source: Source = Source.HUMAN
    labels: list[str] = Field(default_factory=list)


def render_spec(task: Task, money_globs: list[str]) -> str:
    s = task.spec
    scope = s.files_in_scope
    money = [f for f in scope if matches_any(f, money_globs)]
    lines = [
        f"# Spec: {s.goal}",
        "",
        "## Goal",
        s.goal,
        "",
        "## Non-goals",
        "- Anything outside the files in scope.",
        "",
        "## Acceptance criteria",
        f"- AC1: {s.done_when} test: `{s.test_cmd}`",
        "",
        "## Files in scope",
        *[f"- `{f}`" for f in scope],
        "",
        "## Files out of scope",
        *([f"- `{f}`" for f in s.out_of_scope] or ["- none listed"]),
        "",
        "## Money paths",
        *([f"- `{f}`" for f in money] or ["none"]),
        "",
        "## Risks",
        f"- Risk score {task.risk}/5. Why this is worth doing: {task.why}",
        "",
        "## Rollback",
        "Revert the PR.",
        "",
    ]
    return "\n".join(lines)


def render_plan(task: Task) -> str:
    worker = {
        "task_id": task.task_id,
        "goal": task.spec.goal,
        "why": task.why,
        "value": task.value,
        "risk": task.risk,
        "size": (task.size.value if task.size else "S"),
        "test_cmd": task.spec.test_cmd,
        "done_when": task.spec.done_when,
        "files_in_scope": task.spec.files_in_scope,
        "out_of_scope": task.spec.out_of_scope,
        "must_fail_first": task.spec.must_fail_first,
        "depends_on": [],
        "labels": task.labels,
        "max_cost_usd": task.limits.max_cost_usd,
    }
    return (
        "# Plan\n\nOne worker, from the submitted contract.\n\n## Workers\n```json\n"
        + json.dumps({"workers": [worker]}, indent=2)
        + "\n```\n"
    )


class JobService:
    def __init__(self, cfg: Config, store: Store, runner: Runner) -> None:
        self.cfg = cfg
        self.store = store
        self.runner = runner

    # --- submissions ----------------------------------------------------------

    def _intake(self, req: dict[str, Any], files: list[str]) -> list[str]:
        r = score({**req, "files_in_scope": files}, self.cfg.routing.money_paths)
        if r.outcome is IntakeOutcome.REJECT:
            raise SubmitError(r.reasons)
        return r.reasons if r.outcome is IntakeOutcome.PROPOSE else []

    def submit_task(self, raw: dict[str, Any]) -> SubmitOutcome:
        raw = dict(raw)
        provisional = "task_id" not in raw
        raw.setdefault("task_id", "pending")
        try:
            task = Task.model_validate(raw)
            self.cfg.repo(task.repo)
        except ValidationError as e:
            raise SubmitError(
                [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
            ) from e
        except ConfigError as e:
            raise SubmitError([str(e)]) from e

        intake = {"why": task.why, "value": task.value, "risk": task.risk, "source": task.source}
        proposed = self._intake(intake, task.spec.files_in_scope)
        if proposed:
            tid = (
                task.task_id if not provisional else f"proposal-{len(self.store.list_tasks()) + 1}"
            )
            self.store.create_task(
                None, {**task.model_dump(mode="json"), "task_id": tid}, Provenance.HUMAN
            )
            self.store.update_task(tid, state="proposed")
            return SubmitOutcome("proposed", tid, reasons=proposed)

        gate = check_task(task)
        job = self.store.create_job(
            repo=task.repo,
            base=task.base,
            title=task.spec.goal,
            request=f"{task.spec.goal}\n\nWhy: {task.why}",
            notes=[],
            source=task.source.value,
        )
        intake_doc = {**intake, "labels": task.labels, "submitted": task.model_dump(mode="json")}
        self.store.add_artifact(
            job.id, "intake.json", json.dumps(intake_doc, sort_keys=True), Provenance.HUMAN
        )
        if gate.needs_spec:
            self.runner.on_job_created(job.id, True)
            return SubmitOutcome("spec_pending", None, job.id, needs_spec=True, reasons=gate.errors)

        if provisional:
            task = task.model_copy(update={"task_id": f"{job.id}-w1"})
        task = task.model_copy(update={"job_id": job.id})
        self.store.add_artifact(
            job.id, "spec.md", render_spec(task, self.cfg.routing.money_paths), Provenance.HUMAN
        )
        self.store.add_artifact(job.id, "plan.md", render_plan(task), Provenance.HUMAN)
        self.store.create_task(job.id, task.model_dump(mode="json"), Provenance.HUMAN)
        self.store.update_task(task.task_id, state="awaiting_approval")
        errors = self.file_for_approval(job.id)
        if errors:
            raise SubmitError(errors)
        self.runner.on_job_created(job.id, False)
        return SubmitOutcome("spec_pending", task.task_id, job.id)

    def submit_request(self, req: JobRequest) -> Job:
        try:
            self.cfg.repo(req.repo)
        except ConfigError as e:
            raise SubmitError([str(e)]) from e
        self._intake(req.model_dump(mode="json"), [])
        job = self.store.create_job(
            repo=req.repo,
            base=req.base,
            title=req.title,
            request=req.request,
            notes=req.notes,
            source=req.source.value,
        )
        self.store.add_artifact(job.id, "intake.json", req.model_dump_json(), Provenance.HUMAN)
        self.runner.on_job_created(job.id, True)
        return job

    # --- spec gate and the inbox ---------------------------------------------

    def file_for_approval(self, job_id: str) -> list[str]:
        """Run the job spec gate on the stored spec and plan; file the inbox item."""
        spec = self.store.get_artifact(job_id, "spec.md")
        plan = self.store.get_artifact(job_id, "plan.md")
        if spec is None or plan is None:
            errors = ["spec.md and plan.md are both required"]
        else:
            pdoc = parse_plan(plan.content)
            errors = check_job_spec(parse_spec(spec.content), pdoc, self.cfg.routing.money_paths)
        self.store.add_artifact(
            job_id,
            "spec_gate.json",
            json.dumps({"ok": not errors, "errors": errors}),
            Provenance.HUMAN,
        )
        if errors:
            return errors
        job = self.store.get_job(job_id)
        intake_art = self.store.get_artifact(job_id, "intake.json")
        intake = json.loads(intake_art.content) if intake_art else {}
        sdoc = parse_spec(spec.content) if spec else None
        self.store.create_inbox_item(
            "specs",
            "spec",
            job_id,
            f"Approve spec: {job.title}",
            {
                "repo": job.repo,
                "why": intake.get("why"),
                "value": intake.get("value"),
                "risk": intake.get("risk"),
                "decider": intake.get("decider"),
                "money_paths": sdoc.money_paths if sdoc else [],
                "workers": [
                    {
                        "task_id": w.task_id,
                        "goal": w.goal,
                        "size": w.size.value,
                        "files_in_scope": w.files_in_scope,
                        "depends_on": w.depends_on,
                    }
                    for w in pdoc.workers
                ],
            },
        )
        return []

    def page(self, job_id: str | None, title: str, body: dict[str, Any]) -> InboxItem:
        """A question or page for the owner: the third inbox queue."""
        item = self.store.create_inbox_item("questions", "page", job_id, title, body)
        self.store.add_event(
            "page", {"item": item.id, "title": title, **body}, Provenance.HUMAN, job_id=job_id
        )
        return item

    def approve(self, item_id: int, edits: str | None = None) -> Job:
        with self.store.lock:
            try:
                item = self.store.get_inbox_item(item_id)
            except KeyError as e:
                raise NotFound(item_id) from e
            if item.queue != "specs" or item.status != "open" or item.job_id is None:
                raise Conflict(f"inbox item {item_id} is not an open spec to approve")
            try:
                job = transition(
                    self.store,
                    item.job_id,
                    JobState.APPROVED,
                    Actor.OWNER,
                    channel="inbox",
                    evidence={"inbox_item_id": item_id},
                )
            except TransitionError as e:
                raise Conflict(str(e)) from e
            self.store.add_approval(job.id, item_id, Actor.OWNER.value, "inbox", edits)
            self.store.add_artifact(
                job.id,
                "approval.json",
                json.dumps({"inbox_item_id": item_id, "actor": "owner", "edits": edits}),
                Provenance.HUMAN,
            )
            self.store.add_event(
                "approval",
                {"inbox_item_id": item_id, "edits": edits},
                Provenance.HUMAN,
                job_id=job.id,
            )
            self.store.resolve_inbox_item(item_id, Actor.OWNER.value)
        self.runner.on_approved(job.id)
        return job
