"""HTTP surface. Thin: validate, call the service or the arena, shape the response."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from .arena import Arena
from .config import Settings
from .models import Contest, Harness, HarnessSpec, Route, RouteSpec, Run, RunRequest, Session, VerdictIn
from .registry import Registry
from .router.base import Rejected
from .runner import Runner
from .service import RunService
from .storage import JsonStore, SecretStore

UI_PAGE = Path(__file__).parent / "ui" / "index.html"
CONTEST_STREAM = "application/x-ndjson"


@dataclass
class Container:
    settings: Settings
    registry: Registry
    secrets: SecretStore
    runs: JsonStore[Run]
    sessions: JsonStore[Session]
    contests: JsonStore[Contest]
    service: RunService
    arena: Arena


def build(settings: Settings | None = None) -> Container:
    s = settings or Settings()
    secrets = SecretStore(s.secrets)
    registry = Registry(JsonStore(s.harnesses, Harness), JsonStore(s.routes, Route), s.check_timeout_s)
    runs, sessions, contests = JsonStore(s.runs, Run), JsonStore(s.sessions, Session), JsonStore(s.contests, Contest)
    service = RunService(s, registry, Runner(secrets), secrets, runs, sessions, contests)
    arena = Arena(s, registry, secrets, service, contests)
    return Container(s, registry, secrets, runs, sessions, contests, service, arena)


def create_app(c: Container | None = None) -> FastAPI:
    c = c or build()
    app = FastAPI(title="harness-interface", version="0.2.0")
    app.state.container = c

    def not_found(what: str):
        raise HTTPException(404, what)

    # ui: one static page over the same API
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/ui")

    @app.get("/ui", include_in_schema=False)
    def ui():
        return FileResponse(UI_PAGE, media_type="text/html")

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

    @app.get("/cards")
    def cards() -> list[dict]:
        """Each harness with its record: runs, delivered, failed, contests, won, lost."""
        return c.service.cards()

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

    @app.post("/route/preview")
    async def preview_route(request: RunRequest) -> dict:
        """Dry run of `route` mode: the decision, and the Jev request it would send."""
        try:
            return await c.service.preview(request)
        except Rejected as e:
            return {"rejected": str(e)}
        except LookupError as e:
            raise HTTPException(400, str(e))

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
        """`fanout` answers with the contest: streamed as NDJSON lines tagged by harness, or as
        JSON. The other modes answer with the one harness's output in its own content type."""
        try:
            if request.mode == "fanout":
                contest, launched = await c.arena.start(request)
            else:
                run, execution, ws = await c.service.start(request)
        except Rejected as e:
            raise HTTPException(422, f"route rejected the request: {e}")
        except LookupError as e:
            raise HTTPException(400, str(e))
        if request.mode == "fanout":
            headers = {"X-Contest-Id": contest.id}
            if request.stream:
                return StreamingResponse(c.arena.stream(contest, launched), media_type=CONTEST_STREAM, headers=headers)
            contest = await c.arena.finish(contest, launched)
            return JSONResponse({"contest": contest.model_dump(),
                                 "runs": {name: c.runs.get(rid).model_dump() for name, rid in contest.runs.items()}},
                                headers=headers)
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

    @app.patch("/runs/{run_id}")
    def set_verdict(run_id: str, body: VerdictIn) -> Run:
        """A person's verdict on a run. Replaces the judge's."""
        return c.service.set_verdict(run_id, body.success, body.note) or not_found(f"no run {run_id}")

    @app.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict:
        return {"cancelled": c.service.cancel(run_id)}

    @app.get("/runs/{run_id}/log")
    def run_log(run_id: str):
        p = c.service.log_path(run_id)
        return FileResponse(p, media_type="text/plain") if p.exists() else not_found("no log")

    @app.get("/runs/{run_id}/output")
    def run_output(run_id: str):
        """The harness's stdout as it was streamed, in the content type its resource declared."""
        run = c.runs.get(run_id) or not_found(f"no run {run_id}")
        harness = c.registry.get(run.harness)
        p = c.service.out_path(run_id)
        media = harness.run.stdout if harness else "application/octet-stream"
        return FileResponse(p, media_type=media) if p.exists() else not_found("no output")

    @app.get("/runs/{run_id}/files/{path:path}")
    def run_file(run_id: str, path: str):
        run = c.runs.get(run_id) or not_found(f"no run {run_id}")
        try:
            p = c.service.workspace(run).resolve(path)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return FileResponse(p) if p.is_file() else not_found(f"no file {path}")

    # contests
    @app.get("/contests")
    def list_contests() -> list[Contest]:
        return c.contests.list()

    @app.get("/contests/{contest_id}")
    def get_contest(contest_id: str) -> Contest:
        return c.contests.get(contest_id) or not_found(f"no contest {contest_id}")

    # sessions
    @app.get("/sessions")
    def list_sessions() -> list[Session]:
        return c.sessions.list()

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> Session:
        return c.sessions.get(session_id) or not_found(f"no session {session_id}")

    return app
