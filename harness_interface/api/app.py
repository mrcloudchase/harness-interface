"""Layer 7: the HTTP front end. The three resources, and responses in the OpenAI Responses format.
Each route validates, calls the platform and shapes the reply; nothing else. `main` is the server's
entry point. (No `from __future__ import annotations` here: the resource routes are generated per
kind, and FastAPI reads their body types at runtime.)"""
import mimetypes
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.responses import Response as HTTPResponse

from ..errors import Conflict, Invalid, NotFound
from ..platform import DockerPlacement, LocalPlacement, Service
from ..resources import KINDS, Registry
from ..workspace import require_git
from .config import Settings
from .wire import ResponseRequest, response, stream

STATUS = {Invalid: 400, NotFound: 404, Conflict: 409}


def build(settings: Settings) -> Service:
    """The platform as the server runs it, from its settings."""
    data = settings.data_dir
    placement = DockerPlacement(data / "logs") if settings.runtime == "docker" else LocalPlacement()
    return Service(data, Registry(data), placement)


def public(item: Any) -> dict[str, Any]:
    """A resource as the API shows it: a provider's key never leaves the server."""
    return {k: v for k, v in asdict(item).items() if k != "key"}


def create_app(service: Service) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        require_git()
        await service.recover()
        yield

    app = FastAPI(title="harness-interface", version="1.0.0", lifespan=lifespan)
    app.state.service = service

    for error, code in STATUS.items():
        @app.exception_handler(error)
        async def refused(_: Request, e: Exception, code: int = code) -> JSONResponse:
            return JSONResponse({"detail": str(e)}, status_code=code)

    for kind, body in KINDS.items():
        resource_routes(app, service, kind, body)
    response_routes(app, service)
    return app


def resource_routes(app: FastAPI, service: Service, kind: str, body: type) -> None:
    """PUT, GET (one or all) and DELETE, the same for every kind."""
    registry = service.registry

    @app.put(f"/{kind}/{{name}}", name=f"put_{kind}")
    def put(name: str, item: body) -> dict:
        if item.name != name:
            raise Invalid("name in path and body differ")
        return public(registry.put(kind, item))

    @app.get(f"/{kind}", name=f"list_{kind}")
    def list_all() -> list[dict]:
        return [public(i) for i in registry.list(kind)]

    @app.get(f"/{kind}/{{name}}", name=f"get_{kind}")
    def get(name: str) -> dict:
        return public(registry.get(kind, name))

    @app.delete(f"/{kind}/{{name}}", name=f"delete_{kind}")
    def delete(name: str) -> dict:
        return {"deleted": registry.delete(kind, name)}


def response_routes(app: FastAPI, service: Service) -> None:
    @app.post("/responses")
    async def create(req: ResponseRequest):
        run = await service.start(req.ask())
        headers = {"X-Response-Id": run.record.id}
        if req.stream:
            return StreamingResponse(stream(run), media_type="text/event-stream", headers=headers)
        await run.done.wait()                        # the run belongs to the server: leaving does not stop it
        return JSONResponse(response(run.record), headers=headers)

    @app.get("/responses")
    def list_all() -> list[dict]:
        return [response(r) for r in service.list()]

    @app.get("/responses/{rid}")
    def get(rid: str) -> dict:
        return response(service.get(rid))

    @app.post("/responses/{rid}/cancel")
    def cancel(rid: str) -> dict:
        return {"cancelled": service.cancel(rid)}

    @app.get("/responses/{rid}/output")
    def output(rid: str):
        """The harness's stdout as it printed it, in the content type its harness declares."""
        record = service.get(rid)
        path = service.output_path(rid)
        if not path.exists():
            raise NotFound("no output")
        try:
            media = service.registry.get("harnesses", record.harness).run.stdout
        except NotFound:
            media = "application/octet-stream"
        return FileResponse(path, media_type=media)

    @app.get("/responses/{rid}/log")
    def log(rid: str):
        service.get(rid)
        path = service.log_path(rid)
        if not path.exists():
            raise NotFound("no log")
        return FileResponse(path, media_type="text/plain")

    @app.get("/responses/{rid}/diff")
    def diff(rid: str):
        """What the turn changed: so far, while it runs; in full, after."""
        record, ws = service.workspace(rid)
        if not record.base:
            raise NotFound("no diff for this response")
        return PlainTextResponse(ws.diff(record.base, record.commit or None), media_type="text/x-diff")

    @app.get("/responses/{rid}/files")
    def files(rid: str) -> list[str]:
        record, ws = service.workspace(rid)
        return ws.files(record.commit or None)

    @app.get("/responses/{rid}/files/{path:path}")
    def file(rid: str, path: str):
        record, ws = service.workspace(rid)
        data = ws.read(path, record.commit or None)
        if data is None:
            raise NotFound(f"no file {path}")
        return HTTPResponse(data, media_type=mimetypes.guess_type(path)[0] or "application/octet-stream")


def main() -> None:
    """Serve the API, configured by the environment."""
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(build(settings)), host=settings.host, port=settings.port, log_level="info")
