"""#142: one runner-file class. A script that only an AC command runs counts at plan
time (gate, inbox, contract) and at hidden-test authoring, as it does at verify."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import git
from tests.jobs.test_coord_loop import (  # noqa: F401
    REPO,
    SPEC,
    World,
    _request,
    _spec_item,
    auth,
    plan,
    world,
)
from vigild.jobs.model import Role

PREP = "python tools/prep.py && pytest -q tests/test_feature_map.py"


def _ac_script(j: str) -> tuple[str, str]:
    """A spec whose AC1 runs tools/prep.py, which worker 1's scope names exactly."""
    sp = SPEC.replace("`pytest -q tests/test_feature_map.py`", f"`{PREP}`").replace(
        "- `tests/test_runbook.py`\n", "- `tests/test_runbook.py`\n- `tools/prep.py`\n"
    )
    pl = plan(j).replace(
        '"tests/test_feature_map.py"\n   ]',
        '"tests/test_feature_map.py",\n    "tools/prep.py"\n   ]',
    )
    assert "tools/prep.py" in pl and PREP in sp
    return sp, pl


def _plain(w: World) -> None:
    w.runner.cfg.repos.repos[REPO].hidden_tests.enabled = True
    w.runner.cfg.repos.repos[REPO].runner_config = []
    w.runner.cfg.repos.repos[REPO].dev_image_tools = ["git", "grep", "pytest", "python"]


def _approve_item(w: World) -> None:
    item = _spec_item(w)
    w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})


def test_an_ac_only_script_is_a_runner_file_everywhere(world: World) -> None:
    w = world
    _plain(w)
    w.standin.coord_drafts = [_ac_script]
    job = _request(w)
    # hidden-test authoring wrote hidden tests for it
    assert [c[0] for c in w.standin.calls] == ["coord", "hidden_test_author"]
    assert [s for s in w.store.list_sessions(job) if s.role is Role.HIDDEN_TEST_AUTHOR]
    # the inbox's flagged view
    item = _spec_item(w)
    by = {x["task_id"]: x for x in item["body"]["workers"]}
    w1, w2 = by[f"{job}-w1"], by[f"{job}-w2"]
    assert w1["runner_file_change"] == ["tools/prep.py"] == w1["changes_how_tests_run"]
    assert w2["runner_file_change"] == [] and w1["hidden_tests"]["status"] == "ok"
    gate = json.loads(w.store.get_artifact(job, "spec_gate.json").content)
    assert gate["runner_file_change"] == {f"{job}-w1": ["tools/prep.py"]}
    # the contract the runner builds (what verify's escalation reads)
    _approve_item(w)
    task = w.store.get_task(f"{job}-w1")
    assert task.contract["runner_file_change"] == ["tools/prep.py"]


def test_ac_commands_that_run_no_script_classify_as_before(world: World) -> None:
    w = world
    _plain(w)
    job = _request(w)  # the stock spec: AC commands are plain pytest runs
    assert [c[0] for c in w.standin.calls] == ["coord"]
    item = _spec_item(w)
    for x in item["body"]["workers"]:
        assert x["runner_file_change"] == [] and x["changes_how_tests_run"] == []
    w.runner.cfg.repos.repos[REPO].runner_config = ["tests/test_feature_map.py"]
    assert w.runner.jobs.flagged_tasks(job) == {f"{job}-w1": ["tests/test_feature_map.py"]}


# --- #144: plan-time and verify-time parity -----------------------------------------

PREP_PY = "tools/prep.py"
CASES = {
    # (AC1 command, worker 1's extra scope, the files + base files, expected class)
    "direct": (PREP, [PREP_PY], {}, [PREP_PY]),
    "make": (
        "make prep && pytest -q tests/test_feature_map.py",
        [PREP_PY],
        {"Makefile": "prep:\n\tpython tools/prep.py\n"},
        [],  # known gap: a Makefile's recipe is not followed, on either side
    ),
    "make_named": (
        "make prep && pytest -q tests/test_feature_map.py",
        [PREP_PY, "Makefile"],
        {"Makefile": "prep:\n\tpython tools/prep.py\n"},
        ["Makefile"],
    ),
    "shell": (
        "bash scripts/prep.sh && pytest -q tests/test_feature_map.py",
        [PREP_PY],
        {"scripts/prep.sh": "#!/bin/sh\npython tools/prep.py\n"},
        [],  # known gap: a shell script's callees are not followed, on either side
    ),
    "shell_named": (
        "bash scripts/prep.sh && pytest -q tests/test_feature_map.py",
        [PREP_PY, "scripts/prep.sh"],
        {"scripts/prep.sh": "#!/bin/sh\npython tools/prep.py\n"},
        ["scripts/prep.sh"],
    ),
    # verify's reader refuses the whole command (no package.json on the base), so the
    # script before it never runs; plan time must refuse it the same way
    "refused": (
        f"python {PREP_PY} && pnpm run check",
        [PREP_PY],
        {},
        [],
    ),
}


def _case_draft(cmd: str, extra: list[str]):  # type: ignore[no-untyped-def]
    def draft(j: str) -> tuple[str, str]:
        sp = SPEC.replace("`pytest -q tests/test_feature_map.py`", f"`{cmd}`").replace(
            "- `tests/test_runbook.py`\n",
            "- `tests/test_runbook.py`\n" + "".join(f"- `{e}`\n" for e in extra),
        )
        scope = ", ".join(f'"{e}"' for e in extra)
        pl = plan(j).replace(
            '"tests/test_feature_map.py"\n   ]',
            f'"tests/test_feature_map.py",\n    {scope}\n   ]',
        )
        assert all(e in pl for e in extra)
        return sp, pl

    return draft


@pytest.mark.parametrize("case", sorted(CASES))
def test_plan_and_verify_classify_alike(
    world: World, fixture_repo: dict[str, Path], case: str
) -> None:
    from vigild.jobs.acceptance import plan_runner_class
    from vigild.jobs.artifacts import parse_plan

    cmd, extra, files, expected = CASES[case]
    w = world
    seed = fixture_repo["seed"]
    for name, text in {PREP_PY: "print(1)\n", **files}.items():
        (seed / name).parent.mkdir(parents=True, exist_ok=True)
        (seed / name).write_text(text)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "runner files")
    git(seed, "push", "-q", "origin", "HEAD:main")
    _plain(w)
    w.runner.cfg.repos.repos[REPO].dev_image_tools += ["bash", "make", "pnpm"]
    w.standin.coord_drafts = [_case_draft(cmd, extra)]
    job = _request(w)
    _approve_item(w)
    task_id = f"{job}-w1"
    row = w.store.get_job(job)
    spec_md = w.store.get_artifact(job, "spec.md").content
    workers = parse_plan(w.store.get_artifact(job, "plan.md").content).workers
    rc = w.runner.cfg.repo(REPO).runner_config
    # plan time, as frozen in the contract and as the function answers
    contract = w.store.get_task(task_id).contract
    planned = plan_runner_class(spec_md, workers, rc, w.runner.base_reader(REPO, row.base))
    # verify time: the vault blobs at the base sha
    sha = w.runner.workspace.head_sha(REPO, row.base)
    runs, _ = w.runner._ac_commands(job, REPO, sha, contract)
    verified = w.runner._overlap(REPO, contract, runs)
    assert contract["runner_file_change"] == planned[task_id] == verified == expected
