"""The Claude executor's harness: PID 1 in the container, as root.

Protocol with vigild:
- stdin, one JSON line: {"gateway_token": "..."}. Never in the environment
  docker sees; the token goes only into the CLI child's environment.
- /vigil/packet.md (read-only mount): the task packet, the whole prompt.
- /work/.vigil/task.json: the contract (worker) or the job request (coord).
- env: VIGIL_ROLE, VIGIL_MODEL, VIGIL_GATEWAY_URL, VIGIL_MAX_TURNS,
  VIGIL_MAX_BUDGET_USD, VIGIL_REQUIRE_PLUGIN, VIGIL_AGENT_UID, plus OTEL_*.
- stdout: event lines `{"vigil_event": {...}}` while running, and one final
  `{"vigil_result": {...}}` line naming the head commit.

Two users (review round 2, N1 and N11). The harness is root, with only the
capabilities to change uid and to kill. Everything that runs code from the
repo or the model runs as the agent uid (10001) with no capabilities: the CLI
(through /opt/vigil/agent-cli) and git. The agent uid can't signal PID 1, read
its memory or write its stdout (/proc/1/fd/1), so every line vigild reads from
the container is the harness's own.

The harness runs no tests: test results come only from vigild's verifier,
which runs test_cmd in fresh containers on commits taken from the vault (owner
direction, round 2). After the agent, the harness kills every other process,
then commits what the agent left and writes the branch as
/vigil/out/result.bundle (from the base commit vigild recorded), with git
pinned against the repo's own config and a .git that points elsewhere refused.
vigild imports the bundle into its vault and refuses one whose branch tip
isn't the head named on the result line (the out dir is a bind mount, which on
Docker Desktop ignores file modes). The harness never pushes. Tool inputs and
results are redacted of anything token-shaped before they are emitted (item 13).
Exit codes: 0 done, 2 bad input, 3 guard not loaded, 4 agent error,
5 the work tree can't be committed safely.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

WORK = Path("/work")
PACKET = Path("/vigil/packet.md")
OUT = Path("/vigil/out")
AGENT_CLI = "/opt/vigil/agent-cli"  # setpriv down to the agent uid, then the CLI
PLAIN_CLI = "/usr/local/bin/claude"
BOT_NAME = "vigil-worker[bot]"
BOT_EMAIL = "vigil-worker[bot]@users.noreply.github.com"
SECRETISH = re.compile(r"(vgw_[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,})")
# Paths in .git that send git somewhere else for its config, hooks or objects.
ELSEWHERE = ("commondir", "gitdir", "objects/info/alternates", "objects/info/http-alternates")
NO_SYMLINK = ("HEAD", "config", "objects", "refs", "hooks", "info", "packed-refs")


class HarnessRefused(Exception):
    """The work tree can't be committed safely; the session fails closed."""


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


def agent_uid() -> int:
    return int(os.environ.get("VIGIL_AGENT_UID", "10001"))


def as_agent() -> dict[str, Any]:
    """subprocess kwargs that drop to the agent uid (outside a container,
    where the harness isn't root, there is nothing to drop)."""
    if os.getuid() != 0:
        return {}
    uid = agent_uid()
    return {"user": uid, "group": uid, "extra_groups": []}


def kill_strays() -> None:
    """As PID 1, signal every other process in the container."""
    if os.getpid() == 1:
        with contextlib.suppress(ProcessLookupError):
            os.kill(-1, signal.SIGKILL)
        time.sleep(0.2)


def emit(kind: str, payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps({kind: payload}) + "\n")
    sys.stdout.flush()


def emit_event(token: str, event: dict[str, Any]) -> None:
    emit("vigil_event", redact(event, token))


# --- git, pinned against the repo's own config --------------------------------------------


def git_pins() -> list[str]:
    """Command-line config beats the repo's: no hooks, no fsmonitor, no
    external programs, no network, a fixed identity."""
    pins = {
        "core.hooksPath": "/dev/null",
        "core.fsmonitor": "false",
        "core.untrackedCache": "false",
        "core.sshCommand": "false",
        "credential.helper": "",
        "diff.external": "",
        "commit.gpgSign": "false",
        "protocol.allow": "never",
        "gc.auto": "0",
        "maintenance.auto": "false",
        "safe.directory": str(WORK),
        "user.name": BOT_NAME,
        "user.email": BOT_EMAIL,
    }
    out: list[str] = []
    for k, v in pins.items():
        out += ["-c", f"{k}={v}"]
    return out


def git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    gd = str(WORK / ".git")
    env.update(
        {
            "GIT_DIR": gd,
            "GIT_COMMON_DIR": gd,  # a planted .git/commondir is ignored as well as refused
            "GIT_WORK_TREE": str(WORK),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def git(*args: str, check: bool = True) -> str:
    p = subprocess.run(
        ["git", *git_pins(), *args],
        cwd=WORK,
        env=git_env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        **as_agent(),
    )
    if check and p.returncode != 0:
        raise HarnessRefused(f"git {args[0]} failed: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def check_git_dir() -> None:
    """Refuse a .git that sends git somewhere the agent chose."""
    g = WORK / ".git"
    try:
        if not stat.S_ISDIR(os.lstat(g).st_mode):
            raise HarnessRefused(".git is not a directory")
    except FileNotFoundError as e:
        raise HarnessRefused(".git is missing") from e
    for rel in ELSEWHERE:
        if os.path.lexists(g / rel):
            raise HarnessRefused(f".git/{rel} is present")
    for rel in NO_SYMLINK:
        if (g / rel).is_symlink():
            raise HarnessRefused(f".git/{rel} is a symlink")


def snapshot(task: dict[str, Any], role: str) -> str:
    """Commit what the agent left and bundle the branch from the base. Returns
    the head commit, which vigild binds the imported bundle to."""
    branch, base_sha = task.get("branch"), task.get("base_sha")
    if not branch or not base_sha:
        raise HarnessRefused("task.json names no branch or base_sha")
    check_git_dir()
    ref = f"refs/heads/{branch}"
    if git("symbolic-ref", "-q", "HEAD", check=False) != ref:
        raise HarnessRefused(f"HEAD is not on {branch}")
    if git("status", "--porcelain"):
        git("add", "-A")
        what = task.get("task_id") or task.get("job_id")
        git("commit", "-q", "--no-verify", "-m", f"vigil: {role} {what}")
    head = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    with contextlib.suppress(FileNotFoundError):
        os.unlink(OUT / "result.bundle")
    if head != base_sha:
        git("bundle", "create", "-q", str(OUT / "result.bundle"), ref, f"^{base_sha}")
    return head


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
    stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
    options = ClaudeAgentOptions(
        cwd=str(WORK),
        # as root, the CLI goes through setpriv to the agent uid with no capabilities
        cli_path=AGENT_CLI if os.getuid() == 0 else PLAIN_CLI,
        permission_mode="bypassPermissions",
        model=os.environ.get("VIGIL_MODEL"),
        max_turns=int(os.environ.get("VIGIL_MAX_TURNS", "60")),
        max_budget_usd=float(os.environ.get("VIGIL_MAX_BUDGET_USD", "1.0")),
        setting_sources=[],  # isolation: managed settings only; the packet carries CLAUDE.md
        env=child_env,
        stderr=stderr_tail.append,  # piped to the harness, never the container's streams
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
    result["cli_stderr_tail"] = "".join(stderr_tail)[-2000:]
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

    started = time.monotonic()
    try:
        agent = asyncio.run(run_agent(packet, role, token))
    except SystemExit:
        raise
    except Exception as e:  # report, don't hide
        emit("vigil_result", {"status": "failed", "error": f"{type(e).__name__}: {e}"[:500]})
        return 4

    kill_strays()  # nothing the agent started survives to touch what follows
    try:
        head = snapshot(task, role)
    except HarnessRefused as e:
        kill_strays()
        emit("vigil_result", redact({"status": "failed", "error": f"harness: {e}"}, token))
        return 5
    kill_strays()
    emit(
        "vigil_result",
        redact(
            {
                **agent,
                "status": "done",
                "role": role,
                "head": head,
                "seconds": round(time.monotonic() - started, 1),
            },
            token,
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
