"""HTTP surface. Thin: validate, call the service, shape the response."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .config import Settings
from .models import Harness, HarnessSpec, Route, RouteSpec, Run, RunRequest, Session
from .registry import Registry
from .router.base import Rejected
from .runner import Runner
from .service import RunService
from .storage import JsonStore, SecretStore
from .workspace import Workspace


@dataclass
class Container:
    settings: Settings
    registry: Registry
    secrets: SecretStore
    runs: JsonStore[Run]
    sessions: JsonStore[Session]
    service: RunService


def build(settings: Settings | None = None) -> Container:
    s = settings or Settings()
    secrets = SecretStore(s.secrets)
    registry = Registry(JsonStore(s.harnesses, Harness), JsonStore(s.routes, Route), s.check_timeout_s)
    runs, sessions = JsonStore(s.runs, Run), JsonStore(s.sessions, Session)
    service = RunService(s, registry, Runner(secrets), secrets, runs, sessions)
    return Container(s, registry, secrets, runs, sessions, service)


def create_app(c: Container | None = None) -> FastAPI:
    c = c or build()
    app = FastAPI(title="harness-interface", version="0.1.0")
    app.state.container = c

    def not_found(what: str):
        raise HTTPException(404, what)

    # harnesses
    @app.put("/harnesses/{name}")
    def apply_harness(name: str, spec: HarnessSpec) -> Harness:
        if spec.name != name:
            raise HTTPException(400, "name in path and body differ")
        return c.registry.apply(spec)

    @app.get("/harnesses")
    def list_harnesses() -> list[Harness]:
        return c.registry.list()

    @app.get("/harnesses/{name}")
    def get_harness(name: str) -> Harness:
        return c.registry.get(name) or not_found(f"no harness {name}")

    @app.delete("/harnesses/{name}")
    def delete_harness(name: str) -> dict:
        return {"deleted": c.registry.delete(name)}

    # route
    @app.put("/route")
    def apply_route(spec: RouteSpec) -> Route:
        try:
            return c.registry.apply_route(spec)
        except LookupError as e:
            raise HTTPException(400, str(e))

    @app.get("/route")
    def get_route() -> Route:
        return c.registry.route() or not_found("no route applied")

    # secrets
    @app.put("/secrets/{name}")
    async def put_secret(name: str, request: Request) -> dict:
        value = (await request.body()).decode().strip()
        if not value:
            raise HTTPException(400, "empty body")
        c.secrets.put(name, value)
        return {"stored": name}

    @app.get("/secrets")
    def list_secrets() -> list[str]:
        return c.secrets.names()

    # runs
    @app.post("/runs")
    async def create_run(request: RunRequest):
        try:
            run, execution, ws = await c.service.start(request)
        except Rejected as e:
            raise HTTPException(422, f"route rejected the request: {e}")
        except LookupError as e:
            raise HTTPException(400, str(e))
        harness = c.registry.get(run.harness)
        headers = {"X-Run-Id": run.id, "X-Session-Id": run.session, "X-Harness": run.harness}
        if request.stream:
            return StreamingResponse(c.service.stream(run, execution, ws),
                                     media_type=harness.run.stdout if harness else "application/octet-stream",
                                     headers=headers)
        body = b"".join([chunk async for chunk in execution.chunks()])
        run = await c.service.finish(run, execution, ws)
        return JSONResponse({"run": run.model_dump(), "body": body.decode(errors="replace")}, headers=headers)

    @app.get("/runs")
    def list_runs() -> list[Run]:
        return c.runs.list()

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> Run:
        return c.runs.get(run_id) or not_found(f"no run {run_id}")

    @app.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict:
        return {"cancelled": c.service.cancel(run_id)}

    @app.get("/runs/{run_id}/log")
    def run_log(run_id: str):
        p = c.settings.logs / f"{run_id}.log"
        return FileResponse(p, media_type="text/plain") if p.exists() else not_found("no log")

    @app.get("/runs/{run_id}/files/{path:path}")
    def run_file(run_id: str, path: str):
        run = c.runs.get(run_id) or not_found(f"no run {run_id}")
        session = c.sessions.get(run.session) or not_found("no session")
        try:
            p = Workspace(__import__("pathlib").Path(session.workspace)).resolve(path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return FileResponse(p) if p.is_file() else not_found(f"no file {path}")

    # sessions
    @app.get("/sessions")
    def list_sessions() -> list[Session]:
        return c.sessions.list()

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> Session:
        return c.sessions.get(session_id) or not_found(f"no session {session_id}")

    return app
