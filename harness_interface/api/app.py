"""Layer 6: the HTTP routes. Providers and harnesses as resources (PUT, GET one or all, DELETE); `POST
/responses` as the OpenAI Responses API; sessions to read, follow, interrupt and stop. Each route
validates, calls `Sessions` and shapes the reply with `wire`; nothing else. A refusal is 400 (can't be
done), 404 (unknown) or 409 (busy), a malformed body 422, each `{"detail": …}`. At startup git must be
there and what a restart cut off is closed; `main` is the server's entry point. (No `from __future__
import annotations` here: FastAPI reads the route types at runtime.)"""
import asyncio
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Any, Optional, Union

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from ..errors import Conflict, Invalid, NotFound
from ..harness import HarnessFolder, Placement
from ..runtimes import Images
from ..sessions import ResponseRecord, Sessions
from ..store import ProviderEntry, folder_map
from ..workspace import require_git
from . import wire
from .config import Settings

STATUS = {Invalid: 400, NotFound: 404, Conflict: 409}


class ProviderBody(BaseModel):
    name: Optional[str] = None
    url: str
    api: str
    key: str


class Base64(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base64: str


def build(settings: Settings) -> Sessions:
    """The service as the server runs it, from its settings."""
    data = settings.data_dir
    images = Images(data / "logs") if settings.runtime == "docker" else None
    return Sessions(data, Placement(images, ca_file=settings.ca_file))


def create_app(sessions: Sessions) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        require_git()
        await sessions.recover()
        yield
        await sessions.close()

    app = FastAPI(title="harness-interface", version=version("harness-interface"), lifespan=lifespan)

    for error, code in STATUS.items():
        @app.exception_handler(error)
        async def refused(_: Request, e: Exception, code: int = code) -> JSONResponse:
            return JSONResponse({"detail": str(e)}, status_code=code)

    resource_routes(app, sessions)
    response_routes(app, sessions)
    return app


def resource_routes(app: FastAPI, sessions: Sessions) -> None:
    registry = sessions.registry

    def harness(folder: HarnessFolder, with_files: bool = False) -> dict:
        install = registry.install(folder.name)
        out = {"name": folder.name, "description": folder.description, "apis": list(folder.apis),
               "provider": {"url": folder.provider.url, "api": folder.provider.api}, "interrupt": folder.run.interrupt,
               "install": {"state": install.state, "log": install.log, "error": install.error}}
        return {**out, "files": folder_map(folder.path)} if with_files else out

    @app.put("/providers/{name}")
    def put_provider(name: str, body: ProviderBody) -> dict:
        if body.name not in (None, name):
            raise Invalid("the name in the path and the body differ")
        return registry.put_provider(ProviderEntry(name, body.url, body.api, body.key)).public()

    @app.get("/providers")
    def providers() -> list:
        return [p.public() for p in registry.providers()]

    @app.get("/providers/{name}")
    def provider(name: str) -> dict:
        return registry.provider(name).public()

    @app.delete("/providers/{name}")
    def delete_provider(name: str) -> dict:
        registry.delete_provider(name)
        return {"deleted": name}

    @app.put("/harnesses/{name}")
    async def put_harness(name: str, body: dict[str, Union[str, Base64]]) -> dict:
        files = {k: v if isinstance(v, str) else v.model_dump() for k, v in body.items()}
        return harness(await registry.put_harness(name, files))

    @app.get("/harnesses")
    async def harnesses() -> list:
        return [harness(f) for f in registry.harnesses()]

    @app.get("/harnesses/{name}")
    async def get_harness(name: str) -> dict:
        return harness(registry.harness(name), with_files=True)

    @app.delete("/harnesses/{name}")
    async def delete_harness(name: str) -> dict:
        registry.delete_harness(name)
        return {"deleted": name}


def response_routes(app: FastAPI, sessions: Sessions) -> None:
    async def shape(record: ResponseRecord) -> dict:
        return wire.response(record, await asyncio.to_thread(sessions.artifacts, record.id))

    def streamed(ident: str, headers: dict) -> StreamingResponse:
        return StreamingResponse(wire.stream(sessions.follow(ident), shape), media_type="text/event-stream",
                                 headers=headers)

    async def whole_session(sid: str) -> dict:
        s = sessions.session(sid)
        return wire.session(s, [await shape(sessions.response(rid)) for rid in s.responses])

    @app.post("/responses")
    async def create(req: wire.ResponseRequest) -> Any:
        s = await sessions.start(req.ask())
        rid = s.responses[-1]
        headers = {"X-Response-Id": rid, "X-Session-Id": s.id}
        if req.stream:
            return streamed(rid, headers)
        return JSONResponse(await shape(await sessions.wait(rid)), headers=headers)   # leaving doesn't stop it

    @app.get("/sessions")
    def list_sessions() -> dict:
        return {"object": "list", "data": [wire.session(s) for s in sessions.sessions()]}

    @app.get("/sessions/{sid}")
    async def get_session(sid: str, stream: bool = False) -> Any:
        if stream:
            return streamed(sid, {"X-Session-Id": sessions.session(sid).id})
        return await whole_session(sid)

    @app.post("/sessions/{sid}/interrupt")
    async def interrupt(sid: str, req: wire.InterruptRequest) -> Any:
        outcome, record = await sessions.interrupt(sid, req.task, req.instructions)
        headers = {"X-Response-Id": record.id, "X-Session-Id": sid, "X-Interrupt-Outcome": outcome}
        if req.stream:
            return streamed(record.id, headers)
        if outcome != "steered":
            record = await sessions.wait(record.id)
        return JSONResponse({"outcome": outcome, "response": await shape(record)}, headers=headers)

    @app.post("/sessions/{sid}/stop")
    async def stop(sid: str, req: Optional[wire.StopRequest] = None) -> dict:
        outcome = await sessions.stop(sid, req.timeout_s if req else None)
        return {"outcome": outcome, "session": await whole_session(sid)}


def main() -> None:
    """Serve the API, configured by the environment."""
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(build(settings)), host=settings.host, port=settings.port, log_level="info")
