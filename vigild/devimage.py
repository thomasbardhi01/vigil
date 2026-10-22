"""A pinned dev image per repo, validated nightly (owner decisions 2026-10-22).

Each repo in configs/repos.yaml names the image its sessions run in and a
smoke command that proves its toolchain works. `vigil validate-images` runs
the command (nightly, from launchd; runbook) and records the image id. vigild
refuses to dispatch a session for a repo whose image was never validated,
was validated more than STALE_AFTER ago, failed its check, or has been
rebuilt since (a different image id).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from vigild.config import Config
from vigild.db import Store, iso, utcnow

STALE_AFTER = timedelta(hours=26)  # nightly, plus slack


class StaleDevImage(RuntimeError):
    pass


class DockerLike(Protocol):
    def image_id_of(self, image: str) -> str | None: ...
    def run_check(self, image: str, command: str) -> tuple[int, str]: ...


@dataclass(frozen=True)
class Validation:
    repo: str
    image: str
    image_id: str | None
    ok: bool
    output: str
    validated_at: str


class DevImages:
    def __init__(
        self, cfg: Config, store: Store, docker: DockerLike, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.docker = docker
        self.clock = clock

    def validate(self, repo: str) -> Validation:
        pol = self.cfg.repo(repo)
        image_id = self.docker.image_id_of(pol.dev_image)
        if image_id is None:
            code, out = 127, f"{pol.dev_image} is not present"
        else:
            code, out = self.docker.run_check(pol.dev_image, pol.dev_image_check)
        v = Validation(repo, pol.dev_image, image_id, code == 0, out[-2000:], iso(self.clock()))
        self.store.x(
            "INSERT INTO dev_images (repo, image, image_id, ok, output, validated_at)"
            " VALUES (?,?,?,?,?,?)",
            (v.repo, v.image, v.image_id, int(v.ok), v.output, v.validated_at),
        )
        return v

    def latest(self, repo: str) -> dict[str, Any] | None:
        rows = self.store.q(
            "SELECT * FROM dev_images WHERE repo=? ORDER BY id DESC LIMIT 1", (repo,)
        )
        return dict(rows[0]) if rows else None

    def ensure_fresh(self, repo: str) -> str:
        """Return the image to run, or raise StaleDevImage."""
        pol = self.cfg.repo(repo)
        last = self.latest(repo)
        if last is None or last["image"] != pol.dev_image:
            raise StaleDevImage(f"{repo}: dev image {pol.dev_image} was never validated")
        if not last["ok"]:
            raise StaleDevImage(f"{repo}: dev image check failed at {last['validated_at']}")
        age = self.clock() - datetime.fromisoformat(last["validated_at"])
        if age > STALE_AFTER:
            hours = int(age.total_seconds() // 3600)
            raise StaleDevImage(f"{repo}: dev image last validated {hours} h ago")
        current = self.docker.image_id_of(pol.dev_image)
        if current is None:
            raise StaleDevImage(f"{repo}: dev image {pol.dev_image} is not present")
        if current != last["image_id"]:
            raise StaleDevImage(f"{repo}: dev image changed since it was validated")
        return pol.dev_image


class DockerImages:
    """The real DockerLike, over docker-py."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def image_id_of(self, image: str) -> str | None:
        import docker.errors

        try:
            return str(self.client.images.get(image).id)
        except docker.errors.ImageNotFound:
            return None

    def run_check(self, image: str, command: str) -> tuple[int, str]:
        c = self.client.containers.run(
            image,
            entrypoint=["sh", "-c"],
            command=[command],
            detach=True,
            network_mode="none",
            read_only=True,
            tmpfs={"/tmp": "rw,mode=1777"},  # noqa: S108
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
        )
        try:
            code = int(c.wait(timeout=300).get("StatusCode", -1))
            return code, c.logs().decode(errors="replace")
        finally:
            c.remove(force=True)
