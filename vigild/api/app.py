"""The REST API: the one API behind the CLI, MCP and the web UI.

Every route is declared with its full path here, so
scripts/check-feature-map.py can find it.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from vigild.api.auth import Scope, require
from vigild.db import Store
from vigild.jobs.service import Conflict, JobRequest, NotFound, SubmitError
from vigild.jobs.tree import job_tree
from vigild.services import Services

router = APIRouter()
READ = Depends(require(Scope.READ))
ADMIN = Depends(require(Scope.ADMIN))


def _svc(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def _plain(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return getattr(obj, "value", obj)


# --- health ---------------------------------------------------------------------


@router.get("/api/health", dependencies=[READ])
def health(request: Request) -> dict[str, Any]:
    svc = _svc(request)
    try:
        svc.store.q("SELECT 1")
        db = "ok"
    except Exception as e:  # pragma: no cover - a broken DB is the point of the check
        db = f"error: {e}"
    return {"ok": db == "ok", "db": db, "degraded": sorted(svc.degraded), "version": "0.1.0"}


# --- tasks and jobs ---------------------------------------------------------------


@router.post("/api/tasks", dependencies=[ADMIN], status_code=202)
def submit_task(request: Request, body: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    try:
        out = _svc(request).jobs.submit_task(body)
    except SubmitError as e:
        raise HTTPException(422, {"errors": e.reasons}) from e
    return _plain(out)  # type: ignore[no-any-return]


@router.get("/api/tasks", dependencies=[READ])
def list_tasks(request: Request) -> list[dict[str, Any]]:
    return [_plain(t) for t in _svc(request).store.list_tasks()]


@router.get("/api/tasks/{task_id}", dependencies=[READ])
def get_task(request: Request, task_id: str) -> dict[str, Any]:
    try:
        return _plain(_svc(request).store.get_task(task_id))  # type: ignore[no-any-return]
    except KeyError as e:
        raise HTTPException(404, "no such task") from e


@router.post("/api/jobs", dependencies=[ADMIN], status_code=202)
def submit_job(request: Request, body: JobRequest) -> dict[str, Any]:
    try:
        job = _svc(request).jobs.submit_request(body)
    except SubmitError as e:
        raise HTTPException(422, {"errors": e.reasons}) from e
    return _plain(job)  # type: ignore[no-any-return]


@router.get("/api/jobs", dependencies=[READ])
def list_jobs(request: Request) -> list[dict[str, Any]]:
    return [_plain(j) for j in _svc(request).store.list_jobs()]


def _job_or_404(store: Store, job_id: str) -> None:
    try:
        store.get_job(job_id)
    except KeyError as e:
        raise HTTPException(404, "no such job") from e


@router.get("/api/jobs/{job_id}", dependencies=[READ])
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    store = _svc(request).store
    _job_or_404(store, job_id)
    return _plain(store.get_job(job_id))  # type: ignore[no-any-return]


@router.get("/api/jobs/{job_id}/tree", dependencies=[READ])
def get_job_tree(request: Request, job_id: str) -> dict[str, Any]:
    store = _svc(request).store
    _job_or_404(store, job_id)
    return job_tree(store, job_id)


# --- the inbox --------------------------------------------------------------------


@router.get("/api/inbox", dependencies=[READ])
def inbox(request: Request) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"specs": [], "ready": [], "questions": []}
    for item in _svc(request).store.list_inbox("open"):
        out[item.queue].append(_plain(item))
    return out


@router.post("/api/inbox/{item_id}/approve", dependencies=[ADMIN])
def approve(
    request: Request, item_id: int, body: Annotated[dict[str, Any] | None, Body()] = None
) -> dict[str, Any]:
    edits = (body or {}).get("edits")
    try:
        job = _svc(request).jobs.approve(item_id, edits if isinstance(edits, str) else None)
    except NotFound as e:
        raise HTTPException(404, "no such inbox item") from e
    except Conflict as e:
        raise HTTPException(409, str(e)) from e
    return {"job_id": job.id, "state": job.state.value}


# --- sessions -----------------------------------------------------------------------


@router.get("/api/sessions", dependencies=[READ])
def list_sessions(request: Request) -> list[dict[str, Any]]:
    return [_plain(s) for s in _svc(request).store.list_sessions()]


@router.get("/api/sessions/{session_id}", dependencies=[READ])
def get_session(request: Request, session_id: str) -> dict[str, Any]:
    try:
        return _plain(_svc(request).store.get_session(session_id))  # type: ignore[no-any-return]
    except KeyError as e:
        raise HTTPException(404, "no such session") from e


def create_app(services: Services) -> FastAPI:
    app = FastAPI(title="vigild", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = services
    app.include_router(router)

    @app.exception_handler(KeyError)
    async def _missing(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": f"not found: {exc}"}, status_code=404)

    return app
