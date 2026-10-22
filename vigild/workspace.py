"""Per-task clones from a local mirror (B3).

Each repo has a bare mirror under <data>/mirrors; each task gets
`git clone --local` of it under <data>/clones/<task_id> (objects are hard
links, so it's nearly free), with origin pointed at the real remote. A clone
is self-contained, unlike a `git worktree`, whose .git file points outside
the container mount.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
BRANCH = re.compile(r"^vigil/[A-Za-z0-9._/-]+$")
RO_DIRS = (".github", ".claude", ".opencode", ".git/hooks")
RO_FILES = (".git/config",)
BOT_NAME = "vigil-worker[bot]"
BOT_EMAIL = "vigil-worker[bot]@users.noreply.github.com"


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mount:
    host: str
    container: str
    read_only: bool


def github_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


class Workspace:
    def __init__(self, data_dir: Path, remote_url: Callable[[str], str] = github_url) -> None:
        self.data_dir = data_dir
        self.remote_url = remote_url

    def _git(self, cwd: Path, *args: str, token: str | None = None) -> str:
        env = dict(os.environ)
        if token:
            # The header goes through the environment of this one git process,
            # never onto a command line (ps) or into a config file.
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env.update(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraHeader",
                    "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
                }
            )
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if out.returncode != 0:
            raise WorkspaceError(f"git {args[0]} failed: {out.stderr.strip()[:300]}")
        return out.stdout.strip()

    def mirror(self, repo: str, token: str | None = None) -> Path:
        owner, name = repo.split("/")
        path = self.data_dir / "mirrors" / owner / f"{name}.git"
        if path.exists():
            self._git(path, "remote", "update", "--prune", token=token)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._git(
                path.parent,
                "clone",
                "--mirror",
                "--quiet",
                self.remote_url(repo),
                str(path),
                token=token,
            )
        return path

    def clone(
        self, repo: str, task_id: str, *, branch: str, base: str, token: str | None = None
    ) -> Path:
        if not ID.match(task_id):
            raise WorkspaceError(f"bad task id {task_id!r}")
        if not BRANCH.match(branch) or ".." in branch:
            raise WorkspaceError(f"branch {branch!r} must be vigil/*")
        mirror = self.mirror(repo, token)
        dest = self.data_dir / "clones" / task_id
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._git(
            dest.parent, "clone", "--local", "--quiet", "--branch", base, str(mirror), str(dest)
        )
        self._git(dest, "remote", "set-url", "origin", self.remote_url(repo))
        self._git(dest, "update-ref", f"refs/remotes/origin/{base}", "HEAD")
        self._git(dest, "checkout", "--quiet", "-b", branch)
        self._git(dest, "config", "user.name", BOT_NAME)
        self._git(dest, "config", "user.email", BOT_EMAIL)
        exclude = dest / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as f:
            f.write("\n/.vigil/task.json\n")
        return dest

    def write_task(self, clone: Path, contract: dict[str, Any]) -> Path:
        path = clone / ".vigil" / "task.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
        return path

    def files_changed(self, clone: Path, base: str) -> list[str]:
        out = self._git(clone, "diff", "--name-only", f"origin/{base}...HEAD")
        return [line for line in out.splitlines() if line]

    def diff(self, clone: Path, base: str, paths: list[str] | None = None) -> str:
        return self._git(clone, "diff", f"origin/{base}...HEAD", "--", *(paths or []))

    def overlays(self, clone: Path) -> list[Mount]:
        """Read-only mounts over /work (B18). Missing dirs are created empty so
        the agent can't create them either."""
        mounts: list[Mount] = []
        for d in RO_DIRS:
            p = clone / d
            p.mkdir(parents=True, exist_ok=True)
            mounts.append(Mount(str(p), f"/work/{d}", read_only=True))
        for f in RO_FILES:
            mounts.append(Mount(str(clone / f), f"/work/{f}", read_only=True))
        return mounts

    def remove(self, clone: Path) -> None:
        root = (self.data_dir / "clones").resolve()
        if clone.resolve().parent != root:
            raise WorkspaceError(f"{clone} is not a task clone")
        shutil.rmtree(clone)
