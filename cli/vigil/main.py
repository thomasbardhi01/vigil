"""The `vigil` CLI. Phase 1 ships `doctor` and `validate-images`; `run`,
`batch`, `ls`, `trace` and `kill` arrive in phase 2 as clients of the API.

  uv run python -m vigil doctor
  uv run python -m vigil validate-images     # nightly, from launchd (runbook)
"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def doctor(
    repo: list[str] = typer.Option(  # noqa: B008
        None, "--repo", help="Mint and revoke a test token only for these repos."
    ),
    no_docker: bool = typer.Option(False, "--no-docker", help="Skip the Docker checks."),
) -> None:
    """One health check per credential and dependency: names and pass/fail only."""
    import httpx2

    from vigild import config
    from vigild.doctor import render, run_checks

    cfg = config.load()
    secrets = config.load_secrets()
    docker_client = None
    if not no_docker:
        try:
            import docker

            docker_client = docker.from_env()
        except Exception:
            docker_client = None
    with httpx2.Client(timeout=30) as http:
        checks = run_checks(
            cfg, secrets, http=http, docker=docker_client, repos=list(repo) if repo else None
        )
    typer.echo(render(checks))
    raise typer.Exit(0 if all(c.ok is not False for c in checks) else 1)


@app.command("validate-images")
def validate_images() -> None:
    """Run each repo's dev-image check and record it (vigild/devimage.py)."""
    import docker

    from vigild import config
    from vigild.db import Store
    from vigild.devimage import DevImages, DockerImages

    cfg = config.load()
    cfg.vigild.data_path.mkdir(parents=True, exist_ok=True)
    images = DevImages(
        cfg, Store.open(cfg.vigild.data_path / "vigil.db"), DockerImages(docker.from_env())
    )
    failed = False
    for repo in cfg.repos.repos:
        v = images.validate(repo)
        typer.echo(f"{'pass' if v.ok else 'fail'}  {repo}  {v.image}")
        failed |= not v.ok
    raise typer.Exit(1 if failed else 0)
