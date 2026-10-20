"""Layer 5: sessions. A session is one harness, one provider, one workspace, the CLI's own conversation
(`resume`) and every response in it, one at a time. Every front end drives harnesses through
`Sessions`, and Python callers need nothing else:

- `start(ask)` checks the request and returns at once. With no `previous` it makes a session; with one
  it continues that response's session, which stays on its harness and provider; while a response
  runs, a second is a Conflict. `model` is `harness[@provider][/model]`; with no provider, the one
  registered for the harness's default URL and shape. The response runs in the background, owned by
  the service: it runs to its end and is recorded whether or not anyone follows it.
- `follow(id)` yields every event of a session (or of one of its responses) from the first, as it
  comes, until the session is idle, across continuations; a finished response is replayed.
- `interrupt(id, text)` degrades as the contract says: an idle session is continued with the text;
  a running `steered` response is steered, if the line is delivered; otherwise the response is
  stopped and the session continued with the text (`continued`, or `responded` for a harness that
  promises nothing more). `stop(id)` stops gracefully, kills after the timeout, and says which.
- Steers a response didn't take are sent again, joined, as a response that continues the session
  when it ends `ok`, and reported undelivered when it doesn't. No steer is sent after a stop.
- `artifacts(id)` is everything a response produced, so far while it runs: stdout and stderr byte
  for byte, the diff, the changed files, the file list, the reported home artifacts, HI_OUTPUT.
- `recover()` at startup: a response a restart cut off is failed (`server_restarted`), its resume
  kept; every session is idle; what runs left behind is swept.

Everything lives under the data directory: `providers/`, `harnesses/`, `tools/`, `sessions/`,
`responses/`, `logs/`, `runs/` (each response's HI_OUTPUT, outside the workspace) and `workspaces/`.
"""
from __future__ import annotations

import asyncio
import copy
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, AsyncIterator, Mapping

from .errors import Conflict, Invalid, NotFound
from .harness import HarnessFolder, Installer, Placement, Request, Response, Result, session_token
from .harness.contract import OUTPUT, read_output, reported
from .runtimes import Provider, owner_of
from .store import JsonStore, Registry, decode, encode
from .workspace import Workspace

TIERS = ("steered", "continued", "responded")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def parse_model(model: Any) -> tuple[str, str | None, str]:
    """`harness[@provider][/model]` -> (harness, provider or None, model or "")."""
    if not isinstance(model, str):
        raise Invalid("model is harness[@provider][/model]")
    head, _, name = model.partition("/")
    harness, at, provider = head.partition("@")
    if not harness or (at and not provider):
        raise Invalid(f"model is harness[@provider][/model], not {model!r}")
    return harness, provider or None, name


@dataclass(frozen=True)
class Ask:
    """A request, as any front end puts it."""
    model: str                                       # harness[@provider][/model]
    task: str
    instructions: str = ""
    files: Mapping[str, str | bytes] = field(default_factory=dict)
    previous: str | None = None                      # the response this one continues
    metadata: Mapping[str, Any] = field(default_factory=dict)
    input: Any = None                                # the front end's own copy of what was asked, kept as given

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or not self.task.strip():
            raise Invalid("a task is some text")
        if not isinstance(self.instructions, str):
            raise Invalid("instructions are text")


@dataclass
class Session:
    id: str
    harness: str
    provider: str
    model: str                                       # the model it asks for, or "" for the harness's own
    interrupt: str                                   # the harness's tier: what an interrupt will do
    workspace: str
    token: str = field(repr=False)                   # its stand-in for the key, under the gateway
    resume: str | None = None                        # the CLI's conversation, as it last reported it
    status: str = "idle"                             # active | idle
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    interrupts: list[dict[str, Any]] = field(default_factory=list)
    responses: list[str] = field(default_factory=list)


@dataclass
class ResponseRecord:
    id: str
    session: str
    model: str                                       # as asked
    harness: str
    provider: str
    request: dict[str, Any]                          # input, instructions and metadata, as asked
    previous: str | None = None
    created_at: float = field(default_factory=time.time)
    status: str = "in_progress"                      # in_progress | completed | failed | incomplete | cancelled
    answer: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None
    resume: str | None = None
    exit_code: int | None = None
    latency_s: float | None = None
    steers: list[dict[str, Any]] = field(default_factory=list)   # {at, input}, as sent
    undelivered: list[str] = field(default_factory=list)          # the steers it didn't take
    stop: str | None = None                          # stopped | killed, when it was asked to stop
    base: str | None = None                          # the workspace's snapshot before it
    commit: str | None = None                        # and after it
    error: dict[str, str] | None = None              # {code, message}
    output: dict[str, Any] = field(default_factory=dict)          # all of HI_OUTPUT
    home: dict[str, Any] = field(default_factory=dict)            # reported artifacts, encoded; None if deleted


@dataclass(frozen=True)
class SessionEvent:
    kind: str                                        # created | stdout | stderr | steer | interrupted | completed
    response: str
    data: bytes = b""                                # output; a steer's or an interrupt's text
    record: ResponseRecord | None = None             # created, completed: the response as it was then
    outcome: str = ""                                # interrupted: continued | responded
    source: str | None = None                        # interrupted: the response it continues
    at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Artifacts:
    stdout: bytes
    stderr: bytes
    diff: str
    changes: dict[str, bytes | None]                 # path -> new content, None if deleted
    files: list[str]                                 # the whole tree
    home: dict[str, bytes | None]                    # reported artifacts under $HOME
    output: dict[str, Any]                           # HI_OUTPUT


class Feed:
    """A session's events while it is active, for any number of followers, each from where it starts."""

    def __init__(self) -> None:
        self.events: list[SessionEvent] = []
        self.closed = False
        self._wake = asyncio.Event()

    def publish(self, event: SessionEvent) -> None:
        self.events.append(event)
        self._wake.set()
        self._wake = asyncio.Event()

    def close(self) -> None:
        self.closed = True
        self._wake.set()

    def start_of(self, rid: str) -> int | None:
        return next((i for i, e in enumerate(self.events) if e.response == rid), None)

    async def follow(self, start: int = 0) -> AsyncIterator[SessionEvent]:
        i = start
        while True:
            while i < len(self.events):
                yield self.events[i]
                i += 1
            if self.closed:
                return
            await self._wake.wait()


@dataclass(eq=False)
class Live:
    """The response a session is running."""
    record: ResponseRecord
    request: Request
    new_session: bool
    response: Response | None = None
    startup: asyncio.Future | None = None
    stop_asked: bool = False
    stop_timeout: float | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)

    def stop(self, timeout_s: float | None) -> None:
        if self.response:
            self.response.stop(timeout_s)
            return
        self.stop_asked, self.stop_timeout = True, timeout_s
        if self.startup:
            self.startup.cancel()


@dataclass(eq=False)
class Pending:
    """An interrupt waiting for the response it stopped to end, to continue the session with its text."""
    outcome: str
    instructions: str | None
    texts: list[str] = field(default_factory=list)
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())


def status_of(result: Result) -> str:
    if result.status == "ok":
        return "completed"
    if result.stop == "timeout":
        return "incomplete"
    return "cancelled" if result.stop else "failed"


async def nothing() -> AsyncIterator[SessionEvent]:
    return
    yield


class Sessions:
    def __init__(self, data: Path, placement: Placement | None = None):
        self.data = Path(data).absolute()
        self.placement = placement or Placement(owner=owner_of(self.data))
        self.registry = Registry(self.data, Installer(self.data / "tools", self.placement))
        self.store: JsonStore[Session] = JsonStore(self.data / "sessions", lambda d: Session(**d), private=True)
        self.records: JsonStore[ResponseRecord] = JsonStore(self.data / "responses", lambda d: ResponseRecord(**d))
        self.logs, self.runs, self.workspaces = self.data / "logs", self.data / "runs", self.data / "workspaces"
        self._active: dict[str, Session] = {}        # by id: the one copy of an active session
        self._tasks: dict[str, asyncio.Task] = {}    # its responses, one after another
        self._live: dict[str, Live] = {}
        self._feeds: dict[str, Feed] = {}
        self._pending: dict[str, Pending] = {}
        self._halted: set[str] = set()               # asked to stop: nothing more starts

    # reading
    def session(self, sid: str) -> Session:
        found = self.store.get(sid) if isinstance(sid, str) and sid.startswith("sess_") and "/" not in sid else None
        if found is None:
            raise NotFound(f"no session {sid!r}")
        return found

    def sessions(self) -> list[Session]:
        return sorted(self.store.list(), key=lambda s: s.created_at)

    def response(self, rid: str) -> ResponseRecord:
        found = self.records.get(rid) if isinstance(rid, str) and rid.startswith("resp_") and "/" not in rid else None
        if found is None:
            raise NotFound(f"no response {rid!r}")
        return found

    async def wait(self, rid: str) -> ResponseRecord:
        """The response, once it has ended."""
        record = self.response(rid)
        live = self._live.get(record.session)
        if live and live.record.id == rid:
            await live.done.wait()
        return self.response(rid)

    def follow(self, ident: str) -> AsyncIterator[SessionEvent]:
        """Every event of a session, or from one of its responses on, until the session is idle."""
        if isinstance(ident, str) and ident.startswith("resp_"):
            record = self.response(ident)
            feed = self._feeds.get(record.session)
            start = feed.start_of(ident) if feed else None
            return feed.follow(start) if start is not None else self._replay(record)
        self.session(ident)
        feed = self._feeds.get(ident)
        return feed.follow() if feed else nothing()

    def artifacts(self, rid: str) -> Artifacts:
        """Everything the response produced: so far, while it runs."""
        record = self.response(rid)
        ws = Workspace(Path(self.session(record.session).workspace))
        live = self._live.get(record.session)
        response = live.response if live and live.record.id == rid and record.status == "in_progress" else None
        head = record.commit
        if record.base:
            changed, deleted = ws.changes(record.base, head)
            diff, changes = ws.diff(record.base, head), {**{p: ws.read(p, head) for p in changed},
                                                         **{p: None for p in deleted}}
        else:
            diff, changes = "", {}
        files = ws.files(head) if (ws.history / "HEAD").exists() else []
        if response:
            home = reported(response.folder, ws, response.prepared)
            output = read_output(response.prepared.output)
        else:
            home = {p: None if c is None else decode(c) for p, c in record.home.items()}
            output = record.output
        return Artifacts(self._log(rid, "stdout"), self._log(rid, "stderr"), diff, changes, files, home, output)

    # driving
    async def start(self, ask: Ask) -> Session:
        """Check the request and start its response; return its session at once."""
        if ask.previous:
            previous = self.response(ask.previous)
            session = self._current(previous.session)
            harness, provider, model = parse_model(ask.model)
            if harness != session.harness or (provider and provider != session.provider):
                raise Invalid(f"a continued session stays on its harness and provider: "
                              f"{session.harness}@{session.provider}, not {ask.model}")
            if session.id in self._tasks:
                raise Conflict(f"session {session.id} has a response in progress: interrupt it instead")
            self._folder(harness)
            self._provider_entry(session.provider)
            session.model = model or session.model
            request = Request(ask.task, session.resume, ask.instructions, session.model, ask.files)
        else:
            harness, name, model = parse_model(ask.model)
            folder = self._folder(harness)
            entry = self._choose_provider(folder, name)
            request = Request(ask.task, None, ask.instructions, model, ask.files)
            sid = new_id("sess")
            session = Session(id=sid, harness=folder.name, provider=entry.name, model=model,
                              interrupt=folder.run.interrupt, workspace=str(self.workspaces / sid),
                              token=session_token(entry.api))
        install = self.registry.install(harness)
        if install.state == "failed":
            raise Invalid(f"harness {harness!r} failed to install; PUT it again to retry. {install.error}")
        self._activate(session)
        live = self._new_response(session, ask.model, ask, request, ask.previous)
        self._tasks[session.id] = asyncio.ensure_future(self._run(session, live))
        return copy.deepcopy(session)

    async def interrupt(self, sid: str, text: str, instructions: str | None = None) -> tuple[str, ResponseRecord]:
        """Put `text` into the session: `steered`, `continued` or `responded`, and the response that took it."""
        session = self.session(sid)
        if not isinstance(text, str) or not text.strip():
            raise Invalid("an interrupt is some text")
        while True:
            if sid not in self._tasks:
                last = self.response(session.responses[-1])
                started = await self.start(Ask(last.model, text, instructions=last.request.get("instructions", "")
                                               if instructions is None else instructions, previous=last.id))
                record = self.response(started.responses[-1])
                self._log_interrupt(sid, input=text, outcome="continued", response=record.id)
                return "continued", record
            if sid in self._halted:
                raise Conflict(f"session {sid} is stopping")
            live = self._live[sid]
            if self._active[sid].interrupt != "steered" or sid in self._pending or live.stop_asked:
                break
            await live.started.wait()
            if self._live.get(sid) is not live:
                continue                             # it ended, or a continuation took its place
            try:
                if live.response is None:
                    raise Invalid("it never started")
                await live.response.steer(text)
            except Invalid:
                if self._live.get(sid) is not live or sid not in self._tasks:
                    continue
                break
            self._log_interrupt(sid, input=text, outcome="steered", response=live.record.id)
            return "steered", self.response(live.record.id)
        tier = self._active[sid].interrupt
        outcome = "responded" if tier == "responded" else "continued"
        pending = self._pending.setdefault(sid, Pending(outcome, instructions))
        pending.texts.append(text)
        self._live[sid].stop(None)
        record = await asyncio.shield(pending.future)
        return outcome, copy.deepcopy(record)

    async def stop(self, sid: str, timeout_s: float | None = None) -> str:
        """Stop what the session is running: `stopped`, `killed` (it didn't stop in time) or `idle`."""
        self.session(sid)
        task = self._tasks.get(sid)
        if task is None:
            return "idle"
        self._halted.add(sid)
        self._drop_pending(sid)
        live = self._live[sid]
        live.stop(timeout_s)
        await asyncio.wait([task])
        outcome = "killed" if self.response(live.record.id).stop == "killed" else "stopped"
        self._log_interrupt(sid, outcome=outcome, response=live.record.id)
        return outcome

    async def recover(self) -> None:
        """At startup: close what a restart cut off, keeping its resume, and sweep what it left behind."""
        for record in self.records.list():
            if record.status != "in_progress":
                continue
            out = read_output(self.runs / record.id / OUTPUT)
            resume = out.get("resume") if isinstance(out.get("resume"), str) and out.get("resume") else None
            session = self.store.get(record.session)
            if record.base and session:
                record.commit = Workspace(Path(session.workspace)).snapshot("after a restart")
            record.status, record.resume, record.output = "failed", resume, out
            record.error = {"code": "server_restarted", "message": "the server restarted while this response ran"}
            self.records.put(record.id, record)
            if session and resume:
                session.resume = resume
                self.store.put(session.id, session)
        for session in self.store.list():
            if session.status != "idle":
                session.status = "idle"
                self.store.put(session.id, session)
        await self.placement.recover()
        for folder in self.registry.harnesses():
            self.registry.install(folder.name)

    async def close(self) -> None:
        """Stop everything running, now, and every install."""
        for sid in list(self._tasks):
            self._halted.add(sid)
            self._drop_pending(sid)
            self._live[sid].stop(0)
        if self._tasks:
            await asyncio.wait(list(self._tasks.values()))
        await self.registry.close()

    # the work
    def _current(self, sid: str) -> Session:
        return self._active.get(sid) or self.session(sid)

    def _folder(self, name: str) -> HarnessFolder:
        try:
            return self.registry.harness(name)
        except NotFound:
            raise Invalid(f"no harness {name!r}") from None

    def _provider_entry(self, name: str):
        try:
            return self.registry.provider(name)
        except NotFound:
            raise Invalid(f"no provider {name!r}") from None

    def _choose_provider(self, folder: HarnessFolder, name: str | None):
        """The provider named, or the one registered for the harness's default URL and shape."""
        if name:
            entry = self._provider_entry(name)
        else:
            want = (folder.provider.url.rstrip("/"), folder.provider.api)
            entry = next((p for p in self.registry.providers() if (p.url.rstrip("/"), p.api) == want), None)
            if entry is None:
                raise Invalid(f"no provider for {folder.name}: register one for {want[0]} ({want[1]}), "
                              f"or name one: {folder.name}@<provider>")
        if entry.api not in folder.apis:
            raise Invalid(f"{folder.name} speaks {', '.join(folder.apis)}, not {entry.api} ({entry.name})")
        return entry

    def _activate(self, session: Session) -> None:
        session.status, session.updated_at = "active", time.time()
        self._active[session.id] = session
        self._feeds[session.id] = Feed()
        self.store.put(session.id, session)

    def _new_response(self, session: Session, model: str, ask: Ask, request: Request, previous: str | None,
                      interrupted: str = "") -> Live:
        rid = new_id("resp")
        record = ResponseRecord(id=rid, session=session.id, model=model, harness=session.harness,
                                provider=session.provider, previous=previous,
                                request={"input": ask.task if ask.input is None else ask.input,
                                         "instructions": ask.instructions, "metadata": dict(ask.metadata)})
        self.records.put(rid, record)
        session.responses.append(rid)
        session.updated_at = time.time()
        self.store.put(session.id, session)
        live = self._live[session.id] = Live(record, request, new_session=not previous)
        feed = self._feeds[session.id]
        if interrupted:
            feed.publish(SessionEvent("interrupted", rid, ask.task.encode(), outcome=interrupted, source=previous))
        feed.publish(SessionEvent("created", rid, record=copy.deepcopy(record)))
        return live

    async def _run(self, session: Session, live: Live) -> None:
        """Run the session's responses, one after another, until nothing continues it; then it is idle."""
        sid = session.id
        try:
            while live:
                try:
                    result = await self._one(session, live)
                finally:
                    live.done.set()
                live = self._next(session, live.record, result)
        finally:
            self._drop_pending(sid)
            session.status, session.updated_at = "idle", time.time()
            self.store.put(sid, session)
            self._feeds.pop(sid).close()
            for held in (self._active, self._tasks, self._live):
                held.pop(sid, None)
            self._halted.discard(sid)

    async def _one(self, session: Session, live: Live) -> Result | None:
        """One response, start to end; its record is finished whatever happens."""
        record = live.record
        try:
            if live.stop_asked:
                return self._unstarted(session, record, "cancelled", stop="stopped")
            live.startup = asyncio.ensure_future(self._begin(session, live))
            try:
                live.response = await live.startup
            except asyncio.CancelledError:
                if not live.stop_asked:
                    raise
                return self._unstarted(session, record, "cancelled", stop="stopped")
            except Exception as e:
                return self._unstarted(session, record, "failed", error=("failed_to_start", str(e)))
            finally:
                live.started.set()
            if live.stop_asked:
                live.response.stop(live.stop_timeout)
            record.base = live.response.prepared.base
            self.records.put(record.id, record)
            await self._pump(session, record, live.response)
            result = await live.response.result()
        except asyncio.CancelledError:
            raise
        except Exception as e:                       # a bug, not the harness: the record still gets an end
            return self._unstarted(session, record, "failed", error=("internal_error", f"{type(e).__name__}: {e}"))
        self._finish(session, record, result)
        return result

    async def _begin(self, session: Session, live: Live) -> Response:
        folder, installed = await self.registry.ready(session.harness)
        entry = self.registry.provider(session.provider)
        provider = Provider(entry.url, entry.api, entry.key, token=session.token)
        return await Response.start(folder, installed, Workspace(Path(session.workspace)), live.request,
                                    placement=self.placement, rundir=self.runs / live.record.id, provider=provider,
                                    new_session=live.new_session, session=session.id)

    async def _pump(self, session: Session, record: ResponseRecord, response: Response) -> None:
        """Keep what the harness prints byte for byte, and hand every event to followers as it comes."""
        feed, logs = self._feeds[session.id], {}
        self.logs.mkdir(parents=True, exist_ok=True)
        try:
            async for event in response.events():
                if event.stream == "steer":
                    record.steers.append({"at": time.time(), "input": event.data.decode()})
                    self.records.put(record.id, record)
                    feed.publish(SessionEvent("steer", record.id, event.data))
                    continue
                f: IO[bytes] = logs.get(event.stream) or logs.setdefault(
                    event.stream, open(self.logs / f"{record.id}.{event.stream}", "ab"))
                f.write(event.data)
                f.flush()
                if event.stream in ("stdout", "stderr"):
                    feed.publish(SessionEvent(event.stream, record.id, event.data))
        finally:
            for f in logs.values():
                f.close()

    def _finish(self, session: Session, record: ResponseRecord, result: Result) -> None:
        record.status, record.answer, record.resume = status_of(result), result.answer, result.resume
        record.usage, record.cost_usd, record.output = dict(result.usage), result.cost_usd, dict(result.output)
        record.exit_code, record.base, record.commit = result.outcome.code, result.base, result.commit
        if result.stop:
            record.stop = "killed" if result.outcome.kind == "killed" else "stopped"
        record.undelivered = [s["input"] for s in record.steers[result.steers:]]
        record.home = {p: None if c is None else encode(c) for p, c in result.home.items()}
        if record.status == "failed":
            code = "failed_to_start" if result.outcome.kind == "failed" else "harness_failed"
            record.error = {"code": code, "message": result.answer or f"the harness ended {result.outcome.kind}"}
        session.resume = result.resume or session.resume
        self._ended(session, record)

    def _unstarted(self, session: Session, record: ResponseRecord, status: str, stop: str | None = None,
                   error: tuple[str, str] | None = None) -> None:
        record.status, record.stop = status, stop
        record.error = {"code": error[0], "message": error[1]} if error else None
        record.undelivered = [s["input"] for s in record.steers]
        self._ended(session, record)

    def _ended(self, session: Session, record: ResponseRecord) -> None:
        record.latency_s = round(time.time() - record.created_at, 3)
        self.records.put(record.id, record)
        session.updated_at = time.time()
        self.store.put(session.id, session)
        self._feeds[session.id].publish(SessionEvent("completed", record.id, record=copy.deepcopy(record)))

    def _next(self, session: Session, record: ResponseRecord, result: Result | None) -> Live | None:
        """What continues the session now: an interrupt's text, and the steers it didn't take if it ended ok."""
        sid = session.id
        if sid in self._halted:
            return None
        pending = self._pending.pop(sid, None)
        texts = (record.undelivered if result and result.status == "ok" else []) + (pending.texts if pending else [])
        if not texts:
            return None
        instructions = record.request.get("instructions", "")
        if pending and pending.instructions is not None:
            instructions = pending.instructions
        ask = Ask(record.model, "\n".join(texts), instructions=instructions)
        request = Request(ask.task, resume=session.resume, instructions=instructions, model=session.model)
        live = self._new_response(session, record.model, ask, request, record.id,
                                  interrupted=pending.outcome if pending else "continued")
        if pending:
            self._log_interrupt(sid, input="\n".join(pending.texts), outcome=pending.outcome,
                                response=live.record.id)
            pending.future.set_result(copy.deepcopy(live.record))
        return live

    def _drop_pending(self, sid: str) -> None:
        if (pending := self._pending.pop(sid, None)) and not pending.future.done():
            pending.future.set_exception(Conflict(f"session {sid} was stopped before it could continue"))

    def _log_interrupt(self, sid: str, **entry: Any) -> None:
        session = self._current(sid)
        session.interrupts.append({"at": time.time(), **entry})
        self.store.put(sid, session)

    def _log(self, rid: str, stream: str) -> bytes:
        p = self.logs / f"{rid}.{stream}"
        return p.read_bytes() if p.is_file() else b""

    async def _replay(self, record: ResponseRecord) -> AsyncIterator[SessionEvent]:
        """A finished response's events, from its record and logs."""
        yield SessionEvent("created", record.id, record=record)
        for stream in ("stdout", "stderr"):
            if data := self._log(record.id, stream):
                yield SessionEvent(stream, record.id, data)
        for steer in record.steers:
            yield SessionEvent("steer", record.id, steer["input"].encode(), at=steer["at"])
        yield SessionEvent("completed", record.id, record=record)
