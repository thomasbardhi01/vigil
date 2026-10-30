"""scripts/deploy.sh against a temp repo, with launchctl, docker, uv, sqlite3
and curl stubbed on PATH. Nothing here touches the real launchctl or vigild."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy.sh"

STUBS = {
    "launchctl": 'echo "launchctl $*" >> "$STUB_LOG"\n',
    "curl": 'echo "curl $*" >> "$STUB_LOG"\nexit "${STUB_CURL_RC:-0}"\n',
    "docker": 'echo "docker $*" >> "$STUB_LOG"\necho -n "${STUB_DOCKER_OUT:-}"\n',
    "sqlite3": (
        'echo "sqlite3 $*" >> "$STUB_LOG"\n'
        'case "$*" in\n'
        '  *"FROM jobs"*) echo -n "${STUB_JOBS:-}";;\n'
        '  *"FROM sessions"*) echo -n "${STUB_SESSIONS:-}";;\n'
        "esac\n"
    ),
    "uv": (
        'echo "uv $*" >> "$STUB_LOG"\n'
        'case "$*" in\n'
        '  *" doctor"*) echo "pass  everything"; exit "${STUB_DOCTOR_RC:-0}";;\n'
        "esac\n"
    ),
}

REPOS_YAML = "repos:\n  owner/alpha:\n    intake: true\n  owner/beta:\n    intake: false\n"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    )
    return r.stdout.strip()


class Env:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        for name, body in STUBS.items():
            p = self.bin / name
            p.write_text("#!/bin/bash\n" + body)
            p.chmod(0o755)
        self.log = tmp / "calls.log"
        self.log.write_text("")
        self.data = tmp / "data"
        self.data.mkdir()
        (self.data / "vigil.db").write_text("")
        origin = tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        self.dev = tmp / "dev"
        subprocess.run(["git", "clone", "-q", str(origin), str(self.dev)], check=True, capture_output=True)
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            _git(self.dev, "config", k, v)
        (self.dev / "configs").mkdir()
        (self.dev / "configs" / "repos.yaml").write_text(REPOS_YAML)
        self.commit("init", {"README.md": "x\n"})
        self.prod = tmp / "prod"
        subprocess.run(["git", "clone", "-q", str(origin), str(self.prod)], check=True, capture_output=True)
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            _git(self.prod, "config", k, v)

    def commit(self, msg: str, files: dict[str, str]) -> str:
        for rel, text in files.items():
            f = self.dev / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        _git(self.dev, "add", ".")
        _git(self.dev, "commit", "-qm", msg)
        _git(self.dev, "push", "-q", "origin", "HEAD:main")
        return _git(self.dev, "rev-parse", "HEAD")

    def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "STUB_LOG": str(self.log),
            "HOME": str(self.tmp / "home"),
            **extra,
        }
        env.pop("VIGIL_PROD_DIR", None)
        env.pop("VIGIL_DATA_DIR", None)
        return subprocess.run(
            ["bash", str(SCRIPT), "--prod-dir", str(self.prod), "--data-dir", str(self.data), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    def called(self, prefix: str) -> list[str]:
        return [c for c in self.calls() if c.startswith(prefix)]


def test_not_idle_building_job_exits_2_and_changes_nothing(tmp_path: Path) -> None:
    e = Env(tmp_path)
    e.commit("next", {"a.txt": "a\n"})
    before = _git(e.prod, "rev-parse", "HEAD")
    r = e.run(STUB_JOBS="vi-0001|building\n")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "vi-0001" in r.stdout + r.stderr
    assert _git(e.prod, "rev-parse", "HEAD") == before
    assert not e.called("launchctl")


def test_not_idle_container_exits_2(tmp_path: Path) -> None:
    e = Env(tmp_path)
    e.commit("next", {"a.txt": "a\n"})
    r = e.run(STUB_DOCKER_OUT="abc123\n")
    assert r.returncode == 2, r.stdout + r.stderr
    assert not e.called("launchctl")
    assert e.called("docker ps --filter label=dev.vigil.job")


def test_not_idle_running_session_exits_2(tmp_path: Path) -> None:
    e = Env(tmp_path)
    r = e.run(STUB_SESSIONS="s-1|running\n")
    assert r.returncode == 2, r.stdout + r.stderr
    assert not e.called("launchctl")


def test_non_fast_forward_stops_before_restart(tmp_path: Path) -> None:
    e = Env(tmp_path)
    (e.prod / "local.txt").write_text("l\n")
    _git(e.prod, "add", ".")
    _git(e.prod, "commit", "-qm", "local only")
    e.commit("next", {"a.txt": "a\n"})
    r = e.run()
    assert r.returncode != 0
    assert r.returncode != 2
    assert not e.called("launchctl")


def test_dirty_checkout_stops_before_restart(tmp_path: Path) -> None:
    e = Env(tmp_path)
    e.commit("next", {"a.txt": "a\n"})
    (e.prod / "README.md").write_text("changed\n")
    r = e.run()
    assert r.returncode != 0
    assert not e.called("launchctl")


def test_happy_path_without_image_change(tmp_path: Path) -> None:
    e = Env(tmp_path)
    old = _git(e.prod, "rev-parse", "HEAD")
    new = e.commit("Add a thing", {"a.txt": "a\n"})
    r = e.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(e.prod, "rev-parse", "HEAD") == new
    ks = e.called("launchctl kickstart -k gui/")
    assert len(ks) == 1 and ks[0].endswith("/dev.vigil.vigild")
    assert any("doctor" in c for c in e.called("uv"))
    assert not any("dev-image" in c for c in e.called("uv"))
    out = r.stdout
    assert f"production {old[:7]} → {new[:7]}" in out
    assert "Add a thing" in out


def test_images_change_rebuilds_each_repo(tmp_path: Path) -> None:
    e = Env(tmp_path)
    e.commit("Change the executor", {"images/claude-executor/Dockerfile": "FROM x\n"})
    r = e.run()
    assert r.returncode == 0, r.stdout + r.stderr
    builds = [c for c in e.called("uv") if "dev-image" in c]
    assert len(builds) == 2
    assert all("--rebuild" in c for c in builds)
    assert any("--repo owner/alpha" in c for c in builds)
    assert any("--repo owner/beta" in c for c in builds)


def test_no_rebuild_flag_skips_rebuild(tmp_path: Path) -> None:
    e = Env(tmp_path)
    e.commit("Change a prompt", {"prompts/x.md": "p\n"})
    r = e.run("--no-rebuild")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any("dev-image" in c for c in e.called("uv"))


def test_doctor_failure_exits_nonzero_but_keeps_the_deploy(tmp_path: Path) -> None:
    e = Env(tmp_path)
    new = e.commit("next", {"a.txt": "a\n"})
    r = e.run(STUB_DOCTOR_RC="1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert _git(e.prod, "rev-parse", "HEAD") == new


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    e = Env(tmp_path)
    e.commit("Change the executor", {"images/claude-executor/Dockerfile": "FROM x\n"})
    before = _git(e.prod, "rev-parse", "HEAD")
    r = e.run("--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(e.prod, "rev-parse", "HEAD") == before
    assert not e.called("launchctl")
    assert not e.called("uv")
    assert "kickstart" in r.stdout
