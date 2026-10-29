"""vigild pre-fills the mechanical parts of the spec (ADR-0005 part 5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vigild import config as config_mod
from vigild.config import RepoPolicy
from vigild.gitsafe import git
from vigild.intake.spec_gate import check_job_spec
from vigild.jobs.artifacts import SpecDoc, parse_plan, parse_spec
from vigild.packets.assemble import assemble_coord_classic, assemble_coord_lean
from vigild.packets.fence import FENCE_RE
from vigild.packets.prefill import TODO, compute_prefill

MONEY = ["**/budget.py"]
FILES = {
    "CLAUDE.md": "# Rules\n",
    "vigild/jobs/runner.py": "X = 1\n",
    "vigild/budget.py": "CAP = 1\n",
    "vigild/other.py": "Y = 1\n",
    "tests/jobs/test_runner.py": "def test_a(): ...\n",
    "tests/jobs/test_runner_more.py": "def test_b(): ...\n",
    "tests/jobs/test_round2_runner.py": "def test_c(): ...\n",
    "tests/test_budget.py": "def test_d(): ...\n",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "clone"
    r.mkdir()
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    git(r, "config", "user.email", "t@vigil.invalid")
    git(r, "config", "user.name", "t")
    for rel, text in FILES.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text)
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "seed")
    return r


def policy(**over: Any) -> RepoPolicy:
    base = config_mod.load().repo("thomasbardhi01/vigil")
    return base.model_copy(update=over)


def request(text: str) -> dict[str, Any]:
    return {"job_id": "vi-0001", "title": "t", "request": text, "notes": []}


NAMES = "Change `vigild/jobs/runner.py` and `vigild/budget.py`."


def test_runner_and_money_files_are_listed_by_the_policy(repo: Path) -> None:
    pol = policy(runner_config=["vigild/jobs/runner.py"])
    pre = compute_prefill(repo, request(NAMES), policy=pol, money_globs=MONEY)
    assert pre.candidates == ["vigild/jobs/runner.py", "vigild/budget.py"]
    assert pre.runner_files == ["vigild/jobs/runner.py"]
    assert pre.money_paths == ["vigild/budget.py"]
    assert pre.pinned_paths == ["vigild/budget.py"]  # the vigil repo's ladder_pinned_paths
    assert set(pre.test_cmds) >= set(pol.dev_suites.values())
    assert "uv run --offline pytest -q tests/jobs/test_runner.py" in pre.test_cmds
    assert "uv run --offline pytest -q tests/jobs/test_runner_more.py" in pre.test_cmds
    assert "uv run --offline pytest -q tests/test_budget.py" in pre.test_cmds
    assert not [c for c in pre.test_cmds if "round2" in c]  # not test_runner*


def test_a_file_is_a_runner_file_only_if_the_policy_says_so(repo: Path) -> None:
    pre = compute_prefill(repo, request(NAMES), policy=policy(runner_config=[]), money_globs=MONEY)
    assert pre.runner_files == []


def test_a_path_missing_at_base_is_dropped_with_a_note(repo: Path) -> None:
    text = NAMES + " Also `vigild/nope.py`, `vigild/gateway/**`, e.g. this."
    pre = compute_prefill(repo, request(text), policy=policy(), money_globs=MONEY)
    assert "vigild/nope.py" not in pre.candidates
    assert any("vigild/nope.py" in d and "no such file" in d for d in pre.dropped)
    assert any("vigild/gateway/**" in d and "glob" in d for d in pre.dropped)
    assert not any("e.g" in d for d in pre.dropped)  # prose is not a path
    assert "vigild/nope.py" in pre.body()


def test_paths_come_from_the_issue_too(repo: Path) -> None:
    pre = compute_prefill(
        repo, request("fix it"), policy=policy(), money_globs=MONEY, issue="see vigild/other.py"
    )
    assert pre.candidates == ["vigild/other.py"]


def test_a_symlink_out_of_the_clone_is_not_a_candidate(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("s")
    (repo / "link.txt").symlink_to(tmp_path / "secret.txt")
    pre = compute_prefill(repo, request("`link.txt`"), policy=policy(), money_globs=MONEY)
    assert pre.candidates == []


def test_the_section_is_fenced_and_carries_the_rules(repo: Path) -> None:
    pre = compute_prefill(repo, request(NAMES), policy=policy(), money_globs=MONEY)
    text = pre.section("vi-0001", skeleton=True)
    fenced = [m for m in FENCE_RE.finditer(text) if m.group(1) == "prefill"]
    assert len(fenced) == 1 and "`vigild/budget.py`" in fenced[0].group(3)
    assert "Exact files only" in text and "inside spec.md" in text and "Money paths" in text
    assert "changelog" in text and ".vigil/vi-0001/spec.md" in text
    assert ".vigil/vi-0001/spec.md" not in pre.section("vi-0001", skeleton=False)


def test_the_skeleton_follows_the_spec_format(repo: Path) -> None:
    pre = compute_prefill(repo, request(NAMES), policy=policy(), money_globs=MONEY)
    spec = parse_spec(pre.spec_md("A title"))
    assert spec.files_in_scope == pre.candidates and spec.money_paths == ["vigild/budget.py"]
    assert spec.sections["Goal"].strip() == TODO and spec.sections["Risks"].strip() == TODO
    assert TODO in spec.sections["Acceptance criteria"]
    plan = pre.plan_md("vi-0001")
    assert "## Notes addressed" in plan and "## Workers" in plan
    assert '"files_in_scope"' in plan and "vigild/jobs/runner.py" in plan
    assert parse_plan(plan).errors  # a skeleton: the coord fills in the rest


def _drafted(spec_files: list[str], money: list[str]) -> SpecDoc:
    return SpecDoc(sections={}, files_in_scope=spec_files, money_paths=money)


def _scope_errors(spec: SpecDoc, worker_scope: list[str]) -> list[str]:
    plan = parse_plan(
        '## Workers\n```json\n{"workers": [{"task_id": "vi-0001-w1", "goal": "g", "why": "w",'
        ' "value": 3, "risk": 1, "size": "XS", "test_cmd": "pytest -q tests/test_budget.py",'
        ' "done_when": "d", "files_in_scope": ' + str(worker_scope).replace("'", '"') + "}],"
        ' "verify": []}\n```\n'
    )
    return [
        e for e in check_job_spec(spec, plan, MONEY) if "is outside spec.md's files in scope" in e
    ]


def test_the_pa_0003_shape_passes_the_scope_rule_with_the_prefill(repo: Path) -> None:
    """A coord that keeps the skeleton's scope, with a worker on a subset, passes the
    first draft's scope rule; one that writes its own narrower scope fails it."""
    pre = compute_prefill(repo, request(NAMES), policy=policy(), money_globs=MONEY)
    kept = parse_spec(pre.spec_md("t"))
    assert _scope_errors(kept, ["vigild/budget.py"]) == []
    assert _scope_errors(kept, pre.candidates) == []
    # today: the coord guesses its scope and a worker strays outside it
    own = _drafted(["vigild/budget.py"], ["vigild/budget.py"])
    assert _scope_errors(own, ["vigild/budget.py", "tests/test_budget.py"]) != []


def _packets(repo: Path, pre: Any) -> dict[str, str]:
    req = request(NAMES)
    out = {}
    for name, fn, kw in (
        ("classic", assemble_coord_classic, {}),
        ("lean", assemble_coord_lean, {}),
        ("fresh", assemble_coord_classic, {"fresh": True}),
    ):
        out[name] = fn(repo, req, untrusted={}, prefill=pre, **kw).text
    return out


def test_classic_lean_and_fresh_packets_all_carry_the_prefill(repo: Path) -> None:
    pre = compute_prefill(repo, request(NAMES), policy=policy(), money_globs=MONEY)
    for name, text in _packets(repo, pre).items():
        assert "<<<UNTRUSTED prefill " in text, name
        assert "`vigild/budget.py`" in text and "Exact files only" in text, name


def test_a_packet_without_a_prefill_is_unchanged(repo: Path) -> None:
    text = assemble_coord_classic(repo, request(NAMES), untrusted={}).text
    assert "3b. Prefill" not in text and "UNTRUSTED prefill" not in text
