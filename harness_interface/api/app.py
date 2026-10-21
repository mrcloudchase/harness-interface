"""Layer 6: the HTTP routes. A Bearer key names a member of an org; the platform's admin key creates
orgs. Owners register providers, sandboxes and harnesses; every member reads them and makes requests.
`POST /v1/responses` is the OpenAI Responses API; sessions are read, followed, interrupted and
archived. Each route validates, calls the layer below and shapes the reply with `wire`; nothing
else. A refusal is 400 (can't be done), 401, 403, 404 (unknown) or 409 (busy), a malformed body 422,
each `{"detail": …}`. (No `from __future__ import annotations` here: FastAPI reads the route types
at runtime.)"""
import asyncio
import hmac
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib.metadata import version
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from ..errors import Conflict, Invalid, NotFound
from ..runtimes.docker import owner_of
from ..sandboxes import Runtimes
from ..secrets import Vault
from ..sessions import Record, Sessions
from ..store import Member, Store
from . import wire
from .config import Settings

STATUS = {Invalid: 400, NotFound: 404, Conflict: 409}
ADMIN = Member("", "", "admin", 0)


class OrgBody(BaseModel):
    name: str
    owner: str
    max_runs: int = Field(default=4, ge=1)


class MemberBody(BaseModel):
    name: str
    role: str = "member"


class KeyBody(BaseModel):
    label: str = ""


class ProviderBody(BaseModel):
    url: str
    api: str
    key: str = ""


class SandboxBody(BaseModel):
    image: str = ""
    dockerfile: str = ""
    egress: list[str] = []
    memory: str = "4g"
    pids: int = 512


class Service:
    """The server's parts, built from its settings."""

    def __init__(self, settings: Settings, vault: Optional[Vault] = None):
        self.settings = settings
        data = settings.data_dir
        self.store = Store(data, vault or Vault.from_env())
        self.sessions = Sessions(self.store, Runtimes(data / "logs", settings.ca_file, owner_of(data)))

    def running(self, sid: str) -> bool:
        return any(live.record.session == sid for live in self.sessions._live.values())


def create_app(service: Service) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await service.sessions.recover()
        yield
        await service.sessions.close()

    app = FastAPI(title="harness-interface", version=version("harness-interface"), lifespan=lifespan)

    for error, code in STATUS.items():
        @app.exception_handler(error)
        async def refused(_: Request, e: Exception, code: int = code) -> JSONResponse:
            return JSONResponse({"detail": str(e)}, status_code=code)

    store, sessions, settings = service.store, service.sessions, service.settings

    def bearer(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(401, "a Bearer API key is required")
        return auth[7:].strip()

    def principal(request: Request) -> Member:
        token = bearer(request)
        if settings.admin_key and hmac.compare_digest(token, settings.admin_key):
            return ADMIN
        who = store.resolve_key(token)
        if who is None:
            raise HTTPException(401, "unknown or revoked API key")
        return who

    def member(who: Member = Depends(principal)) -> Member:
        if who is ADMIN:
            raise HTTPException(403, "the admin key manages orgs; a member's key does this")
        return who

    def owner(who: Member = Depends(member)) -> Member:
        if not who.owner:
            raise HTTPException(403, "an owner's key does this")
        return who

    def admin(who: Member = Depends(principal)) -> Member:
        if who is not ADMIN:
            raise HTTPException(403, "the admin key does this")
        return who

    # the platform
    @app.post("/v1/orgs")
    def create_org(body: OrgBody, _: Member = Depends(admin)) -> dict:
        org = store.create_org(body.name, body.max_runs)
        store.create_member(org.name, body.owner, "owner")
        key, secret = store.mint_key(org.name, body.owner, "first")
        return {"org": asdict(org), "owner": body.owner, "key": {"id": key.id, "secret": secret}}

    @app.get("/v1/orgs")
    def list_orgs(_: Member = Depends(admin)) -> dict:
        return {"object": "list", "data": [asdict(o) for o in store.orgs()]}

    @app.get("/v1/me")
    def me(who: Member = Depends(member)) -> dict:
        return asdict(who)

    # the org
    @app.post("/v1/members")
    def create_member(body: MemberBody, who: Member = Depends(owner)) -> dict:
        return asdict(store.create_member(who.org, body.name, body.role))

    @app.get("/v1/members")
    def list_members(who: Member = Depends(owner)) -> dict:
        return {"object": "list", "data": [asdict(m) for m in store.members(who.org)]}

    @app.post("/v1/members/{name}/keys")
    def mint_key(name: str, body: KeyBody, who: Member = Depends(member)) -> dict:
        if not (who.owner or who.name == name):
            raise HTTPException(403, "a member mints keys for themselves; an owner for anyone")
        key, secret = store.mint_key(who.org, name, body.label)
        return {**asdict(key), "secret": secret}

    @app.get("/v1/keys")
    def list_keys(who: Member = Depends(member)) -> dict:
        keys = [k for k in store.keys(who.org) if who.owner or k.member == who.name]
        return {"object": "list", "data": [asdict(k) for k in keys]}

    @app.delete("/v1/keys/{key_id}")
    def revoke_key(key_id: str, who: Member = Depends(member)) -> dict:
        keys = {k.id: k for k in store.keys(who.org)}
        if key_id not in keys or not (who.owner or keys[key_id].member == who.name):
            raise NotFound(f"no key {key_id}")
        return asdict(store.revoke_key(who.org, key_id))

    # providers, sandboxes, harnesses
    @app.put("/v1/providers/{name}")
    def put_provider(name: str, body: ProviderBody, who: Member = Depends(owner)) -> dict:
        return store.put_provider(who.org, name, body.url, body.api, body.key).public()

    @app.get("/v1/providers")
    def list_providers(who: Member = Depends(member)) -> dict:
        return {"object": "list", "data": [p.public() for p in store.providers(who.org)]}

    @app.get("/v1/providers/{name}")
    def get_provider(name: str, who: Member = Depends(member)) -> dict:
        return store.provider(who.org, name).public()

    @app.delete("/v1/providers/{name}")
    def delete_provider(name: str, who: Member = Depends(owner)) -> dict:
        store.delete_provider(who.org, name)
        return {"deleted": name}

    @app.put("/v1/sandboxes/{name}")
    def put_sandbox(name: str, body: SandboxBody, who: Member = Depends(owner)) -> dict:
        return store.put_sandbox(who.org, name, image=body.image, dockerfile=body.dockerfile, egress=body.egress,
                                 memory=body.memory, pids=body.pids).public()

    @app.get("/v1/sandboxes")
    def list_sandboxes(who: Member = Depends(member)) -> dict:
        return {"object": "list", "data": [s.public() for s in store.sandboxes(who.org)]}

    @app.get("/v1/sandboxes/{name}")
    def get_sandbox(name: str, who: Member = Depends(member)) -> dict:
        return store.sandbox(who.org, name).public()

    @app.delete("/v1/sandboxes/{name}")
    def delete_sandbox(name: str, who: Member = Depends(owner)) -> dict:
        store.delete_sandbox(who.org, name)
        return {"deleted": name}

    def shaped_harness(org: str, name: str) -> dict:
        h = store.harness(org, name)
        return h.public(store.config(h))

    @app.put("/v1/harnesses/{name}")
    async def put_harness(name: str, request: Request, who: Member = Depends(owner)) -> dict:
        """The body is the folder as a tar archive, gzipped or not."""
        archive = await request.body()
        if not archive:
            raise Invalid("send the harness folder as a tar archive in the request body")
        h = await asyncio.to_thread(store.put_harness, who.org, name, archive)
        return h.public(store.config(h))

    @app.get("/v1/harnesses")
    def list_harnesses(who: Member = Depends(member)) -> dict:
        return {"object": "list", "data": [h.public(store.config(h)) for h in store.harnesses(who.org)]}

    @app.get("/v1/harnesses/{name}")
    def get_harness(name: str, who: Member = Depends(member)) -> dict:
        return shaped_harness(who.org, name)

    @app.delete("/v1/harnesses/{name}")
    def delete_harness(name: str, who: Member = Depends(owner)) -> dict:
        store.delete_harness(who.org, name)
        return {"deleted": name}

    # responses
    def streamed(who: Member, r: Record) -> StreamingResponse:
        async def ended() -> Record:
            return await sessions.wait(r.id)
        return StreamingResponse(wire.stream(r, sessions.follow(who, r.id), ended), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Session-Id": r.session})

    @app.post("/v1/responses")
    async def create_response(req: wire.ResponseRequest, who: Member = Depends(member)) -> Any:
        r = await sessions.create(req.ask(who))
        if req.stream:
            return streamed(who, r)
        if not req.background:
            r = await sessions.wait(r.id)            # a client that leaves does not stop it
        return JSONResponse(wire.response(r), headers={"X-Session-Id": r.session})

    @app.get("/v1/responses/{rid}")
    def get_response(rid: str, stream: bool = False, who: Member = Depends(member)) -> Any:
        r = sessions.response(who, rid)
        return streamed(who, r) if stream else wire.response(r)

    @app.post("/v1/responses/{rid}/cancel")
    async def cancel_response(rid: str, who: Member = Depends(member)) -> dict:
        return wire.response(await sessions.cancel(who, rid))

    # sessions
    @app.get("/v1/sessions")
    def list_sessions(who: Member = Depends(member)) -> dict:
        return {"object": "list", "data": [wire.session(s, service.running(s.id)) for s in sessions.sessions(who)]}

    @app.get("/v1/sessions/{sid}")
    def get_session(sid: str, who: Member = Depends(member)) -> dict:
        return wire.session(sessions.session(who, sid), service.running(sid))

    @app.post("/v1/sessions/{sid}/interrupt")
    async def interrupt(sid: str, req: wire.InterruptRequest, who: Member = Depends(member)) -> dict:
        return wire.response(await sessions.interrupt(who, sid, req.text))

    @app.get("/v1/sessions/{sid}/trace")
    def trace(sid: str, who: Member = Depends(member)) -> dict:
        lines = sessions.trace(who, sid)
        for line in lines:
            if line["kind"] == "response":           # kept as the record; shown as the response object
                line["body"] = wire.response(Record(**line["body"]))
        return {"object": "list", "data": lines}

    @app.get("/v1/sessions/{sid}/archive")
    async def archive(sid: str, who: Member = Depends(member)) -> Response:
        data = await sessions.archive(who, sid)
        return Response(data, media_type="application/gzip",
                        headers={"Content-Disposition": f'attachment; filename="{sid}.tar.gz"'})

    @app.delete("/v1/sessions/{sid}")
    async def delete_session(sid: str, who: Member = Depends(member)) -> dict:
        await sessions.delete(who, sid)
        return {"deleted": sid}

    return app
