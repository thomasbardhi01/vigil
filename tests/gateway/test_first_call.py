"""The first-call check: every role's worst-case first call fits its cap.
One function (vigild/gateway/firstcall.py) serves this CI test and the
preflight at job submission, so a model or price change fails CI and a bad
submission is refused with the numbers before any container starts."""

from __future__ import annotations

import pytest

from vigild.config import Config
from vigild.gateway.firstcall import FIRST_CALL_CHARS, first_calls, refusals

REPO = "thomasbardhi01/parkagent"


def test_every_roles_worst_case_first_call_fits_its_cap(cfg: Config) -> None:
    rows = first_calls(cfg)
    roles = {r.role for r in rows}
    assert {"coord", "fallback", "reviewer", "auditor"} <= roles
    assert any(r.role.startswith("tier:") for r in rows)
    for r in rows:
        assert r.worst_usd <= r.limit_usd, (
            f"{r.role} on {r.model}: worst-case first call ${r.worst_usd:.4f} > ${r.limit_usd:.2f}"
        )


def test_the_opus_coord_keeps_its_one_dollar_reservation(cfg: Config) -> None:
    (coord,) = [r for r in first_calls(cfg) if r.role == "coord"]
    assert coord.model == "claude-opus-5-5"
    # 200,000 chars / 3 = 66,667 tokens at $8/M, plus 16,384 output tokens at $20/M
    assert coord.worst_usd == pytest.approx(66_667 * 8e-6 + 16_384 * 20e-6, rel=1e-3)
    assert coord.limit_usd == cfg.budgets.coord_session_usd == 1.00
    assert coord.worst_usd < 0.90


def test_an_opus_workers_first_call_fits_the_task_cap(cfg: Config) -> None:
    (w,) = [r for r in first_calls(cfg) if r.role == "tier:claude-opus"]
    assert w.limit_usd == cfg.budgets.per_task_usd
    assert w.worst_usd < w.limit_usd


def test_a_cap_that_no_longer_fits_is_refused_with_the_numbers(cfg: Config) -> None:
    assert refusals(cfg, REPO) == []
    cfg.budgets.coord_session_usd = 0.50
    (msg,) = refusals(cfg, REPO)
    assert "coord" in msg and "claude-opus-5-5" in msg and "$0.50" in msg
    assert f"{FIRST_CALL_CHARS:,}" in msg


def test_a_role_the_repo_may_not_use_is_not_checked(cfg: Config) -> None:
    cfg.budgets.coord_session_usd = 0.50
    cfg.repo(REPO).backends = ["claude-sonnet"]  # no Opus here: the coord can't run anyway
    assert all("coord" not in m for m in refusals(cfg, REPO))
