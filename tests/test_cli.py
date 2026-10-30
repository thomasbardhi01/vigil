"""The `vigil` CLI's own behaviour (phase 1 commands)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

from vigil.main import app  # noqa: E402

from tests.test_devimage import world as world  # noqa: E402


def test_dev_image_closes_its_docker_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 2a, item 0: an unclosed client printed `ValueError: I/O operation
    on closed file` at exit."""
    import vigild.server as server

    closed: list[str] = []

    class Images:
        def ensure_fresh(self, repo: str, base: str, *, force: bool = False) -> str:
            return "vigil-dev/x:1"

        def latest(self, repo: str) -> dict[str, Any] | None:
            return None

    class Runner:
        dev_images = Images()
        session_images = None

        class workspace:
            @staticmethod
            def head_sha(repo: str, branch: str) -> str:
                return "a" * 40

        def close(self) -> None:
            closed.append("runner")

    monkeypatch.setattr(server, "build", lambda **kw: object())
    monkeypatch.setattr(server, "_github_app", lambda v: None)
    monkeypatch.setattr(server, "build_runner", lambda v, app: Runner())
    out = CliRunner().invoke(app, ["dev-image", "--repo", "o/x"])
    assert out.exit_code == 0, out.output
    assert closed == ["runner"]


# --- vigil kill (issue #52) -----------------------------------------------------------------


def _api(monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, Any]) -> list[Any]:
    """Point the CLI's API client at a stand-in vigild that answers `status`, `body`."""
    import httpx2
    import vigil.main as cli

    seen: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    monkeypatch.setenv("VIGIL_API_TOKEN", "t" * 8)
    monkeypatch.setattr(
        cli,
        "_api_client",
        lambda: httpx2.Client(
            base_url="http://vigild.test", transport=httpx2.MockTransport(handler)
        ),
    )
    return seen


def test_kill_posts_to_the_api_as_the_cli_and_prints_what_it_did(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    seen = _api(monkeypatch, 200, {"job_id": "pa-0007", "killed": True, "already": None,
                                   "state": "abandoned", "message": "killed pa-0007 (was building)"})  # fmt: skip
    out = CliRunner().invoke(app, ["kill", "pa-0007"])
    assert out.exit_code == 0, out.output
    (req,) = seen
    assert req.method == "POST" and req.url.path == "/api/jobs/pa-0007/kill"
    assert json.loads(req.content) == {"channel": "cli"}
    assert "killed pa-0007" in out.output


def test_kill_of_a_finished_job_says_so_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _api(monkeypatch, 200, {"job_id": "pa-0007", "killed": False, "already": "abandoned",
                            "state": "abandoned", "message": "pa-0007 is already abandoned; nothing to kill"})  # fmt: skip
    out = CliRunner().invoke(app, ["kill", "pa-0007"])
    assert out.exit_code == 0 and "already abandoned" in out.output


@pytest.mark.parametrize("status", [404, 409, 401])
def test_kill_fails_on_an_api_error(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    _api(monkeypatch, status, {"detail": "no such job"})
    out = CliRunner().invoke(app, ["kill", "nope"])
    assert out.exit_code == 1 and str(status) in out.output


# --- vigil batch (issue #54) ----------------------------------------------------------------

BATCH_YAML = """\
name: docs sweep
jobs:
  - repo: o/r
    title: First
    request: Do the first thing.
    why: because
    value: 3
    risk: 1
  - repo: o/r
    title: Second
    request: Do the second thing.
    why: because
    value: 2
    risk: 1
    issue: 12
    notes: [keep it short]
"""


def test_batch_submit_parses_the_yaml_and_posts_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import json

    f = tmp_path / "b.yaml"
    f.write_text(BATCH_YAML)
    seen = _api(
        monkeypatch, 202, {"batch_id": "b-0001", "name": "docs sweep", "jobs": ["r-0001", "r-0002"]}
    )
    out = CliRunner().invoke(app, ["batch", "submit", str(f)])
    assert out.exit_code == 0, out.output
    req = seen[0]
    assert req.method == "POST" and req.url.path == "/api/batch"
    body = json.loads(req.content)
    assert body["name"] == "docs sweep" and [j["title"] for j in body["jobs"]] == [
        "First",
        "Second",
    ]
    assert body["jobs"][1]["issue"] == 12 and body["jobs"][1]["notes"] == ["keep it short"]
    assert "b-0001" in out.output and "r-0002" in out.output


def test_batch_submit_refusal_names_the_job_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    f = tmp_path / "b.yaml"
    f.write_text(BATCH_YAML)
    _api(monkeypatch, 422, {"detail": {"errors": ["jobs[1]: no such repo"]}})
    out = CliRunner().invoke(app, ["batch", "submit", str(f)])
    assert out.exit_code == 1 and "jobs[1]: no such repo" in out.output


def test_batch_submit_rejects_a_file_that_is_not_a_batch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    seen = _api(monkeypatch, 202, {})
    for text in ("- just\n- a list\n", "name: x\n", "name: x\njobs: nope\n", "{{{"):
        f = tmp_path / "bad.yaml"
        f.write_text(text)
        out = CliRunner().invoke(app, ["batch", "submit", str(f)])
        assert out.exit_code == 1, text
    assert CliRunner().invoke(app, ["batch", "submit", str(tmp_path / "none.yaml")]).exit_code == 1
    assert seen == []  # nothing was sent


def test_batch_status_prints_each_job_and_the_total(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {
        "batch_id": "b-0001", "name": "docs sweep", "created_at": "t",
        "jobs": [
            {"job_id": "r-0001", "title": "First", "state": "building", "spent_usd": 0.25, "held_usd": 0.5, "total_usd": 0.75},
            {"job_id": "r-0002", "title": "Second", "state": "spec_pending", "spent_usd": 0.0, "held_usd": 0.0, "total_usd": 0.0},
        ],
        "cost": {"spent_usd": 0.25, "held_usd": 0.5, "total_usd": 0.75},
    }  # fmt: skip
    seen = _api(monkeypatch, 200, body)
    out = CliRunner().invoke(app, ["batch", "status", "b-0001"])
    assert out.exit_code == 0, out.output
    assert seen[0].method == "GET" and seen[0].url.path == "/api/batch/b-0001"
    assert "r-0001" in out.output and "building" in out.output and "0.75" in out.output
    assert "docs sweep" in out.output


def test_batch_status_of_an_unknown_batch_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _api(monkeypatch, 404, {"detail": "no such batch"})
    assert CliRunner().invoke(app, ["batch", "status", "b-9"]).exit_code == 1


def test_batch_status_refuses_an_id_that_is_not_a_batch_id_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _api(monkeypatch, 200, {})
    for bad in ("../x", "b-1/../../jobs", "b-0001?x=1", "x", "b-", "B-1", ""):
        out = CliRunner().invoke(app, ["batch", "status", bad])
        assert out.exit_code == 1, bad
    assert seen == []


def _client_token(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], file: dict[str, str]
) -> str | None:
    """The bearer token `_api_client` would send, with `env` as the environment and `file`
    as the env file's contents (fake values)."""
    import vigil.main as cli

    from vigild import config

    for name in ("VIGIL_API_TOKEN", "VIGIL_COORD_TOKEN", "VIGIL_API_ROLE"):
        monkeypatch.delenv(name, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(config, "load_secrets", lambda: config.Secrets(file))
    auth_header = cli._api_client().headers["Authorization"]
    return str(auth_header).removeprefix("Bearer ")


def test_api_client_uses_the_api_token_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    both = {"VIGIL_API_TOKEN": "owner-fake-000", "VIGIL_COORD_TOKEN": "coord-fake-111"}
    assert _client_token(monkeypatch, {}, both) == "owner-fake-000"
    assert _client_token(monkeypatch, {"VIGIL_API_ROLE": "owner"}, both) == "owner-fake-000"


def test_api_client_uses_the_coord_token_for_the_coord_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    both = {"VIGIL_API_TOKEN": "owner-fake-000", "VIGIL_COORD_TOKEN": "coord-fake-111"}
    assert _client_token(monkeypatch, {"VIGIL_API_ROLE": "coord"}, both) == "coord-fake-111"
    # from the environment first, as VIGIL_API_TOKEN is
    env = {"VIGIL_API_ROLE": "coord", "VIGIL_COORD_TOKEN": "coord-env-222"}
    assert _client_token(monkeypatch, env, both) == "coord-env-222"


def test_api_client_with_the_coord_role_never_falls_back_to_the_owner_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import typer

    with pytest.raises(typer.Exit):
        _client_token(
            monkeypatch, {"VIGIL_API_ROLE": "coord"}, {"VIGIL_API_TOKEN": "owner-fake-000"}
        )


# --- vi-0010: `vigil dev-image` and the inbox Rebuild write the same record ---------------------


def _cli_world(world: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    import types

    import vigild.server as server

    images, _docker, suites, ws, base, _ctx = world
    data = images.cfg.vigild.data_path
    monkeypatch.setenv("VIGIL_DATA_DIR", str(data))
    runner = types.SimpleNamespace(
        dev_images=images, session_images=None, workspace=ws, close=lambda: None
    )
    monkeypatch.setattr(
        server, "build", lambda **kw: types.SimpleNamespace(cfg=images.cfg, store=images.store)
    )
    monkeypatch.setattr(server, "_github_app", lambda v: None)
    monkeypatch.setattr(server, "build_runner", lambda v, app: runner)
    return images, suites, ws, base, data


ROW_FIELDS = ("repo", "image", "image_id", "ok", "output", "key", "stage", "base_sha")


def test_cli_build_leaves_one_record_like_on_rebuild_and_names_the_data_dir(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    from vigild.jobs.runner import JobRunner

    images, _, ws, base, data = _cli_world(world, monkeypatch)
    docker = world[1]
    out = CliRunner().invoke(app, ["dev-image", "--repo", "o/fixture"])
    assert out.exit_code == 0, out.output
    assert str(data) in out.output
    rows = images.store.q("SELECT * FROM dev_images WHERE repo=?", ("o/fixture",))
    assert len(rows) == 1
    cli_row = {k: rows[0][k] for k in ROW_FIELDS}
    images.store.x("DELETE FROM dev_images")
    docker.builds.clear()  # the fake's image ids count builds; start the second from the same
    me = types.SimpleNamespace(
        session_images=None, dev_images=images, workspace=ws, background=False
    )
    JobRunner.on_rebuild(me, "o/fixture", base)  # type: ignore[arg-type]
    (row,) = images.store.q("SELECT * FROM dev_images WHERE repo=?", ("o/fixture",))
    assert {k: row[k] for k in ROW_FIELDS} == cli_row


def test_a_build_stopped_mid_validation_exits_nonzero_and_says_no_record_was_written(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    images, suites, _, _, _ = _cli_world(world, monkeypatch)

    def boom(*a: Any, **kw: Any) -> None:
        raise RuntimeError("docker went away")

    monkeypatch.setattr(suites, "run", boom)
    out = CliRunner().invoke(app, ["dev-image", "--repo", "o/fixture"])
    assert out.exit_code != 0
    assert "validate" in out.output and "docker went away" in out.output
    assert "no record was written" in out.output
    assert images.store.q("SELECT * FROM dev_images") == []


def test_a_fetch_failure_names_the_fetch_stage(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    images, _, ws, _, _ = _cli_world(world, monkeypatch)

    def no_fetch(*a: Any, **kw: Any) -> str:
        raise RuntimeError("github is down")

    monkeypatch.setattr(ws, "head_sha", no_fetch)
    out = CliRunner().invoke(app, ["dev-image", "--repo", "o/fixture"])
    assert out.exit_code != 0
    assert "fetch" in out.output and "github is down" in out.output
    assert "no record was written" in out.output
    assert images.store.q("SELECT * FROM dev_images") == []


def test_a_build_failure_names_the_build_stage(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    images, _, _, _, _ = _cli_world(world, monkeypatch)

    def no_build(*a: Any, **kw: Any) -> str:
        raise RuntimeError("docker build died")

    monkeypatch.setattr(images.docker, "build", no_build)
    out = CliRunner().invoke(app, ["dev-image", "--repo", "o/fixture"])
    assert out.exit_code != 0
    assert "build" in out.output and "docker build died" in out.output
    assert "no record was written" in out.output
    assert images.store.q("SELECT * FROM dev_images") == []


def test_cli_with_session_images_and_rebuild_builds_the_dev_image_once(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    import vigild.server as server

    images, _, _, _, _ = _cli_world(world, monkeypatch)
    runner = server.build_runner(None, None)  # type: ignore[arg-type]
    calls: list[str] = []
    real = images.ensure_fresh

    def dev(repo: str, sha: str, **kw: Any) -> str:
        calls.append("dev")
        return real(repo, sha, **kw)

    def session(repo: str, sha: str, **kw: Any) -> str:
        calls.append("session")
        return dev(repo, sha, **kw)  # SessionImages.ensure_fresh builds the dev image itself

    monkeypatch.setattr(images, "ensure_fresh", dev)
    runner.session_images = types.SimpleNamespace(ensure_fresh=session)
    out = CliRunner().invoke(app, ["dev-image", "--repo", "o/fixture", "--rebuild"])
    assert out.exit_code == 0, out.output
    assert calls == ["session", "dev"]
    assert len(images.store.q("SELECT * FROM dev_images WHERE repo=?", ("o/fixture",))) == 1


def test_a_session_step_failure_after_a_recorded_dev_image_names_the_stage_and_tag(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    import vigild.server as server

    images, *_ = _cli_world(world, monkeypatch)
    runner = server.build_runner(None, None)  # type: ignore[arg-type]

    def session(repo: str, sha: str, **kw: Any) -> str:
        images.ensure_fresh(repo, sha, **kw)  # the dev image is recorded
        images.stage = "session-build"
        raise RuntimeError("session build died")

    runner.session_images = types.SimpleNamespace(ensure_fresh=session)
    out = CliRunner().invoke(app, ["dev-image", "--repo", "o/fixture"])
    (row,) = images.store.q("SELECT * FROM dev_images WHERE repo=?", ("o/fixture",))
    assert out.exit_code == 1
    assert "session-build" in out.output and "session build died" in out.output
    assert row["image"] in out.output
    assert "no record was written" not in out.output
