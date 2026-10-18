"""HTTP surface: the three resources, and responses. Validate, call, shape; nothing else.
`main` is the entry point: `uv run harness-interface`."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .config import Settings
from .models import Harness, Provider, Response, ResponseRequest, Sandbox
from .registry import Resources
from .responses import ResponseService
from .sandbox import DockerSandbox, LocalSandbox
from .store import JsonStore
from .workspace import Workspace


@dataclass
class Container:
    settings: Settings
    resources: Resources
    responses: JsonStore[Response]
    service: ResponseService


def build(settings: Settings | None = None) -> Container:
    s = settings or Settings()
    resources = Resources(s.data_dir)
    sandbox = LocalSandbox(s.logs) if s.runtime == "local" else DockerSandbox(s.logs, s.logs)
    responses = JsonStore(s.responses, Response)
    return Container(s, resources, responses, ResponseService(s, resources, sandbox, responses))


def create_app(c: Container | None = None) -> FastAPI:
    c = c or build()
    app = FastAPI(title="harness-interface", version="1.0.0")
    app.state.container = c

    def not_found(what: str):
        raise HTTPException(404, what)

    def same_name(path_name: str, body_name: str) -> None:
        if path_name != body_name:
            raise HTTPException(400, "name in path and body differ")

    def public(p: Provider) -> dict:
        return p.model_dump(exclude={"key"})

    # providers
    @app.put("/providers/{name}")
    def put_provider(name: str, spec: Provider) -> dict:
        same_name(name, spec.name)
        return public(c.resources.providers.put(name, spec))

    @app.get("/providers")
    def list_providers() -> list[dict]:
        return [public(p) for p in c.resources.providers.list()]

    @app.get("/providers/{name}")
    def get_provider(name: str) -> dict:
        p = c.resources.providers.get(name)
        return public(p) if p else not_found(f"no provider {name}")

    @app.delete("/providers/{name}")
    def delete_provider(name: str) -> dict:
        return {"deleted": c.resources.providers.delete(name)}

    # sandboxes
    @app.put("/sandboxes/{name}")
    def put_sandbox(name: str, spec: Sandbox) -> Sandbox:
        same_name(name, spec.name)
        try:
            return c.resources.put_sandbox(spec)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/sandboxes")
    def list_sandboxes() -> list[Sandbox]:
        return c.resources.list_sandboxes()

    @app.get("/sandboxes/{name}")
    def get_sandbox(name: str) -> Sandbox:
        return c.resources.sandbox(name) or not_found(f"no sandbox {name}")

    @app.delete("/sandboxes/{name}")
    def delete_sandbox(name: str) -> dict:
        try:
            return {"deleted": c.resources.delete_sandbox(name)}
        except ValueError as e:
            raise HTTPException(400, str(e))

    # harnesses
    @app.put("/harnesses/{name}")
    def put_harness(name: str, spec: Harness) -> Harness:
        same_name(name, spec.name)
        try:
            return c.resources.put_harness(spec)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/harnesses")
    def list_harnesses() -> list[Harness]:
        return c.resources.harnesses.list()

    @app.get("/harnesses/{name}")
    def get_harness(name: str) -> Harness:
        return c.resources.harnesses.get(name) or not_found(f"no harness {name}")

    @app.delete("/harnesses/{name}")
    def delete_harness(name: str) -> dict:
        return {"deleted": c.resources.delete_harness(name)}

    # responses
    @app.post("/responses")
    async def create_response(req: ResponseRequest):
        try:
            record, proc, ws = await c.service.start(req)
        except (LookupError, ValueError) as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        if req.stream:
            return StreamingResponse(c.service.stream(record, proc, ws), media_type="text/event-stream",
                                     headers={"X-Response-Id": record.id})
        async for _ in proc.chunks():
            pass
        record = await c.service.finish(record, proc, ws)
        return JSONResponse(record.model_dump(), headers={"X-Response-Id": record.id})

    @app.get("/responses")
    def list_responses() -> list[Response]:
        return c.responses.list()

    @app.get("/responses/{response_id}")
    def get_response(response_id: str) -> Response:
        return c.responses.get(response_id) or not_found(f"no response {response_id}")

    @app.post("/responses/{response_id}/cancel")
    def cancel_response(response_id: str) -> dict:
        return {"cancelled": c.service.cancel(response_id)}

    @app.get("/responses/{response_id}/output")
    def response_output(response_id: str):
        """The harness's stdout as it was streamed, in the content type its resource declared."""
        record = c.responses.get(response_id) or not_found(f"no response {response_id}")
        harness = c.resources.harnesses.get(record.harness.name)
        p = c.service.out_path(response_id)
        return FileResponse(p, media_type=harness.run.stdout if harness else "application/octet-stream") if p.exists() else not_found("no output")

    @app.get("/responses/{response_id}/log")
    def response_log(response_id: str):
        p = c.service.log_path(response_id)
        return FileResponse(p, media_type="text/plain") if p.exists() else not_found("no log")

    @app.get("/responses/{response_id}/files/{path:path}")
    def response_file(response_id: str, path: str):
        record = c.responses.get(response_id) or not_found(f"no response {response_id}")
        try:
            p = Workspace(Path(record.harness.workspace)).resolve(path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return FileResponse(p) if p.is_file() else not_found(f"no file {path}")

    return app


def main() -> None:
    """Serve the API, configured by the environment (see config.py)."""
    import uvicorn
    c = build()
    uvicorn.run(create_app(c), host=c.settings.host, port=c.settings.port, log_level="info")
