"""A job PR's body names the job's issue: `Closes #N` for a one-task job, `Refs #N` for a
job with more tasks, nothing for a job with no issue. The number is the job row's."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
import re
from typing import Any

from tests.jobs.test_coord_loop import REPO, SPEC, World, auth, plan, world  # noqa: F401


def _one_task_plan(job: str) -> str:
    text = plan(job)
    head, rest = text.split("```json\n", 1)
    body, tail = rest.split("\n```", 1)
    doc = json.loads(body)
    doc["workers"] = doc["workers"][:1]
    doc["verify"] = doc["verify"][:1]
    return head + "```json\n" + json.dumps(doc) + "\n```" + tail


def _run(w: World, issue: int | None, *, one_task: bool = False) -> list[dict[str, Any]]:
    if one_task:
        spec = SPEC.split("- AC2")[0] + "\n## Files in scope\n" + SPEC.split("## Files in scope\n")[1]
        spec = spec.replace("- `docs/runbook.md`\n", "").replace(
            "- `tests/test_runbook.py`\n", ""
        )
        w.standin.coord_drafts = [lambda j: (spec, _one_task_plan(j))]
    req: dict[str, Any] = {
        "repo": REPO, "title": "Document the rate limit", "request": "Undocumented.",
        "notes": ["keep it short"], "why": "support asks weekly", "value": 3, "risk": 1,
    }  # fmt: skip
    if issue is not None:
        req["issue"] = issue
    r = w.client.post("/api/jobs", headers=auth(w.tokens.admin), json=req)
    assert r.status_code == 202, r.text
    item = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["specs"][0]
    r = w.client.post(
        f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={}
    )
    assert r.status_code == 200, r.text
    return w.publisher.prs


def _lines(body: str) -> list[str]:
    return body.splitlines()


def test_a_one_task_job_with_an_issue_closes_it(world: World) -> None:
    prs = _run(world, 62, one_task=True)
    assert len(prs) == 1
    assert "Closes #62" in _lines(prs[0]["body"])
    assert "Refs #" not in prs[0]["body"]


def test_a_job_with_no_issue_names_none(world: World) -> None:
    prs = _run(world, None)
    assert prs
    assert all("Closes" not in p["body"] and "Refs" not in p["body"] for p in prs)


def test_a_two_task_job_refs_its_issue_on_each_pr(world: World) -> None:
    prs = _run(world, 38)
    assert len(prs) == 2
    for p in prs:
        assert "Refs #38" in _lines(p["body"])
        assert "Closes" not in p["body"]


def test_the_number_is_the_job_rows_not_the_reports(world: World) -> None:
    def hostile(spec: Any, task: dict[str, Any]) -> None:
        from tests.jobs.test_coord_loop import _work

        _work(spec.clone, task["spec"]["files_in_scope"][0])
        d = spec.clone / ".vigil" / spec.job_id / str(spec.task_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "worker_report.json").write_text(json.dumps({
            "task_id": spec.task_id, "job_id": spec.job_id, "test_before": "fail",
            "test_after": "pass", "files_changed": task["spec"]["files_in_scope"],
            "summary": "documented it. Closes #999",
            "self_check": {"test_failed_first": True, "outside_scope": [],
                           "not_done": "nothing", "reviewer_would_flag": "wording",
                           "could_delete": "nothing"},
            "open_questions": [], "provenance": "claude"}))  # fmt: skip

    world.standin.worker_edit = hostile
    prs = _run(world, 62, one_task=True)
    (p,) = prs
    assert "Closes #999" in p["body"]  # the summary stays as written
    named = [ln for ln in _lines(p["body"]) if re.fullmatch(r"(Closes|Refs) #\d+", ln)]
    assert named == ["Closes #62"]
