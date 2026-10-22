"""Layer 6: the HTTP routes a tenant uses. A member's key names a member of a tenant; owners register
providers and packages and add members; every member reads them and makes requests.
`POST /v1/responses` is the OpenAI Responses API; sessions are read, followed, steered, archived.
Each route validates, calls the layer below and shapes the reply with `wire`; nothing else. A refusal
is 400, 401, 403, 404 or 409 with `{"detail": …}`; a malformed body 422."""
from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from ..blobs import open_blobs
from ..catalog import Catalog
from ..errors import Conflict, Invalid, NotFound
from ..records import open_records
from ..secrets import Vault
from ..sessions import Record, Sessions
from ..store import Member, Store
from . import deployer, internal, wire
from .auth import Principals
from .config import Settings

STATUS = {Invalid: 400, NotFound: 404, Conflict: 409}
CONSOLE = Path(__file__).resolve().parents[1] / "console"
VERSION = version("harness-interface")


class SignupBody(BaseModel):
    tenant: str
    owner: str


class MemberBody(BaseModel):
    name: str
    role: str = "member"


class KeyBody(BaseModel):
    label: str = ""


class ProviderBody(BaseModel):
    url: str
    api: str
    key: str = ""


class ForkBody(BaseModel):
    catalog: str


class Service:
    """The platform's parts, built from its settings; shared by every role in a process."""

    def __init__(self, settings: Settings, vault: Optional[Vault] = None):
        self.settings = settings
        self.vault = vault or Vault.from_env()
        self.records = open_records(settings.records_url)
        self.blobs = open_blobs(settings.blobs_url, base_url=settings.public_url, secret=self.vault.derive("blobs"))
        self.store = Store(self.records, self.blobs, self.vault, settings.allow_private)
        self.sessions = Sessions(self.store, settings.public_url, settings.gateway_url)
        self.catalog = Catalog()
        self.join_token = settings.join_token or secrets.token_urlsafe(32)   # an in-process worker joins with it
        self.principals = Principals(self.store, settings.deployer_key, self.join_token)


def create_app(service: Service) -> FastAPI:
    settings, store, sessions, principals = service.settings, service.store, service.sessions, service.principals

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def sweeps() -> None:
            while True:
                await asyncio.sleep(15)
                try:
                    sessions.sweep_lost()
                except Exception:
                    pass
        task = asyncio.create_task(sweeps())
        yield
        task.cancel()

    app = FastAPI(title="harness-interface", version=VERSION, lifespan=lifespan)

    for error, code in STATUS.items():
        @app.exception_handler(error)
        async def refused(_: Request, e: Exception, code: int = code) -> JSONResponse:
            return JSONResponse({"detail": str(e)}, status_code=code)

    member, owner = Depends(principals.member), Depends(principals.owner)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": VERSION, "roles": list(settings.roles), "signup": settings.signup}

    # the front door
    @app.post("/v1/signup")
    def signup(body: SignupBody) -> dict:
        if settings.signup != "open":
            raise HTTPException(404, "sign-up is closed on this platform; the deployer creates tenants")
        t = store.create_tenant(body.tenant)
        store.create_member(t.name, body.owner, "owner")
        key, secret = store.mint_key(t.name, body.owner, "first")
        return {"tenant": asdict(t), "owner": body.owner, "key": {"id": key.id, "secret": secret}}

    @app.get("/v1/me")
    def me(who: Member = member) -> dict:
        t = store.tenant(who.tenant)
        return {**asdict(who), "limits": t.limits, "tenant_status": t.status}

    # the tenant
    @app.post("/v1/members")
    def create_member(body: MemberBody, who: Member = owner) -> dict:
        return asdict(store.create_member(who.tenant, body.name, body.role))

    @app.get("/v1/members")
    def list_members(who: Member = member) -> dict:
        return {"object": "list", "data": [asdict(m) for m in store.members(who.tenant)]}

    @app.post("/v1/members/{name}/keys")
    def mint_key(name: str, body: KeyBody, who: Member = member) -> dict:
        if not (who.owner or who.name == name):
            raise HTTPException(403, "a member mints keys for themselves; an owner for anyone")
        key, secret = store.mint_key(who.tenant, name, body.label)
        return {**asdict(key), "secret": secret}

    @app.get("/v1/keys")
    def list_keys(who: Member = member) -> dict:
        return {"object": "list", "data": [asdict(k) for k in store.keys(who.tenant) if who.owner or k.member == who.name]}

    @app.delete("/v1/keys/{key_id}")
    def revoke_key(key_id: str, who: Member = member) -> dict:
        keys = {k.id: k for k in store.keys(who.tenant)}
        if key_id not in keys or not (who.owner or keys[key_id].member == who.name):
            raise NotFound(f"no key {key_id}")
        return asdict(store.revoke_key(who.tenant, key_id))

    # providers
    @app.put("/v1/providers/{name}")
    def put_provider(name: str, body: ProviderBody, who: Member = owner) -> dict:
        return store.put_provider(who.tenant, name, body.url, body.api, body.key).public()

    @app.get("/v1/providers")
    def list_providers(who: Member = member) -> dict:
        return {"object": "list", "data": [p.public() for p in store.providers(who.tenant)]}

    @app.get("/v1/providers/{name}")
    def get_provider(name: str, who: Member = member) -> dict:
        return store.provider(who.tenant, name).public()

    @app.delete("/v1/providers/{name}")
    def delete_provider(name: str, who: Member = owner) -> dict:
        store.delete_provider(who.tenant, name)
        return {"deleted": name}

    # packages
    @app.get("/v1/catalog")
    def list_catalog(who: Member = member) -> dict:
        return {"object": "list", "data": [service.catalog.info(n) for n in service.catalog.names()]}

    @app.get("/v1/catalog/{name}")
    def get_catalog(name: str, who: Member = member) -> dict:
        return service.catalog.info(name)

    @app.put("/v1/harnesses/{name}")
    async def put_harness(name: str, request: Request, who: Member = owner) -> dict:
        """The body is the package as a tar archive, or JSON `{"catalog": "<package>"}` to fork one."""
        t = store.tenant(who.tenant)
        if request.headers.get("content-type", "").startswith("application/json"):
            body = ForkBody(**(await request.json()))
            await asyncio.to_thread(service.catalog.fork, store, who.tenant, body.catalog, name)
        else:
            cap = t.ceilings.upload_mb * 1024 * 1024
            if int(request.headers.get("content-length", "0") or 0) > cap:
                raise Invalid(f"the package is over the tenant's upload limit of {t.ceilings.upload_mb} MB")
            archive = await request.body()
            if not archive:
                raise Invalid("send the package as a tar archive in the request body")
            await asyncio.to_thread(store.put_harness, who.tenant, name, archive)
        return store.harness(who.tenant, name).public()

    @app.get("/v1/harnesses")
    def list_harnesses(who: Member = member) -> dict:
        return {"object": "list", "data": [h.public() for h in store.harnesses(who.tenant)]}

    @app.get("/v1/harnesses/{name}")
    def get_harness(name: str, who: Member = member) -> dict:
        return store.harness(who.tenant, name).public()

    @app.delete("/v1/harnesses/{name}")
    def delete_harness(name: str, who: Member = owner) -> dict:
        store.delete_harness(who.tenant, name)
        return {"deleted": name}

    # responses
    def streamed(who: Member, r: Record) -> StreamingResponse:
        async def ended() -> Record:
            return await sessions.wait(r.id)
        return StreamingResponse(wire.stream(r, sessions.follow(who, r.id), ended), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Session-Id": r.session})

    @app.post("/v1/responses")
    async def create_response(req: wire.ResponseRequest, who: Member = member) -> Any:
        r = await asyncio.to_thread(sessions.create, req.ask(who))
        if req.stream:
            return streamed(who, r)
        if not req.background:
            r = await sessions.wait(r.id)
        return JSONResponse(wire.response(r), headers={"X-Session-Id": r.session})

    @app.get("/v1/responses/{rid}")
    def get_response(rid: str, stream: bool = False, detail: bool = False, who: Member = member) -> Any:
        r = sessions.response(who, rid)
        return streamed(who, r) if stream else (wire.record_detail(r) if detail else wire.response(r))

    @app.post("/v1/responses/{rid}/cancel")
    async def cancel_response(rid: str, who: Member = member) -> dict:
        r = sessions.cancel(who, rid)
        if not r.final:
            r = await sessions.wait(rid)
        return wire.response(r)

    @app.get("/v1/responses/{rid}/captures")
    def list_captures(rid: str, who: Member = member) -> dict:
        return {"object": "list", "data": sessions.captures(who, rid)}

    @app.get("/v1/responses/{rid}/captures/{name:path}")
    def get_capture(rid: str, name: str, who: Member = member) -> Response:
        return Response(sessions.capture(who, rid, name), media_type="application/octet-stream")

    # sessions
    @app.get("/v1/sessions")
    def list_sessions(who: Member = member) -> dict:
        return {"object": "list", "data": [wire.session(s) for s in sessions.sessions(who)]}

    @app.get("/v1/sessions/{sid}")
    def get_session(sid: str, who: Member = member) -> dict:
        return wire.session(sessions.session(who, sid))

    @app.post("/v1/sessions/{sid}/interrupt")
    def interrupt(sid: str, req: wire.InterruptRequest, who: Member = member) -> dict:
        return wire.response(sessions.interrupt(who, sid, req.text))

    @app.get("/v1/sessions/{sid}/trace")
    def trace(sid: str, who: Member = member) -> dict:
        lines = sessions.trace(who, sid)
        for line in lines:
            if line["kind"] == "response":
                line["body"] = wire.record_detail(Record(**line["body"]))
        return {"object": "list", "data": lines}

    @app.get("/v1/sessions/{sid}/archive")
    def archive(sid: str, who: Member = member) -> Response:
        return Response(sessions.archive(who, sid), media_type="application/gzip",
                        headers={"Content-Disposition": f'attachment; filename="{sid}.tar.gz"'})

    @app.delete("/v1/sessions/{sid}")
    def delete_session(sid: str, who: Member = member) -> dict:
        sessions.delete(who, sid)
        return {"deleted": sid}

    app.include_router(deployer.router(store, sessions, principals))
    app.include_router(internal.router(store, sessions, principals, VERSION))

    if (CONSOLE / "index.html").is_file():
        @app.get("/", include_in_schema=False)
        def console() -> FileResponse:
            return FileResponse(CONSOLE / "index.html")

        @app.get("/console/{path:path}", include_in_schema=False)
        def console_file(path: str) -> FileResponse:
            target = (CONSOLE / path).resolve()
            if not target.is_file() or CONSOLE not in target.parents:
                raise HTTPException(404)
            return FileResponse(target)

    return app
