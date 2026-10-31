"""#136 fix round 1: which ACs a worker's text names, and which ACs a worker answers for."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vigild.jobs.acceptance import live_workers, worker_acs
from vigild.jobs.artifacts import ac_refs, parse_plan, parse_spec


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("AC1 holds", {"AC1"}),
        ("ac2", {"AC2"}),
        ("AC1\u2013AC3", {"AC1", "AC2", "AC3"}),
        ("AC1-AC3", {"AC1", "AC2", "AC3"}),
        ("ACs 1-2", {"AC1", "AC2"}),
        ("ACs 1, 3", {"AC1", "AC3"}),
        ("ACs 1, 2 and 4", {"AC1", "AC2", "AC4"}),
        ("AC1, AC4", {"AC1", "AC4"}),
        ("AC1 and AC2 hold", {"AC1", "AC2"}),
        ("AC10 is not AC1", {"AC10", "AC1"}),
        ("AC1, 5 files", {"AC1"}),
        ("the extra doc", set()),
        ("BAC1 or AC", set()),
        ("AC1 through AC3", {"AC1", "AC2", "AC3"}),  # #139 round 2
        ("AC1..AC3", {"AC1", "AC2", "AC3"}),
        ("AC-2 and AC#3", {"AC2", "AC3"}),
        ("ac12b", set()),
    ],
)
def test_ac_refs(text: str, want: set[str]) -> None:
    assert ac_refs(text) == want


def _task(tid: str, state: str, why: str, shape: str | None = None) -> SimpleNamespace:
    contract = {"why": why, "spec": {"done_when": ""}, **({"shape": shape} if shape else {})}
    return SimpleNamespace(id=tid, state=state, contract=contract)


def test_only_live_worker_tasks_count() -> None:
    tasks = [
        _task("a", "superseded", "AC1"),
        _task("b", "abandoned", "AC2"),
        _task("c", "deps_pending", "x", shape="deps"),
        _task("d", "building", "AC3"),
    ]
    assert [t.id for t in live_workers(tasks)] == ["d"]


def test_a_one_worker_job_runs_every_ac() -> None:
    assert worker_acs(["AC1", "AC2"], ["AC1"], "AC1") is None


def test_a_worker_of_several_runs_what_it_names_and_what_nobody_names() -> None:
    idents = ["AC1", "AC2", "AC3"]
    texts = {"w1": "AC1", "w2": "AC2"}
    assert worker_acs(idents, list(texts.values()), texts["w1"]) == {"AC1", "AC3"}
    assert worker_acs(idents, list(texts.values()), texts["w2"]) == {"AC2", "AC3"}


def _spec(n: int) -> str:
    items = "".join(f"- AC{i}: s. test: `pytest -q tests/t{i}.py`\n" for i in range(1, n + 1))
    return (
        "# S\n\n## Goal\ng\n\n## Non-goals\n- n\n\n## Acceptance criteria\n"
        f"{items}\n## Files in scope\n- `docs/a.md`\n\n## Files out of scope\n- none\n\n"
        "## Money paths\nnone\n\n## Interfaces\n- none\n\n## Risks\n- none\n\n## Rollback\nr\n"
    )


def _plan(*whys: str) -> str:
    import json

    ws = [
        {
            "task_id": f"j-w{i}", "goal": "g", "why": why, "value": 3, "risk": 1, "size": "XS",
            "test_cmd": "pytest -q tests/t1.py", "done_when": "it holds",
            "files_in_scope": [f"docs/a{i}.md"], "labels": ["docs"],
        }
        for i, why in enumerate(whys, start=1)
    ]  # fmt: skip
    verify = [{"criterion": f"AC{i}", "level": 0, "why_not_higher": "doc"} for i in range(1, 4)]
    return f"# Plan\n\n## Workers\n```json\n{json.dumps({'workers': ws, 'verify': verify})}\n```\n"


def test_the_spec_gate_refuses_a_plan_where_an_ac_is_named_by_no_worker() -> None:
    from vigild.intake.spec_gate import check_job_spec

    spec = _spec(3).replace("`docs/a.md`", "`docs/**`")
    errors = check_job_spec(parse_spec(spec), parse_plan(_plan("AC1", "AC2")), [])
    assert "AC3 is named by no worker's why or done_when" in " ".join(errors)
    ok = check_job_spec(parse_spec(spec), parse_plan(_plan("AC1\u2013AC2", "AC3")), [])
    assert not [e for e in ok if "named by no worker" in e]
    one = check_job_spec(parse_spec(spec), parse_plan(_plan("nothing")), [])
    assert not [e for e in one if "named by no worker" in e]


# --- #143: the gate counts the published tasks a re-plan keeps ------------------------------


def test_kept_workers() -> None:
    from vigild.jobs.acceptance import kept_workers

    tasks = [
        _task("w1", "merged", "AC1"),
        _task("w2", "building", "AC2"),
        _task("w3", "superseded", "AC3"),
        _task("w4", "awaiting_approval", "AC3"),
        _task("w5", "deps_pending", "x", shape="deps"),
    ]
    assert [t.id for t in kept_workers(tasks, {"w2"})] == ["w1"]


def test_gate_and_runtime_agree() -> None:
    from vigild.intake.spec_gate import check_job_spec

    spec = _spec(2).replace("`docs/a.md`", "`docs/**`")
    plan = parse_plan(_plan("nothing"))
    kept = [_task("k", "merged", "AC1")]
    texts = [
        __import__("vigild.jobs.acceptance", fromlist=["x"]).contract_text(t.contract) for t in kept
    ]
    errors = check_job_spec(parse_spec(spec), plan, [], kept_texts=texts)
    assert any("AC2 is named by no worker" in e for e in errors)
    # runtime: the new worker answers for AC2, which nobody names; kept answers AC1
    from vigild.jobs.acceptance import contract_text

    mine = contract_text({"why": "nothing", "spec": {}})
    assert worker_acs(["AC1", "AC2"], [*texts, mine], mine) == {"AC2"}


def test_service_gate_counts_kept_tasks() -> None:
    from vigild.config import Config  # noqa: F401
    from vigild.jobs.service import JobService

    svc = JobService.__new__(JobService)
    svc.store = SimpleNamespace(list_tasks=lambda job_id: [_task("k", "merged", "AC1")])  # type: ignore[assignment]
    svc.cfg = SimpleNamespace(routing=SimpleNamespace(money_paths=[]))  # type: ignore[assignment]
    svc.files = None
    svc.dirs = None
    svc._used_task_ids = lambda job_id: []  # type: ignore[method-assign]
    import vigild.jobs.service as mod

    mod.missing_tools = lambda cfg, repo, cmd: []  # type: ignore[assignment]
    spec = _spec(2).replace("`docs/a.md`", "`docs/**`")
    errors = svc._gate("o/r", spec, _plan("nothing"), "main", "j")
    assert any("AC2 is named by no worker" in e for e in errors), errors
