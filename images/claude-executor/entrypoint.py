"""The Claude executor's harness. Runs as uid 10001 inside the container.

Protocol with vigild:
- stdin, one JSON line: {"gateway_token": "..."}. Never in the environment
  docker sees; the token goes only into the CLI child's environment.
- /vigil/packet.md (read-only mount): the task packet, the whole prompt.
- /work/.vigil/task.json: the contract (worker) or the job request (coord).
- env: VIGIL_ROLE, VIGIL_MODEL, VIGIL_GATEWAY_URL, VIGIL_MAX_TURNS,
  VIGIL_MAX_BUDGET_USD, VIGIL_REQUIRE_PLUGIN, plus OTEL_* from vigild.
- stdout: event lines `{"vigil_event": {...}}` while running, and one final
  `{"vigil_result": {...}}` line.

The worker harness runs test_cmd before and after the agent and writes what
it saw to /vigil/out/harness_tests.json. Before each test run and before it
writes anything, it kills every other process in the container, so nothing the
agent left running can rewrite the record. It commits whatever the agent left
uncommitted and writes the branch as /vigil/out/result.bundle (from the base
commit vigild recorded). vigild imports that bundle into its own repo; host git
never runs in /work (review round 1, blocker 1). The harness never pushes.
Tool inputs and results are redacted of anything token-shaped before they are
emitted (item 13).
Exit codes: 0 done, 2 bad input, 3 guard not loaded, 4 agent error.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

WORK = Path("/work")
PACKET = Path("/vigil/packet.md")
OUT = Path("/vigil/out")
SECRETISH = re.compile(r"(vgw_[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,})")


def redact(value: Any, token: str = "") -> Any:
    if isinstance(value, str):
        if token:
            value = value.replace(token, "[redacted]")
        return SECRETISH.sub("[redacted]", value)
    if isinstance(value, dict):
        return {k: redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, token) for v in value]
    return value


def kill_strays() -> None:
    """As PID 1, signal every other process in the container."""
    if os.getpid() == 1:
        with contextlib.suppress(ProcessLookupError):
            os.kill(-1, signal.SIGKILL)
        time.sleep(0.2)


def write_out(name: str, data: bytes) -> None:
    path = OUT / name
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def emit(kind: str, payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps({kind: payload}) + "\n")
    sys.stdout.flush()


def emit_event(token: str, event: dict[str, Any]) -> None:
    emit("vigil_event", redact(event, token))


def sh(cmd: str, timeout: int = 900) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            shell=True,
            cwd=WORK,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    return p.returncode, (p.stdout + p.stderr)[-4000:]


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=WORK, capture_output=True, text=True, check=False)
    return p.stdout.strip()


def outcome(code: int) -> str:
    if code == 0:
        return "pass"
    if code in (126, 127):
        return "unknown"  # couldn't run in this image: vigild rejects it, never accepts
    return "fail"


async def run_agent(packet: str, role: str, token: str) -> dict[str, Any]:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        SystemMessage,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
        query,
    )

    required = os.environ.get("VIGIL_REQUIRE_PLUGIN", "guard")
    child_env = {
        "ANTHROPIC_BASE_URL": os.environ["VIGIL_GATEWAY_URL"],
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-5-5",
        "ANTHROPIC_SMALL_FAST_MODEL": "claude-haiku-5-5",
    }
    options = ClaudeAgentOptions(
        cwd=str(WORK),
        cli_path="/usr/local/bin/claude",
        permission_mode="bypassPermissions",
        model=os.environ.get("VIGIL_MODEL"),
        max_turns=int(os.environ.get("VIGIL_MAX_TURNS", "60")),
        max_budget_usd=float(os.environ.get("VIGIL_MAX_BUDGET_USD", "1.0")),
        setting_sources=[],  # isolation: managed settings only; the packet carries CLAUDE.md
        env=child_env,
    )
    result: dict[str, Any] = {"plugins": [], "denials": [], "tool_calls": 0}
    async for msg in query(prompt=packet, options=options):
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            plugins = [
                p.get("name") if isinstance(p, dict) else str(p)
                for p in msg.data.get("plugins", [])
            ]
            result["plugins"] = plugins
            result["session_id"] = msg.data.get("session_id")
            emit(
                "vigil_event",
                {
                    "type": "state",
                    "data": {"init": True, "plugins": plugins, "model": msg.data.get("model")},
                },
            )
            if required and not any(required in (p or "") for p in plugins):
                emit(
                    "vigil_result",
                    {"status": "failed", "error": f"{required} not loaded", "plugins": plugins},
                )
                sys.exit(3)
        elif isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, ToolUseBlock):
                    result["tool_calls"] += 1
                    emit_event(
                        token,
                        {
                            "type": "tool_call",
                            "data": {"id": b.id, "name": b.name, "input": b.input},
                        },
                    )
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for b in msg.content:
                if isinstance(b, ToolResultBlock):
                    text = b.content if isinstance(b.content, str) else json.dumps(b.content)
                    emit_event(
                        token,
                        {
                            "type": "tool_result",
                            "data": {
                                "id": b.tool_use_id,
                                "is_error": b.is_error,
                                "content": (text or "")[:2000],
                            },
                        },
                    )
        elif isinstance(msg, ResultMessage):
            result.update(
                {
                    "subtype": msg.subtype,
                    "is_error": msg.is_error,
                    "num_turns": msg.num_turns,
                    "session_id": msg.session_id,
                    "sdk_cost_estimate_usd": msg.total_cost_usd,
                    "permission_denials": msg.permission_denials or [],
                    "result_text": (msg.result or "")[:4000],
                }
            )
    return result


def main() -> int:
    line = sys.stdin.readline()
    try:
        secrets = json.loads(line)
        token = secrets["gateway_token"]
    except json.JSONDecodeError, KeyError:
        emit("vigil_result", {"status": "failed", "error": "no gateway token on stdin"})
        return 2
    role = os.environ.get("VIGIL_ROLE", "worker")
    packet = PACKET.read_text()
    task = json.loads((WORK / ".vigil" / "task.json").read_text())

    harness: dict[str, Any] = {}
    test_cmd = (task.get("spec") or {}).get("test_cmd") if role == "worker" else None
    if test_cmd:
        code, out = sh(test_cmd)
        kill_strays()
        harness["before"] = {"exit": code, "outcome": outcome(code), "tail": out[-1000:]}

    started = time.monotonic()
    try:
        agent = asyncio.run(run_agent(packet, role, token))
    except SystemExit:
        raise
    except Exception as e:  # report, don't hide
        emit("vigil_result", {"status": "failed", "error": f"{type(e).__name__}: {e}"[:500]})
        return 4

    kill_strays()  # nothing the agent started survives to touch what follows
    if test_cmd:
        code, out = sh(test_cmd)
        kill_strays()
        harness["after"] = {"exit": code, "outcome": outcome(code), "tail": out[-1000:]}
        write_out("harness_tests.json", json.dumps({**harness, "provenance": "human"}).encode())
    if git("status", "--porcelain"):
        git("add", "-A")
        git("commit", "-q", "-m", f"vigil: {role} {task.get('task_id') or task.get('job_id')}")
    branch, base_sha = task.get("branch"), task.get("base_sha")
    with contextlib.suppress(FileNotFoundError):
        os.unlink(OUT / "result.bundle")
    if branch and base_sha:
        git(
            "bundle",
            "create",
            "-q",
            str(OUT / "result.bundle"),
            f"refs/heads/{branch}",
            f"^{base_sha}",
        )
    emit(
        "vigil_result",
        redact(
            {
                "status": "done",
                "role": role,
                "head": git("rev-parse", "HEAD"),
                "harness": harness,
                "seconds": round(time.monotonic() - started, 1),
                **agent,
            },
            token,
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
