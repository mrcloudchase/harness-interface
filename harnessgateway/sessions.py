"""Layer 5: sessions and turns, as the control plane sees them. A turn is one record that is both
the response a member reads and the job a worker claims; it moves queued -> claimed -> in_progress ->
a final status. A session is the chain of turns that share a workspace, kept as snapshots in blobs.

    response/<tenant>/<rid>      the turn: public fields, job fields, and the worker's commands
    session/<tenant>/<sid>       the chain: turns, the workspace snapshot, which turn runs now
    chunk/<tenant>/<rid>:<seq>   a running turn's output, as it arrives, for any number of followers
    trace/<tenant>/<sid>:<seq>   every request, response, steer and cancel, as sent
    usage/<tenant>/<rid>         calls and bytes (the gateway's), seconds, the time, harness and status (the turn's)
    arena/<tenant>/<aid>         a matchup: one prompt, several harnesses' turns, and the winner the member picked

    blobs tenants/<t>/sessions/<sid>/workspace.tgz           the workspace after the last turn
          tenants/<t>/members/<m>/harnesses/<h>/home.tgz    the member's home for that package
          tenants/<t>/sessions/<sid>/turns/<rid>/…           files in, the door log, the provider captures

Workers pull: `claim` hands out the oldest queued turn whose tenant has a free slot, with URLs good for
that turn's blobs and a token good for that turn's provider; `commands` carries cancels and steers back
on each heartbeat; `result` ends it. A worker that stops heartbeating loses its turns, not the sessions.
"""
from __future__ import annotations

import asyncio
import io
import posixpath
import tarfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Mapping

from .errors import Conflict, Invalid, NotFound
from .runtimes.docker import PROVIDER_URL
from .store import Member, Store, Worker

STREAMS = ("stdout", "stderr")
FINAL = ("completed", "failed", "cancelled", "incomplete")
RUNNING = "1"
LOST_AFTER_S = 45
FILE_MAX = 4 * 1024 * 1024                       # of one workspace file read back through the API


@dataclass(frozen=True)
class Ask:
    """One turn, as asked."""
    tenant: str
    member: str
    harness: str
    prompt: str
    instructions: str = ""
    files: Mapping[str, bytes] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    previous: str | None = None
    store: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for rel in self.files:
            n = posixpath.normpath(rel)
            if not rel or rel.startswith("/") or n.startswith("../") or n == "..":
                raise Invalid(f"a file's path is relative and inside the workspace: {rel!r}")


@dataclass
class Record:
    """A turn, as kept. The public part becomes the response object; the rest is the job."""
    id: str
    session: str
    tenant: str
    member: str
    harness: str
    version: str
    provider: str
    model: str
    turn: int
    created: float
    previous: str | None
    store: bool
    metadata: dict[str, str]
    status: str = "queued"
    running: str = "0"                               # "1" while a worker has it: counted against max_runs
    worker: str = ""
    started: float | None = None
    ended: float | None = None
    output: str = ""                                 # what response.sh returned: the response's text
    stdout: str = ""                                 # request.sh's streams, as kept
    stderr: str = ""
    exit_code: int | None = None
    error: str = ""
    truncated: bool = False
    prompt: str = ""
    instructions: str = ""
    files: str = ""                                  # blob key of the request's files, if any
    cancel: bool = False
    interrupts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def final(self) -> bool:
        return self.status in FINAL


@dataclass
class SessionRecord:
    id: str
    tenant: str
    member: str
    harness: str
    version: str
    created: float
    stored: bool = True
    responses: list[str] = field(default_factory=list)
    running: str = ""                                # the turn in progress, if any
    workspace: str = ""                              # blob key of the last snapshot, if any
    snapshot: str = ""                               # the turn that made it (a worker's cache key)

    @property
    def turn(self) -> int:
        return len(self.responses)


def home_blob(tenant: str, member: str, harness: str) -> str:
    return f"tenants/{tenant}/members/{member}/harnesses/{harness}/home.tgz"


def turn_blob(tenant: str, sid: str, rid: str, name: str) -> str:
    return f"tenants/{tenant}/sessions/{sid}/turns/{rid}/{name}"


class Sessions:
    def __init__(self, store: Store, public_url: str, gateway_url: str):
        self.store, self.public_url, self.gateway_url = store, public_url, gateway_url
        self.records, self.blobs = store.records, store.blobs

    # records
    def _put_session(self, s: SessionRecord) -> None:
        self.records.put("session", s.tenant, s.id, asdict(s))

    def _put_record(self, r: Record) -> None:
        self.records.put("response", r.tenant, r.id, asdict(r))

    def _session_by_id(self, sid: str) -> SessionRecord:
        found = self.records.find("session", sid) if sid.startswith("sess_") else None
        if not found:
            raise NotFound(f"no session {sid}")
        return SessionRecord(**found[1])

    def _record_by_id(self, rid: str) -> Record:
        found = self.records.find("response", rid) if rid.startswith("resp_") else None
        if not found:
            raise NotFound(f"no response {rid}")
        return Record(**found[1])

    def _trace(self, s: SessionRecord, kind: str, rid: str, body: Any) -> None:
        seq = len(self.records.list("trace", s.tenant, f"{s.id}:"))
        self.records.put("trace", s.tenant, f"{s.id}:{seq:06d}", {"at": time.time(), "kind": kind, "response": rid, "body": body})

    @staticmethod
    def _reachable(who: Member, tenant: str, member: str) -> bool:
        return tenant == who.tenant and (who.owner or member == who.name)

    def session(self, who: Member, sid: str) -> SessionRecord:
        s = self._session_by_id(sid)
        if not self._reachable(who, s.tenant, s.member):
            raise NotFound(f"no session {sid}")
        return s

    def response(self, who: Member, rid: str) -> Record:
        r = self._record_by_id(rid)
        if not self._reachable(who, r.tenant, r.member):
            raise NotFound(f"no response {rid}")
        return r

    def sessions(self, who: Member) -> list[SessionRecord]:
        found = [SessionRecord(**d) for d in self.records.list("session", who.tenant)]
        return sorted((s for s in found if self._reachable(who, s.tenant, s.member)), key=lambda s: s.created)

    def records_of(self, who: Member, sid: str) -> list[Record]:
        s = self.session(who, sid)
        return [self._record_by_id(rid) for rid in s.responses]

    def trace(self, who: Member, sid: str) -> list[dict[str, Any]]:
        s = self.session(who, sid)
        return self.records.list("trace", s.tenant, f"{s.id}:")

    # a turn asked
    def create(self, ask: Ask) -> Record:
        """Queue a turn; a worker runs it. Conflict while the session is busy."""
        tenant = self.store.tenant(ask.tenant)
        if tenant.status != "active":
            raise Invalid(f"tenant {tenant.name} is suspended")
        who = self.store.member(ask.tenant, ask.member)
        if ask.previous:
            prev = self._record_by_id(ask.previous)
            if not self._reachable(who, prev.tenant, prev.member):
                raise NotFound(f"no response {ask.previous}")
            s = self._session_by_id(prev.session)
            if not s.stored:
                raise Invalid(f"{ask.previous} was not stored, so it cannot be continued")
            if s.running:
                raise Conflict(f"session {s.id} is running a response")
            if ask.harness != s.harness:
                raise Invalid(f"session {s.id} runs {s.harness}, not {ask.harness}")
            h = self.store.harness(ask.tenant, s.harness)
            version = s.version
        else:
            h = self.store.harness(ask.tenant, ask.harness)
            version = h.current
            s = SessionRecord(f"sess_{uuid.uuid4().hex}", ask.tenant, ask.member, h.name, version, time.time(), ask.store)
        config = h.config(version)
        provider_name = ask.provider or config.provider
        if not provider_name:
            raise Invalid("no provider: name one in the request's model path or in harness.json's defaults")
        provider = self.store.provider(ask.tenant, provider_name)
        rid = f"resp_{uuid.uuid4().hex}"
        files = ""
        if ask.files:
            total = sum(len(b) for b in ask.files.values())
            if total > tenant.ceilings.upload_mb * 1024 * 1024:
                raise Invalid(f"the request's files are over the tenant's upload limit of {tenant.ceilings.upload_mb} MB")
            files = turn_blob(s.tenant, s.id, rid, "files.tgz")
            self.blobs.put(files, pack_files(ask.files))
        r = Record(rid, s.id, s.tenant, s.member, s.harness, version, provider.name, ask.model or config.model, s.turn + 1,
                   time.time(), ask.previous, ask.store, dict(ask.metadata), prompt=ask.prompt, instructions=ask.instructions,
                   files=files)
        s.responses.append(rid)
        s.running = rid
        self._put_session(s)
        self._put_record(r)
        self._trace(s, "request", rid, dict(ask.body))
        return r

    # the worker's side
    def claim(self, worker: Worker) -> dict[str, Any] | None:
        """The oldest queued turn whose tenant has a free slot, as a job, or None."""
        for tenant, rid, doc in self.records.where("response", "status", "queued", limit=50):
            try:
                ceilings = self.store.tenant(tenant).ceilings
            except NotFound:
                continue
            if self.records.count("response", tenant, "running", RUNNING) >= ceilings.max_runs:
                continue
            r = Record(**{**doc, "status": "claimed", "running": RUNNING, "worker": worker.id, "started": time.time()})
            if self.records.update_if("response", tenant, rid, "status", "queued", asdict(r)):
                return self._job(r, ceilings)
        return None

    def _job(self, r: Record, ceilings) -> dict[str, Any]:
        s = self._session_by_id(r.session)
        h = self.store.harness(r.tenant, r.harness)
        config = h.config(r.version)
        provider = self.store.provider(r.tenant, r.provider)
        timeout = min(config.timeout_s, ceilings.run_timeout_s)
        token = self.store.issue_token(r.tenant, provider.name, s.id, r.id, provider.api, timeout + 120)
        home = home_blob(r.tenant, r.member, r.harness)
        get, put = self.blobs.presign_get, self.blobs.presign_put
        return {"id": r.id, "session": s.id, "tenant": r.tenant, "member": r.member, "harness": r.harness, "version": r.version,
                "turn": r.turn, "new_session": r.turn == 1, "model": r.model, "prompt": r.prompt, "instructions": r.instructions,
                "store": r.store, "config": config.as_json(), "limits": ceilings.as_dict(), "timeout_s": timeout,
                "request": self._request_body(s, r), "token": token,
                "provider": {"api": provider.api, "path": provider.path, "url": PROVIDER_URL + provider.path},
                "gateway_url": self.gateway_url, "snapshot": s.snapshot,
                "urls": {"folder": get(self.store.harness_blob(r.tenant, r.harness, r.version), int(timeout) + 600),
                         "workspace": get(s.workspace, int(timeout) + 600) if s.workspace else "",
                         "home": get(home, int(timeout) + 600) if self.blobs.exists(home) else "",
                         "files": get(r.files, int(timeout) + 600) if r.files else "",
                         "workspace_put": put(f"tenants/{r.tenant}/sessions/{s.id}/workspace.tgz", int(timeout) + 600) if r.store else "",
                         "home_put": put(home, int(timeout) + 600),
                         "door_log_put": put(turn_blob(r.tenant, s.id, r.id, "door.log"), int(timeout) + 600)}}

    def _request_body(self, s: SessionRecord, r: Record) -> dict[str, Any]:
        for t in self.records.list("trace", s.tenant, f"{s.id}:"):
            if t["kind"] == "request" and t["response"] == r.id:
                return t["body"]
        return {}

    def started(self, worker: Worker, rid: str) -> None:
        r = self._record_by_id(rid)
        if r.worker == worker.id and r.status == "claimed":
            r.status = "in_progress"
            self._put_record(r)

    def chunks_in(self, worker: Worker, rid: str, chunks: list[dict[str, Any]]) -> None:
        r = self._record_by_id(rid)
        if r.worker != worker.id or r.final:
            raise Conflict(f"{rid} is not this worker's running turn")
        for c in chunks:
            self.records.put("chunk", r.tenant, f"{rid}:{int(c['seq']):08d}", {"stream": c["stream"], "text": c["text"]})

    def commands(self, worker: Worker, running: list[str]) -> dict[str, dict[str, Any]]:
        """What the worker should do to the turns it reports; also its heartbeat."""
        self.store.touch_worker(worker, len(running))
        out: dict[str, dict[str, Any]] = {}
        for rid in running:
            try:
                r = self._record_by_id(rid)
            except NotFound:
                out[rid] = {"cancel": True, "interrupts": []}
                continue
            out[rid] = {"cancel": r.cancel or r.final, "interrupts": r.interrupts}
        return out

    def result(self, worker: Worker, rid: str, body: dict[str, Any]) -> Record:
        """The worker's report ends the turn."""
        r = self._record_by_id(rid)
        if r.worker != worker.id:
            raise Conflict(f"{rid} is not this worker's turn")
        if r.final:
            return r
        s = self._session_by_id(r.session)
        ceilings = self.store.tenant(r.tenant).ceilings
        cap = ceilings.output_mb * 1024 * 1024
        kind, code = body.get("outcome", "failed"), body.get("exit_code")
        texts = {k: str(body.get(k, "")) for k in ("output", "stdout", "stderr")}
        r.truncated = bool(body.get("truncated")) or any(len(t) > cap for t in texts.values())
        r.output, r.stdout, r.stderr = (t[:cap] for t in texts.values())
        r.exit_code, r.ended = code, time.time()
        if kind == "failed":
            r.status, r.error = "failed", str(body.get("error", "the turn could not run"))
        elif kind == "timed_out":
            r.status, r.error = "incomplete", "the turn ran past its timeout"
        elif kind in ("stopped", "killed"):
            r.status = "cancelled"
        else:
            r.status = "completed" if code == 0 else "failed"
            r.error = "" if code == 0 else f"the package exited {code}"
        r.running = "0"
        self._put_record(r)
        usage = self.records.get("usage", r.tenant, rid) or {"calls": 0, "bytes_in": 0, "bytes_out": 0, "seconds": 0}
        self.records.put("usage", r.tenant, rid, {**usage, "seconds": round(float(body.get("seconds", 0)), 1), "at": r.ended,
                                                  "harness": r.harness, "status": r.status})
        if r.store and body.get("snapshot"):
            s.workspace, s.snapshot = f"tenants/{r.tenant}/sessions/{s.id}/workspace.tgz", rid
        if not r.store:
            s.stored = False
        s.running = ""
        self._put_session(s)
        self._trace(s, "response", rid, asdict(r))
        return r

    def sweep_lost(self) -> list[str]:
        """Turns whose worker stopped heartbeating are failed; their sessions go on."""
        lost: list[str] = []
        stale = {w.id for w in self.store.workers() if time.time() - w.last_seen > LOST_AFTER_S}
        for tenant, rid, doc in self.records.where("response", "running", RUNNING, limit=1000):
            if doc["worker"] in stale:
                worker = Worker(doc["worker"], "", 0, 0)
                self.result(worker, rid, {"outcome": "failed", "error": "the worker running it was lost"})
                lost.append(rid)
        return lost

    # following and the rest
    async def wait(self, rid: str, poll_s: float = 0.25) -> Record:
        while not (r := self._record_by_id(rid)).final:
            await asyncio.sleep(poll_s)
        return r

    def follow(self, who: Member, rid: str, poll_s: float = 0.25) -> AsyncIterator[tuple[str, str]]:
        """Its output as it arrives, or whole if it has ended: (stream, text) pairs."""
        r = self.response(who, rid)

        async def live() -> AsyncIterator[tuple[str, str]]:
            seen = 0
            while True:
                chunks = self.records.list("chunk", r.tenant, f"{rid}:")
                for c in chunks[seen:]:
                    yield c["stream"], c["text"]
                seen = len(chunks)
                if self._record_by_id(rid).final:
                    for c in self.records.list("chunk", r.tenant, f"{rid}:")[seen:]:
                        yield c["stream"], c["text"]
                    return
                await asyncio.sleep(poll_s)

        async def replay() -> AsyncIterator[tuple[str, str]]:
            for stream in STREAMS:
                if text := getattr(r, stream):
                    yield stream, text
        return replay() if r.final else live()

    def with_live_streams(self, r: Record) -> Record:
        """A running record with what has streamed so far in its stdout and stderr."""
        if r.final:
            return r
        chunks = self.records.list("chunk", r.tenant, f"{r.id}:")
        r.stdout = "".join(c["text"] for c in chunks if c["stream"] == "stdout")
        r.stderr = "".join(c["text"] for c in chunks if c["stream"] == "stderr")
        return r

    def cancel(self, who: Member, rid: str) -> Record:
        """Ask the worker to stop it; a queued turn ends at once."""
        r = self.response(who, rid)
        if r.final:
            return r
        s = self._session_by_id(r.session)
        self._trace(s, "cancel", rid, {})
        if r.status == "queued" and self.records.update_if("response", r.tenant, rid, "status", "queued",
                                                           asdict(Record(**{**asdict(r), "status": "cancelled", "ended": time.time()}))):
            s.running = ""
            self._put_session(s)
            return self._record_by_id(rid)
        r = self._record_by_id(rid)
        r.cancel = True
        self._put_record(r)
        return r

    def interrupt(self, who: Member, sid: str, text: str) -> Record:
        """Steer the session's running turn: the text reaches request.sh with the package's signal."""
        s = self.session(who, sid)
        if not s.running:
            raise Conflict(f"session {sid} is not running a response")
        r = self._record_by_id(s.running)
        if r.final or r.status == "queued":
            raise Conflict(f"session {sid} is not running a response")
        r.interrupts.append({"seq": len(r.interrupts) + 1, "text": text})
        self._put_record(r)
        self._trace(s, "interrupt", r.id, {"input": text})
        return r

    def archive(self, who: Member, sid: str) -> bytes:
        """The workspace after its last turn, as a gzipped tar."""
        s = self.session(who, sid)
        if not s.stored or not s.workspace:
            raise NotFound(f"session {sid} kept no workspace")
        return self.blobs.get(s.workspace)

    # the workspace's files, from its last snapshot
    def files(self, who: Member, sid: str) -> list[dict[str, Any]]:
        """Every file in the workspace after its last turn: path and size. Nothing before the first
        turn ends, and nothing for a stateless session."""
        s = self.session(who, sid)
        if not s.stored or not s.workspace:
            return []
        out = []
        with tarfile.open(fileobj=io.BytesIO(self.blobs.get(s.workspace)), mode="r:gz") as tar:
            for m in tar:
                if m.isfile():
                    out.append({"path": posixpath.normpath(m.name), "size": m.size})
        return sorted(out, key=lambda f: f["path"])

    def file(self, who: Member, sid: str, path: str, limit: int = FILE_MAX) -> bytes:
        """One file from the workspace's last snapshot, at most `limit` bytes."""
        s = self.session(who, sid)
        wanted = posixpath.normpath(path)
        if not s.stored or not s.workspace or wanted.startswith(("/", "..")):
            raise NotFound(f"no file {path}")
        with tarfile.open(fileobj=io.BytesIO(self.blobs.get(s.workspace)), mode="r:gz") as tar:
            for m in tar:
                if m.isfile() and posixpath.normpath(m.name) == wanted:
                    if m.size > limit:
                        raise Invalid(f"{path} is over {limit // (1024 * 1024)} MB; download the archive")
                    return tar.extractfile(m).read()
        raise NotFound(f"no file {path}")

    # arenas: one prompt, several harnesses, the member's pick
    def create_arena(self, who: Member, prompt: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        if not 2 <= len(entries) <= 6:
            raise Invalid("an arena has two to six entries")
        rows = []
        for e in entries:
            r = self.response(who, str(e.get("response", "")))
            rows.append({"harness": r.harness, "model": f"{r.harness}/{r.provider}/{r.model}", "response": r.id, "session": r.session})
        if len({row["harness"] for row in rows}) < 2:
            raise Invalid("an arena pits different harnesses against each other")
        d = {"id": f"arena_{uuid.uuid4().hex[:12]}", "tenant": who.tenant, "member": who.name, "prompt": (prompt or "")[:4000],
             "entries": rows, "winner": "", "created": time.time()}
        self.records.put("arena", who.tenant, d["id"], d)
        return d

    def arena(self, who: Member, aid: str) -> dict[str, Any]:
        d = self.records.get("arena", who.tenant, aid) if aid.startswith("arena_") else None
        if d is None or not self._reachable(who, d["tenant"], d["member"]):
            raise NotFound(f"no arena {aid}")
        return d

    def arenas(self, who: Member) -> list[dict[str, Any]]:
        found = [d for d in self.records.list("arena", who.tenant) if self._reachable(who, d["tenant"], d["member"])]
        return sorted(found, key=lambda d: -d["created"])

    def pick_winner(self, who: Member, aid: str, winner: str) -> dict[str, Any]:
        d = self.arena(who, aid)
        if winner and winner not in {e["harness"] for e in d["entries"]}:
            raise Invalid("the winner is one of the arena's harnesses")
        d["winner"] = winner
        self.records.put("arena", who.tenant, aid, d)
        return d

    def delete_arena(self, who: Member, aid: str) -> None:
        self.arena(who, aid)
        self.records.delete("arena", who.tenant, aid)

    def leaderboard(self, who: Member) -> list[dict[str, Any]]:
        """Per harness, across the arenas this member can see: runs and wins, most wins first."""
        board: dict[str, dict[str, int]] = {}
        for d in self.arenas(who):
            for e in d["entries"]:
                row = board.setdefault(e["harness"], {"runs": 0, "wins": 0})
                row["runs"] += 1
                row["wins"] += e["harness"] == d["winner"]
        return [{"harness": hn, **v} for hn, v in sorted(board.items(), key=lambda kv: (-kv[1]["wins"], -kv[1]["runs"], kv[0]))]

    def captures(self, who: Member, rid: str) -> list[str]:
        r = self.response(who, rid)
        prefix = turn_blob(r.tenant, r.session, r.id, "")
        return [k[len(prefix):] for k in self.blobs.list(prefix.rstrip("/"))]

    def capture(self, who: Member, rid: str, name: str) -> bytes:
        r = self.response(who, rid)
        if name not in self.captures(who, rid):
            raise NotFound(f"no capture {name}")
        return self.blobs.get(turn_blob(r.tenant, r.session, r.id, name))

    def delete(self, who: Member, sid: str) -> None:
        s = self.session(who, sid)
        if s.running:
            raise Conflict(f"session {sid} is running a response")
        for rid in s.responses:
            for kind in ("response", "usage"):
                self.records.delete(kind, s.tenant, rid)
            for i in range(len(self.records.list("chunk", s.tenant, f"{rid}:"))):
                self.records.delete("chunk", s.tenant, f"{rid}:{i:08d}")
        for i in range(len(self.records.list("trace", s.tenant, f"{sid}:"))):
            self.records.delete("trace", s.tenant, f"{sid}:{i:06d}")
        self.blobs.delete(f"tenants/{s.tenant}/sessions/{sid}")
        self.records.delete("session", s.tenant, sid)


def pack_files(files: Mapping[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, data in files.items():
            info = tarfile.TarInfo(posixpath.normpath(rel))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()
