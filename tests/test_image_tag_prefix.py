"""#128: a non-production data dir gets its own image tag prefix, so a test or
scratch build never moves a tag production's records point at."""

from __future__ import annotations

import hashlib
from pathlib import Path

from vigild.config import Config
from vigild.devimage import DevImages, SessionImages, image_prefix

KEY = "a" * 64


def _dev(cfg: Config, data: Path) -> DevImages:
    cfg.vigild.data_dir = str(data)
    return DevImages(cfg, None, None, None, None)  # type: ignore[arg-type]


def test_a_scratch_data_dir_gets_a_prefixed_tag(cfg: Config, tmp_path: Path) -> None:
    data = tmp_path / "scratch"
    h = hashlib.sha256(str(data.resolve()).encode()).hexdigest()[:8]
    assert _dev(cfg, data).tag("o/fixture", KEY) == f"vigil-dev-{h}/fixture:{'a' * 16}"


def test_the_production_data_dir_keeps_todays_tag(cfg: Config) -> None:
    prod = Path.home() / "vigil-data"
    assert _dev(cfg, prod).tag("o/fixture", KEY) == f"vigil-dev/fixture:{'a' * 16}"
    assert image_prefix(prod, "session") == "vigil-session"


def test_two_data_dirs_get_different_prefixes(tmp_path: Path) -> None:
    assert image_prefix(tmp_path / "a", "dev") != image_prefix(tmp_path / "b", "dev")


def test_the_session_tag_follows_the_same_prefix(cfg: Config, tmp_path: Path) -> None:
    dev = _dev(cfg, tmp_path / "scratch")
    h = hashlib.sha256(str((tmp_path / "scratch").resolve()).encode()).hexdigest()[:8]
    tag = SessionImages(dev, lambda: tmp_path).tag("o/fixture", KEY)
    assert tag == f"vigil-session-{h}/fixture:{'a' * 16}"
