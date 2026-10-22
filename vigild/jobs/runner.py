"""The job runner: drives a job through stages 1-3 of the protocol.

- on_job_created (a request with no spec): the coord drafts spec.md and
  plan.md; vigild runs the spec gate; up to three drafts, then it pages you.
- on_approved (only from the inbox): planning turns plan.md's contracts into
  routed tasks; building runs them in dependency waves, each wave's workers in
  parallel, each in its own container, clone and branch. After a worker exits,
  vigild checks acceptance on the host and, if it passes, pushes the branch and
  opens the draft PR itself (P2): the worker never holds a GitHub token.

Every session reserves its budget before it starts, gets a gateway token that
is revoked when it ends, runs in its repo's validated dev image, and writes its
events. A budget refusal halts dispatch, blocks the job and pages you.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from vigild.budget import Budget, BudgetExceeded
from vigild.config import Config
from vigild.contract.models import Limits, Spec, Task, Verify, WorkerContract
from vigild.db import Store, iso
from vigild.devimage import DevImages, StaleDevImage
from vigild.executors.base import ExecOutcome, Executor, SessionSpec
from vigild.gateway.service import Gateway
from vigild.github.publish import PublishError
from vigild.jobs.acceptance import check_worker
from vigild.jobs.artifacts import ArtifactError, parse_plan, read_worker_report, render
from vigild.jobs.fsm import Actor, TransitionError, transition
from vigild.jobs.model import JobState, Role, SessionRow
from vigild.metering.calls import session_cost
from vigild.packets.assemble import assemble_coord, assemble_worker
from vigild.provenance import Provenance
from vigild.repos import RepoPolicyError, check_backend
from vigild.router.rules import RoutingError, route
from vigild.telemetry.spans import Telemetry
from vigild.workspace import Workspace

log = logging.getLogger("vigild.runner")
COORD_DRAFTS = 3


class Publisher(Protocol):
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
    ) -> str: ...


class Pager(Protocol):
    def page(self, job_id: str | None, title: str, body: dict[str, Any]) -> Any: ...
    def file_for_approval(self, job_id: str) -> list[str]: ...


class Refused(Exception):
    """A session could not start (budget, policy); dispatch halts."""


class JobRunner:
    def __init__(
        self,
        cfg: Config,
        store: Store,
        budget: Budget,
        gateway: Gateway,
        executor: Executor,
        workspace: Workspace,
        publisher: Publisher,
        telemetry: Telemetry,
        dev_images: DevImages,
        *,
        background: bool = True,
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.budget = budget
        self.gateway = gateway
        self.executor = executor
        self.workspace = workspace
        self.publisher = publisher
        self.telemetry = telemetry
        self.dev_images = dev_images
        self.background = background
        self.jobs: Pager | None = None

    # --- triggers ---------------------------------------------------------------------

    def _spawn(self, fn: Callable[[str], None], job_id: str) -> None:
        def safe(j: str) -> None:
            try:
                fn(j)
            except Exception as e:  # never die silently: page
                log.exception("runner failed on %s", j)
                self._page(j, f"vigild error on {j}", {"error": f"{type(e).__name__}: {e}"})

        if self.background:
            threading.Thread(target=safe, args=(job_id,), daemon=True).start()
        else:
            safe(job_id)

    def on_job_created(self, job_id: str, needs_spec: bool) -> None:
        if needs_spec:
            self._spawn(self.run_coord, job_id)

    def on_approved(self, job_id: str) -> None:
        self._spawn(self.build, job_id)

    # --- helpers ------------------------------------------------------------------------

    def _page(self, job_id: str | None, title: str, body: dict[str, Any]) -> None:
        assert self.jobs is not None
        self.jobs.page(job_id, title, body)

    def _block(self, job_id: str, reason: str) -> None:
        try:
            transition(
                self.store, job_id, JobState.BLOCKED, Actor.VIGILD, evidence={"reason": reason}
            )
        except TransitionError:
            log.warning("could not block %s", job_id)

    def _event_sink(self, s: SessionRow) -> Callable[[dict[str, Any]], None]:
        def sink(e: dict[str, Any]) -> None:
            self.store.add_event(
                str(e.get("type", "state")),
                e.get("data") or {},
                Provenance.CLAUDE,
                job_id=s.job_id,
                session_id=s.id,
                task_id=s.task_id,
            )

        return sink

    def _image(self, repo: str) -> str:
        return self.dev_images.ensure_fresh(repo)

    def _run_session(
        self, s: SessionRow, spec: SessionSpec, reservation: int, attrs: dict[str, Any]
    ) -> ExecOutcome:
        """Token, telemetry, run, revoke, settle. The reservation is already made."""
        token = self.gateway.issue_token(s.id, spec.repo, spec.preset)
        self.store.update_session(
            s.id, status="running", started_at=iso(), clone_path=str(spec.clone)
        )
        try:
            with self.telemetry.session(s.id, attrs) as tr:
                spec.traceparent = tr.traceparent
                self.store.update_session(s.id, detail={"trace_id": tr.trace_id})
                with self.telemetry.span(tr, "vigil.spawn", {"vigil.image": spec.image or ""}):
                    out = self.executor.run(spec, token, self._event_sink(s))
                tr.set("vigil.status", out.status)
            return out
        finally:
            self.gateway.revoke(s.id)
            self.budget.settle(reservation)
            self.store.update_session(s.id, ended_at=iso())

    def _spec(self, s: SessionSpec | None = None, **kw: Any) -> SessionSpec:
        return SessionSpec(**kw)

    # --- stage 1: the coord drafts spec.md and plan.md ------------------------------------

    def run_coord(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        preset = self.cfg.routing.coord
        try:
            image = self._image(job.repo)
            check_backend(self.cfg, job.repo, preset)
        except StaleDevImage as e:
            self._page(
                job_id, f"{job_id}: dev image not fresh; coord not started", {"error": str(e)}
            )
            return
        except RepoPolicyError as e:
            self._page(job_id, f"{job_id}: coord backend refused", {"error": str(e)})
            return
        branch = f"vigil/{job_id}-spec"
        coord = self.store.create_session(job_id, Role.COORD, backend_preset=preset, branch=branch)
        self.store.set_coord_session(job_id, coord.id)
        clone = self.workspace.clone(job.repo, f"{job_id}-coord", branch=branch, base=job.base)
        intake = self.store.get_artifact(job_id, "intake.json")
        meta = json.loads(intake.content) if intake else {}
        request = {
            "job_id": job_id,
            "repo": job.repo,
            "base": job.base,
            "title": job.title,
            "request": job.request,
            "notes": job.notes,
            "why": meta.get("why"),
            "value": meta.get("value"),
            "risk": meta.get("risk"),
        }
        self.workspace.write_task(clone, request)
        gate_errors: list[str] | None = None
        for attempt in range(1, COORD_DRAFTS + 1):
            try:
                rid = self.budget.reserve(
                    session_id=coord.id,
                    task_id=None,
                    amount=self.cfg.budgets.coord_session_usd,
                    purpose="coord",
                )
            except BudgetExceeded as e:
                self.store.update_session(coord.id, status="refused")
                self._page(
                    job_id, f"{job_id}: {e.cap} cap reached; coord not started", {"error": str(e)}
                )
                return
            packet = assemble_coord(clone, request, untrusted={}, gate_errors=gate_errors)
            self.store.add_event(
                "packet",
                {"role": "coord", "attempt": attempt, "dropped": packet.dropped},
                Provenance.HUMAN,
                job_id=job_id,
                session_id=coord.id,
            )
            spec = SessionSpec(
                session_id=coord.id,
                role=Role.COORD,
                job_id=job_id,
                task_id=None,
                repo=job.repo,
                preset=preset,
                model=self.cfg.preset(preset).model or "",
                clone=clone,
                session_dir=self.cfg.vigild.data_path / "sessions" / f"{coord.id}-{attempt}",
                max_turns=40,
                max_minutes=30,
                max_budget_usd=self.cfg.budgets.coord_session_usd,
                mounts=self.workspace.overlays(clone),
                packet=packet.text,
                image=image,
            )
            out = self._run_session(
                coord,
                spec,
                rid,
                {
                    "vigil.job_id": job_id,
                    "vigil.role": "coord",
                    "vigil.repo": job.repo,
                    "vigil.attempt": attempt,
                },
            )
            if out.status != "done":
                self.store.update_session(coord.id, status="failed")
                self._page(
                    job_id,
                    f"{job_id}: coord session {out.status}",
                    {"error": out.error or "", "attempt": attempt},
                )
                return
            for name in ("spec.md", "plan.md"):
                path = clone / ".vigil" / job_id / name
                text = path.read_text() if path.is_file() else ""
                self.store.add_artifact(
                    job_id, name, render(name, text, Provenance.CLAUDE), Provenance.CLAUDE
                )
            assert self.jobs is not None
            gate_errors = self.jobs.file_for_approval(job_id)
            if not gate_errors:
                self.store.update_session(coord.id, status="done")
                return
            self.store.add_event(
                "spec_gate",
                {"attempt": attempt, "errors": gate_errors},
                Provenance.HUMAN,
                job_id=job_id,
                session_id=coord.id,
            )
        self.store.update_session(coord.id, status="failed")
        self._page(
            job_id,
            f"{job_id}: the spec gate refused {COORD_DRAFTS} drafts",
            {"errors": gate_errors or []},
        )

    # --- stages 2-3: planning and building -----------------------------------------------

    def _task(self, job_id: str, repo: str, base: str, source: str, w: WorkerContract) -> Task:
        cap = self.cfg.budgets.per_task_usd
        return Task(
            task_id=w.task_id,
            repo=repo,
            base=base,
            branch=f"vigil/{w.task_id}",
            why=w.why,
            value=w.value,
            risk=w.risk,
            job_id=job_id,
            source=source,  # type: ignore[arg-type]
            spec=Spec(
                goal=w.goal,
                test_cmd=w.test_cmd,
                done_when=w.done_when,
                must_fail_first=w.must_fail_first,
                files_in_scope=w.files_in_scope,
                out_of_scope=w.out_of_scope,
                verify=Verify(level=w.verify_level),
            ),
            limits=Limits(max_cost_usd=min(w.max_cost_usd or cap, cap)),
            depends_on=w.depends_on,
            labels=w.labels,
            size=w.size,
        )

    def build(self, job_id: str) -> None:
        job = transition(self.store, job_id, JobState.PLANNING, Actor.VIGILD)
        art = self.store.get_artifact(job_id, "plan.md")
        assert art is not None
        plan = parse_plan(art.content)
        for w in plan.workers:
            task = self._task(job_id, job.repo, job.base, job.source, w)
            try:
                r = route(task, self.cfg)
            except RoutingError as e:
                self._page(job_id, f"{job_id}: {w.task_id} can't be routed", {"error": str(e)})
                self._block(job_id, f"routing: {e}")
                return
            contract = task.model_copy(
                update={"tier": r.tier, "tier_reason": r.tier_reason, "backend": r.preset}
            ).model_dump(mode="json")
            try:
                self.store.get_task(w.task_id)
                self.store.update_task(w.task_id, contract=contract)
            except KeyError:
                self.store.create_task(job_id, contract, Provenance.CLAUDE)
            self.store.route_task(
                w.task_id, tier=r.tier, tier_reason=r.tier_reason, backend_preset=r.preset
            )
        transition(self.store, job_id, JobState.BUILDING, Actor.VIGILD)

        done: set[str] = set()
        pending = list(plan.workers)
        while pending:
            wave = [w for w in pending if set(w.depends_on) <= done]
            if not wave:
                break  # the rest wait on a failed or waiting dependency
            pending = [w for w in pending if w not in wave]
            try:
                reservations = self._reserve_wave(job_id, [w.task_id for w in wave])
            except Refused:
                return
            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                futures = [
                    pool.submit(self._run_worker, job_id, w.task_id, reservations[w.task_id])
                    for w in wave
                ]
                results = [f.result() for f in futures]
            done |= {w.task_id for w, ok in zip(wave, results, strict=True) if ok}
        tasks = self.store.list_tasks(job_id)
        if tasks and all(t.state == "pr_open" for t in tasks):
            transition(self.store, job_id, JobState.IN_REVIEW, Actor.VIGILD)

    def _reserve_wave(self, job_id: str, task_ids: list[str]) -> dict[str, int]:
        """Reserve every worker of a wave before any starts; on a refusal,
        release them, block the job and page: dispatch halts."""
        held: dict[str, int] = {}
        for tid in task_ids:
            t = self.store.get_task(tid)
            amount = float(t.contract["limits"]["max_cost_usd"])
            try:
                held[tid] = self.budget.reserve(
                    session_id=None, task_id=tid, amount=amount, purpose="worker"
                )
            except BudgetExceeded as e:
                for rid in held.values():
                    self.budget.settle(rid, 0.0)
                for t2 in task_ids:
                    self.store.update_task(t2, state="waiting")
                self._page(
                    job_id,
                    f"{job_id}: {e.cap} cap reached; dispatch halted",
                    {"cap": e.cap, "detail": e.detail, "tasks": task_ids},
                )
                self._block(job_id, f"budget: {e}")
                raise Refused(str(e)) from e
        return held

    def _write_job_artifacts(self, job_id: str, clone: Path) -> None:
        for name in ("spec.md", "plan.md", "approval.json"):
            art = self.store.get_artifact(job_id, name)
            if art is None:
                continue
            path = clone / ".vigil" / job_id / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(art.content)
        self.workspace._git(clone, "add", ".vigil")
        self.workspace._git(clone, "commit", "-q", "-m", f"vigil: {job_id} spec, plan, approval")

    def _fail(
        self,
        job_id: str,
        s: SessionRow,
        task_id: str,
        title: str,
        body: dict[str, Any],
        state: str = "failed",
    ) -> bool:
        self.store.update_session(s.id, status=state)
        self.store.update_task(task_id, state=state)
        self._page(job_id, title, {"task_id": task_id, **body})
        return False

    def _run_worker(self, job_id: str, task_id: str, reservation: int) -> bool:
        job = self.store.get_job(job_id)
        t = self.store.get_task(task_id)
        contract = t.contract
        preset = t.backend_preset or self.cfg.routing.fallback
        branch = contract["branch"]
        s = self.store.create_session(
            job_id,
            Role.WORKER,
            task_id=task_id,
            parent_session_id=job.coord_session_id,
            backend_preset=preset,
            branch=branch,
        )
        # attach the wave's reservation to this session, so the gateway sees its headroom
        self.store.x("UPDATE reservations SET session_id=? WHERE id=?", (s.id, reservation))
        try:
            image = self._image(job.repo)
        except StaleDevImage as e:
            self.budget.settle(reservation, 0.0)
            return self._fail(
                job_id,
                s,
                task_id,
                f"{task_id}: dev image not fresh",
                {"error": str(e)},
                state="waiting",
            )
        clone = self.workspace.clone(job.repo, task_id, branch=branch, base=job.base)
        self._write_job_artifacts(job_id, clone)
        self.workspace.write_task(clone, contract)
        approval = self.store.get_artifact(job_id, "approval.json")
        edits = json.loads(approval.content).get("edits") if approval else None
        packet = assemble_worker(clone, contract, untrusted={}, approval_edits=edits)
        self.store.add_event(
            "packet",
            {"role": "worker", "dropped": packet.dropped},
            Provenance.HUMAN,
            job_id=job_id,
            session_id=s.id,
            task_id=task_id,
        )
        self.store.update_task(task_id, state="running")
        spec = SessionSpec(
            session_id=s.id,
            role=Role.WORKER,
            job_id=job_id,
            task_id=task_id,
            repo=job.repo,
            preset=preset,
            model=self.cfg.preset(preset).model or "",
            clone=clone,
            session_dir=self.cfg.vigild.data_path / "sessions" / s.id,
            max_turns=60,
            max_minutes=40,
            max_budget_usd=float(contract["limits"]["max_cost_usd"]),
            mounts=self.workspace.overlays(clone),
            packet=packet.text,
            image=image,
        )
        attrs = {
            "vigil.job_id": job_id,
            "vigil.task_id": task_id,
            "vigil.role": "worker",
            "vigil.repo": job.repo,
            "vigil.tier": t.tier or "",
            "vigil.branch": branch,
            "vigil.model": spec.model,
            "vigil.attempt": int(contract.get("attempt", 1)),
        }
        out = self._run_session(s, spec, reservation, attrs)
        if out.status != "done":
            return self._fail(
                job_id,
                s,
                task_id,
                f"{task_id}: worker session {out.status}",
                {"error": out.error or ""},
            )

        art_dir = clone / ".vigil" / job_id / task_id
        ask = art_dir / "ask_coord.json"
        if ask.is_file():
            question = json.loads(ask.read_text()).get("question", "")
            self.store.create_inbox_item(
                "questions",
                "ask_coord",
                job_id,
                f"{task_id} asks its coord",
                {
                    "question": question,
                    "task_id": task_id,
                    "coord_session_id": job.coord_session_id,
                },
                Provenance.CLAUDE,
            )
            self.store.update_session(s.id, status="waiting")
            self.store.update_task(task_id, state="waiting")
            return False
        try:
            report = read_worker_report(clone, job_id, task_id)
        except ArtifactError as e:
            return self._fail(
                job_id, s, task_id, f"{task_id}: no valid worker_report.json", {"error": str(e)}
            )
        self.store.add_artifact(
            job_id,
            "worker_report.json",
            report.model_dump_json(),
            Provenance.CLAUDE,
            task_id=task_id,
        )
        harness_path = art_dir / "harness_tests.json"
        harness = json.loads(harness_path.read_text()) if harness_path.is_file() else {}
        errors = check_worker(
            clone, job.base, contract, report, harness, cost=session_cost(self.store, s.id)
        )
        if errors:
            return self._fail(
                job_id, s, task_id, f"{task_id}: stage 3 acceptance failed", {"errors": errors}
            )
        body = (
            f"{report.summary}\n\nJob `{job_id}`, task `{task_id}` (tier `{t.tier}`: "
            f"{t.tier_reason}).\n\nTest: `{contract['spec']['test_cmd']}` "
            f"{report.test_before.value} → {report.test_after.value}.\n\n"
            f"Self-check: would flag: {report.self_check.reviewer_would_flag}; not done: "
            f"{report.self_check.not_done}.\n\nOpened by vigild; a human merges."
        )
        try:
            url = self.publisher.publish(
                clone,
                repo=job.repo,
                branch=branch,
                base=job.base,
                title=f"[vigil {job_id}] {contract['spec']['goal']}",
                body=body,
                scope=list(contract["spec"]["files_in_scope"]),
            )
        except PublishError as e:
            return self._fail(job_id, s, task_id, f"{task_id}: publish refused", {"error": str(e)})
        self.store.update_session(s.id, status="pr_open", pr_url=url)
        self.store.update_task(task_id, state="pr_open")
        self.store.add_event(
            "pr_open",
            {"pr_url": url, "branch": branch},
            Provenance.HUMAN,
            job_id=job_id,
            session_id=s.id,
            task_id=task_id,
        )
        return True


# --- wiring for the real daemon ------------------------------------------------------------


class GitHubPublisher:
    """Mints a one-hour, one-repo token for each publish and revokes it after."""

    def __init__(self, app: Any, http: Any) -> None:
        self.app = app
        self.http = http

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
        from vigild.github.app import WORKER_PERMISSIONS
        from vigild.github.publish import RestPulls, publish

        with self.app.lease(repo, WORKER_PERMISSIONS) as tok:
            return publish(
                clone,
                repo=repo,
                branch=branch,
                base=base,
                title=title,
                body=body,
                pulls=RestPulls(self.http, tok.token),
                scope=scope,
                token=tok.token,
            )


class NoPublisher:
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
        raise PublishError("the GitHub App is not configured (GITHUB_APP_ID, GITHUB_APP_KEY_PATH)")


def build_runner(v: Any) -> JobRunner:
    import docker
    import httpx2

    from vigild.devimage import DockerImages
    from vigild.executors.runtime import DockerRuntime
    from vigild.github.app import GitHubApp

    client = docker.from_env()
    publisher: Publisher = NoPublisher()
    app_id, key_path = v.secrets.get("GITHUB_APP_ID"), v.secrets.get("GITHUB_APP_KEY_PATH")
    if app_id and key_path:
        http = httpx2.Client(timeout=30)
        app = GitHubApp(
            app_id,
            Path(key_path).expanduser().read_bytes(),
            http=http,
            claude_mods=v.cfg.vigild.github.claude_mods,
            allowed_repos=list(v.cfg.repos.repos),
        )
        publisher = GitHubPublisher(app, http)
    runner = JobRunner(
        v.cfg,
        v.store,
        v.budget,
        v.gateway,
        DockerRuntime(v.cfg, client),
        Workspace(v.cfg.vigild.data_path),
        publisher,
        v.telemetry,
        DevImages(v.cfg, v.store, DockerImages(client)),
    )
    runner.jobs = v.services.jobs
    return runner
