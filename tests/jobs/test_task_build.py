"""`JobRunner._task` sets `has_existing_tests` from the base mirror, never None, so
routing rules 4 and 6 can fire (#100)."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.conftest import auth, git
from tests.jobs.test_coord_loop import REPO, SPEC, World, plan, world  # noqa: F401
from vigild import config as config_mod
from vigild.contract.models import WorkerContract
from vigild.jobs.runner import JobRunner
from vigild.router.rules import route

JOB = "vi-0001"


class FakeWorkspace:
    """A mirror that answers from a dict of path -> text."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def mirror_file(self, repo: str, branch: str, path: str) -> str | None:
        return self.files.get(path)

    def mirror_paths(self, repo: str, branch: str) -> set[str]:
        return set(self.files)


def _runner(files: dict[str, str]) -> JobRunner:
    r = object.__new__(JobRunner)
    r.cfg = config_mod.load()
    r.workspace = FakeWorkspace(files)  # type: ignore[assignment]
    return r


def _w(scope: list[str], **kw: Any) -> WorkerContract:
    return WorkerContract.model_validate({
        "task_id": f"{JOB}-w1", "goal": "g", "why": "w", "value": 3, "risk": 2, "size": "S",
        "test_cmd": "pytest -q", "done_when": "green", "files_in_scope": scope, **kw,
    })  # fmt: skip


def build(files: dict[str, str], scope: list[str], **kw: Any) -> Any:
    runner = _runner(files)
    return runner, runner._task(JOB, "thomasbardhi01/vigil", "main", "human", _w(scope, **kw))


def test_an_in_scope_test_file_at_the_base() -> None:
    _, t = build({"tests/test_a.py": "x"}, ["tests/test_a.py", "vigild/a.py"])
    assert t.has_existing_tests is True


def test_a_source_file_with_a_related_test_and_a_new_test() -> None:
    files = {"tests/test_workspace.py": "x", "vigild/workspace.py": "x"}
    _, t = build(files, ["vigild/workspace.py", "tests/jobs/test_new_thing.py"])
    assert t.has_existing_tests is True


def test_vi_0004_exact_shape_existing_conftest_and_a_new_test() -> None:
    files = {"tests/security/conftest.py": "x"}
    scope = ["tests/security/conftest.py", "tests/security/test_teardown_labels.py"]
    _, t = build(files, scope, labels=["tests"], size="S")
    assert t.has_existing_tests is True


def test_only_new_test_files_in_scope() -> None:
    _, t = build({"vigild/a.py": "x"}, ["tests/test_new.py", "tests/jobs/test_other.py"])
    assert t.has_existing_tests is False


def test_no_test_file_anywhere() -> None:
    _, t = build({"vigild/a.py": "x"}, ["vigild/a.py", "docs/a.md"])
    assert t.has_existing_tests is False


def test_no_mirror_globs_and_absent_paths_are_false() -> None:
    _, t = build({}, ["vigild/a.py", "tests/test_a.py"])
    assert t.has_existing_tests is False
    _, t = build({"tests/test_a.py": "x"}, ["tests/**", "vigild/*.py"])
    assert t.has_existing_tests is False


def test_a_test_only_in_the_clone_is_not_at_the_base() -> None:
    """The mirror is the base; a worker's own new test never counts."""
    _, t = build({"vigild/a.py": "x"}, ["vigild/a.py", "tests/test_a.py"])
    assert t.has_existing_tests is False


def test_a_related_test_at_the_base_versus_only_in_the_clone() -> None:
    at_base = {"vigild/a.py": "x", "tests/sub/test_a_more.py": "x"}
    _, t = build(at_base, ["vigild/a.py"])
    assert t.has_existing_tests is True
    _, t = build({"vigild/a.py": "x", "other/test_a.py": "x"}, ["vigild/a.py"])
    assert t.has_existing_tests is False  # not under tests/
    _, t = build({"vigild/a.py": "x"}, ["vigild/a.py"])
    assert t.has_existing_tests is False


def test_a_real_mirror_lists_paths(world: World) -> None:
    ws = world.runner.workspace
    assert ws.mirror_paths(REPO, "main") == set()  # no mirror yet
    ws.mirror(REPO)
    paths = ws.mirror_paths(REPO, "main")
    assert {"README.md", "docs/runbook.md"} <= paths
    assert ws.mirror_paths(REPO, "main;rm") == set()
    assert ws.mirror_paths(REPO, "nope") == set()


def test_rules_fire_on_built_tasks() -> None:
    cfg = config_mod.load()
    runner = _runner({"tests/test_a.py": "x"})
    vigil = "thomasbardhi01/vigil"
    t = runner._task(JOB, vigil, "main", "human", _w(["tests/test_a.py"], labels=["tests"]))
    r = route(t, cfg)
    assert r.tier_reason.startswith("rule6") and r.preset == "tower-qwen"
    f = _w(["vigild/new.py"], labels=["feature"], size="M")
    t = _runner({})._task(JOB, vigil, "main", "human", f)
    assert route(t, cfg).tier_reason == "rule4:new-feature-no-tests"


def test_a_tests_job_routes_to_the_tower_through_the_api(world: World, tmp_path: Path) -> None:
    w = world
    seed = Path(str(tmp_path / "seed"))
    (seed / "tests").mkdir(exist_ok=True)
    (seed / "tests" / "test_runbook.py").write_text("def test_x():\n    assert True\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "a test")
    git(seed, "push", "-q", "origin", "main")
    w.runner.cfg.repos.repos[REPO].backends.append("tower-qwen")

    def draft(job: str) -> tuple[str, str]:
        doc = json.loads(plan(job).split("```json\n")[1].split("\n```")[0])
        for x in doc["workers"]:
            x["labels"], x["size"] = ["tests"], "S"
        body = json.dumps(doc, indent=1)
        return SPEC, plan(job).split("```json\n")[0] + "```json\n" + body + "\n```\n"

    w.standin.coord_drafts.append(draft)
    r = w.client.post(
        "/api/jobs",
        headers=auth(w.tokens.admin),
        json={"repo": REPO, "title": "t", "request": "r", "why": "w", "value": 3, "risk": 1},
    )
    assert r.status_code == 202, r.text
    job = str(r.json()["id"])
    (item,) = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["specs"]
    a = w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})
    assert a.status_code == 200, a.text
    t2 = w.store.get_task(f"{job}-w2")  # its scope has tests/test_runbook.py, at the base
    assert t2.tier_reason is not None and t2.tier_reason.startswith("rule6")
    assert t2.backend_preset == "tower-qwen"
    t1 = w.store.get_task(f"{job}-w1")  # no test at the base for it
    assert t1.tier_reason == "rule9:default"
