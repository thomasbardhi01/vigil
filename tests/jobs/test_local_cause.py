"""#181 item 1: a failed worker session on a local preset pages with its cause,
read from vigild's own records (the gateway's `model_calls` rows and
`upstream_error` events, the redacted CLI stderr tail), never from model text.
A hosted session's page is unchanged."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

from typing import Any

from tests.jobs.test_coord_loop import World, _approve, _failure_item, world  # noqa: F401
from vigild.executors.base import EventSink, ExecOutcome, SessionSpec
from vigild.jobs.model import Role
from vigild.metering.calls import CallUsage, record_call
from vigild.metering.prices import PriceTable
from vigild.provenance import Provenance


def _all_local(w: World) -> None:
    for p in w.runner.cfg.backends.presets.values():
        p.locality = "local"


def _fail_w1(
    w: World,
    *,
    stderr: str = "",
    calls: list[tuple[int, int]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    model_text: str = "",
) -> str:
    """w1's session makes `calls` ((status, latency_ms) rows), meets `errors`
    (gateway `upstream_error` events), and ends failed with `stderr`."""
    prices = PriceTable(w.runner.cfg.prices)
    real = w.standin.run

    def run(spec: SessionSpec, token: str, sink: EventSink) -> ExecOutcome:
        if spec.role is Role.WORKER and str(spec.task_id).endswith("w1"):
            for status, ms in calls or []:
                record_call(
                    w.store, prices, session_id=spec.session_id, task_id=spec.task_id,
                    job_id=spec.job_id, purpose="session", provider="openai_compatible",
                    backend_preset=spec.preset, model=spec.model,
                    usage=CallUsage(), status=status, latency_ms=ms,
                )  # fmt: skip
            for e in errors or []:
                w.store.add_event(
                    "upstream_error", e, Provenance.HUMAN,
                    job_id=spec.job_id, session_id=spec.session_id, task_id=spec.task_id,
                )  # fmt: skip
            return ExecOutcome(
                "failed", 1,
                {"status": "failed", "error": model_text or "ResultError", "cli_stderr_tail": stderr},
                "ResultError",
            )  # fmt: skip
        return real(spec, token, sink)

    w.standin.run = run  # type: ignore[method-assign]
    job = _approve(w)
    return job


def _entry(w: World, job: str) -> dict[str, Any]:
    return _failure_item(w, job)["body"]["tasks"][f"{job}-w1"]  # type: ignore[no-any-return]


def test_all_200_calls_and_an_unrecognized_model_is_a_client_side_stop(world: World) -> None:
    w = world
    _all_local(w)
    job = _fail_w1(
        w,
        stderr='[claude-code:unrecognized_model] {"model":"qwen3.6-35b-a3b"}\n',
        calls=[(200, 2000), (200, 23000), (200, 5000)],
    )
    e = _entry(w, job)
    assert e["cause"] == "client_side_stop"
    assert e["backend"]
    assert e["calls"]["count"] == 3
    assert e["calls"]["statuses"] == {"200": 3}
    assert e["calls"]["max_latency_ms"] == 23000
    assert e["calls"]["spend_usd"] == 0


def test_a_503_among_the_calls_is_http_503(world: World) -> None:
    w = world
    _all_local(w)
    job = _fail_w1(w, calls=[(200, 900), (503, 100)])
    e = _entry(w, job)
    assert e["cause"] == "http_503"
    assert e["calls"]["statuses"] == {"200": 1, "503": 1}


def test_a_gateway_upstream_error_event_names_the_status(world: World) -> None:
    w = world
    _all_local(w)
    job = _fail_w1(w, errors=[{"status": 503, "message": "no slot available"}])
    e = _entry(w, job)
    assert e["cause"] == "http_503"
    assert e["calls"]["count"] == 1 and e["calls"]["statuses"] == {"503": 1}


def test_no_calls_and_a_connection_error_is_unreachable(world: World) -> None:
    w = world
    _all_local(w)
    job = _fail_w1(w, errors=[{"error": "ConnectError"}], stderr="connect ECONNREFUSED")
    e = _entry(w, job)
    assert e["cause"] == "unreachable"
    assert e["calls"]["count"] == 0 and e["calls"]["statuses"] == {}


def test_a_read_timeout_is_timeout(world: World) -> None:
    w = world
    _all_local(w)
    job = _fail_w1(w, errors=[{"error": "ReadTimeout"}])
    assert _entry(w, job)["cause"] == "timeout"


def test_a_404_naming_the_model_is_wrong_model(world: World) -> None:
    w = world
    _all_local(w)
    job = _fail_w1(w, errors=[{"status": 404, "message": "model 'x' not found"}])
    assert _entry(w, job)["cause"] == "wrong_model"


def test_a_context_error_is_context_overflow(world: World) -> None:
    w = world
    _all_local(w)
    job = _fail_w1(
        w, errors=[{"status": 400, "message": "request exceeds the available context size"}]
    )
    assert _entry(w, job)["cause"] == "context_overflow"


def test_what_the_model_wrote_never_sets_the_cause(world: World) -> None:
    w = world
    _all_local(w)
    job = _fail_w1(w, calls=[(200, 10)], model_text="ECONNREFUSED http_503 timeout")
    assert _entry(w, job)["cause"] == "client_side_stop"


def test_a_hosted_failure_page_is_unchanged(world: World) -> None:
    w = world
    job = _fail_w1(w, stderr="[claude-code:unrecognized_model]", calls=[(200, 10)])
    e = _entry(w, job)
    assert not {"cause", "backend", "calls"} & set(e)
