"""Per-row docs (#96 part 1): the loader, the generator, the checks, and the
two-order merge that is the issue's done-when."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from vigild import docs_rows

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_").removesuffix(".py"), ROOT / "scripts" / name
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("gen-docs-tables.py")
fm = _load("check-feature-map.py")
ds = _load("check-docs-same-pr.py")

HEAD = "| ID | Feature | Phase | What it does | Entry points | Core code | Guardrails | Tests | Status |"
MAP = f"# Map\n\n{HEAD}\n|---|---|---|---|---|---|---|---|---|\n| m-row | M | 1 | old | — | — | — | — | planned (phase 2) |\n"


def feature_file(slug: str, *, phase: str = "2", body: str = "Does a thing.") -> str:
    return (
        f"---\nid: {slug}\nfeature: Feature {slug}\nphase: '{phase}'\nentry_points: '`GET /api/{slug}`'\n"
        f"core_code: '`vigild/{slug}.py`'\nguardrails: —\ntests: '`tests/test_{slug}.py`'\n"
        f"status: planned (phase 3)\n---\n{body}\n"
    )


def decision_file(slug: str) -> str:
    return (
        f"---\nid: {slug}\nchoice: Choice {slug}\npicked: Picked {slug}\n---\nBecause | reasons.\n"
    )


def _root(tmp: Path) -> Path:
    (tmp / "docs" / "features").mkdir(parents=True)
    (tmp / "docs" / "decisions" / "arch").mkdir(parents=True)
    (tmp / "docs" / "feature-map.md").write_text(MAP)
    (tmp / "docs" / "architecture.md").write_text("# Arch\n")
    return tmp


def test_generator_renders_files_and_table_rows_sorted(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "docs/features/zeta.md").write_text(feature_file("zeta"))
    (root / "docs/features/alpha.md").write_text(feature_file("alpha", body="Has a | pipe."))
    out = gen.render(root, "features")
    lines = out.splitlines()
    assert lines[0] == HEAD
    assert lines[1] == "|---|---|---|---|---|---|---|---|---|"
    assert [ln.split(" | ")[0] for ln in lines[2:]] == ["| alpha", "| m-row", "| zeta"]
    assert (
        "| alpha | Feature alpha | 2 | Has a \\| pipe. | `GET /api/alpha` | `vigild/alpha.py` "
        "| — | `tests/test_alpha.py` | planned (phase 3) |"
    ) in lines


def test_generator_renders_decisions(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "docs/decisions/arch/x.md").write_text(decision_file("x"))
    out = gen.render(root, "decisions")
    assert out.splitlines()[0] == "| ID | Choice | Picked | Why |"
    assert out.splitlines()[2] == "| x | Choice x | Picked x | Because \\| reasons. |"


def test_loader_merges_both_formats_and_refuses_a_slug_in_both(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "docs/features/a.md").write_text(feature_file("a"))
    assert [r["ID"] for r in docs_rows.merged_rows(root, "features")] == ["a", "m-row"]
    (root / "docs/features/m-row.md").write_text(feature_file("m-row"))
    with pytest.raises(docs_rows.DuplicateSlug, match="m-row"):
        docs_rows.merged_rows(root, "features")


@pytest.mark.parametrize(
    ("name", "text", "needle"),
    [
        ("a.md", "no front matter\n", "front matter"),
        ("a.md", feature_file("b"), "slug"),
        ("a.md", feature_file("a").replace("tests: ", "xtests: "), "tests"),
        ("a.md", feature_file("a").replace("planned (phase 3)", "wat"), "status"),
    ],
)
def test_check_feature_map_fails_on_a_malformed_row_file(
    tmp_path: Path, name: str, text: str, needle: str
) -> None:
    root = _root(tmp_path)
    (root / "docs/features" / name).write_text(text)
    errors = fm.check(root, code_dirs=[])
    assert any("docs/features/a.md" in e and needle in e for e in errors), errors


def test_check_feature_map_passes_a_good_row_file_and_reads_its_routes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "docs/features/a.md").write_text(feature_file("a"))
    (root / "docs/decisions/arch/d.md").write_text(decision_file("d"))
    assert fm.check(root, code_dirs=[]) == []
    (root / "pkg").mkdir()
    (root / "pkg/api.py").write_text('app.get("/api/a")\napp.get("/api/zzz")\n')
    errors = fm.check(root, code_dirs=["pkg"])
    assert errors == ["route GET /api/zzz is in code but in no feature-map row"]


def test_check_feature_map_fails_a_malformed_decision_file(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "docs/decisions/arch/d.md").write_text(decision_file("e"))
    assert any(
        "docs/decisions/arch/d.md" in e and "slug" in e for e in fm.check(root, code_dirs=[])
    )


def test_a_cited_decision_may_be_a_row_file(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "docs/decisions/arch/d.md").write_text(decision_file("d"))
    (root / "docs/runbook.md").write_text("See decision `d`.\n")
    assert fm.check(root, code_dirs=[]) == []


def test_docs_same_pr_accepts_a_decision_row_as_the_architecture_update() -> None:
    changed = ["vigild/gateway/service.py"]
    assert ds.check(changed) != []
    assert ds.check([*changed, "docs/decisions/arch/x.md"]) == []


def test_a_feature_row_alone_is_not_an_architecture_update() -> None:
    """Owner review of #211: a feature-map row says what a feature does, not how a
    flow works; only docs/architecture.md or a decision row counts."""
    assert ds.check(["vigild/jobs/fsm.py", "docs/features/x.md"]) != []
    assert ds.check(["vigild/jobs/fsm.py", "docs/features/x.md", "docs/architecture.md"]) == []


def _git(cwd: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(cwd),
    }
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def test_two_prs_each_adding_a_feature_and_a_decision_merge_in_either_order(
    tmp_path: Path,
) -> None:
    repo = _root(tmp_path / "r")
    _git(repo, "init", "-q", "-b", "main")
    (repo / "docs/features/.keep").write_text("")
    (repo / "docs/decisions/arch/.keep").write_text("")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    for name in ("a", "b"):
        _git(repo, "checkout", "-qb", f"pr-{name}", "main")
        (repo / f"docs/features/{name}.md").write_text(feature_file(name))
        (repo / f"docs/decisions/arch/{name}.md").write_text(decision_file(name))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"pr {name}")
    for first, second in (("a", "b"), ("b", "a")):
        _git(repo, "checkout", "-q", "-B", f"order-{first}", "main")
        _git(repo, "merge", "--no-ff", "-qm", first, f"pr-{first}")
        _git(repo, "merge", "--no-ff", "-qm", second, f"pr-{second}")  # asserts exit 0
        assert (repo / "docs/features/a.md").exists() and (repo / "docs/features/b.md").exists()
        assert (repo / "docs/decisions/arch/b.md").exists()
        assert fm.check(repo, code_dirs=[]) == []


def test_the_packet_feature_index_lists_per_row_files(tmp_path: Path) -> None:
    from vigild.packets import assemble

    root = _root(tmp_path)
    (root / "docs/features/a.md").write_text(feature_file("a"))
    index = assemble._coord_context(root, {"title": "t", "request": "r"}, None)[0]
    assert "- a [planned]" in index and "- m-row [planned]" in index
