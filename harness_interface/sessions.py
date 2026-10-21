"""Layer 5: sessions and turns. A turn runs one harness's `request.sh` once in one sandbox against
one provider: the prompt on stdin, stdout and stderr back, the exit code its status. A session is
the directory a stateful turn leaves behind and the next turn continues in.

    <data>/sessions/<org>/<member>/<harness>/home/            the member's $HOME for that harness
    <data>/sessions/<org>/<member>/<harness>/<sid>/session.json
    <data>/sessions/<org>/<member>/<harness>/<sid>/workspace/  where request.sh runs
    <data>/sessions/<org>/<member>/<harness>/<sid>/run/        $HI_DIR: the interrupt file, scratch
    <data>/sessions/<org>/<member>/<harness>/<sid>/responses/<rid>.json
    <data>/sessions/<org>/<member>/<harness>/<sid>/trace.jsonl  every request and response body, as sent

Seeds are copied, never read: `seeds/project` into the workspace when the session starts (a file
already there wins), `seeds/user` into the member's home on its first use, `seeds/org` into the home
on every turn (it wins). A turn's variables are HI_WORKSPACE, HOME, HI_DIR, HI_SESSION, HI_RESPONSE,
HI_TURN, HI_MODEL, HI_INSTRUCTIONS, HI_HARNESS_DIR, HI_TOOLS, PATH, HI_PROVIDER_URL,
HI_PROVIDER_KEY_FILE, and the names harness.json's provider_env asks for, set to the gateway's URL
and the session's token. The provider's key is opened only to start the run's door.

A steer writes `$HI_DIR/interrupt` and sends the harness's signal; a cancel sends SIGTERM, then a
kill. One turn at a time per session; `max_runs` at a time per org. A turn with `store: false`
leaves its response and trace and nothing else.
"""
from __future__ import annotations

import asyncio
import codecs
import io
import json
import posixpath
import secrets
import shutil
import tarfile
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

from . import harness as contract
from .errors import Conflict, Invalid, NotFound
from .execution import Execution, Outcome, Spec
from .runtimes.docker import ContainerExecution, Provider, signal, sweep
from .sandboxes import Runtimes, path_with
from .store import JsonStore, Member, Store

STREAMS = ("stdout", "stderr")
STATUSES = ("in_progress", "completed", "failed", "cancelled", "incomplete")


def session_token(api: str) -> str:
    """A session's stand-in for its key under the gateway, shaped like a real one for CLIs that check."""
    return ("sk-ant-api03-hi-" if api == "anthropic-messages" else "sk-hi-") + secrets.token_hex(24)


@dataclass(frozen=True)
class Ask:
    """One turn, as asked."""
    org: str
    member: str
    harness: str
    prompt: str
    instructions: str = ""
    files: Mapping[str, bytes] = field(default_factory=dict)   # workspace path -> content
    sandbox: str = ""                                # overrides of the harness's defaults
    provider: str = ""
    model: str = ""
    previous: str | None = None                      # the response to continue after
    store: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, Any] = field(default_factory=dict)      # the request as sent, for the trace

    def __post_init__(self) -> None:
        for rel in self.files:
            n = posixpath.normpath(rel)
            if not rel or n.startswith(("/", "../")) or n == "..":
                raise Invalid(f"a file's path is relative and inside the workspace: {rel!r}")


@dataclass
class Record:
    """A response, as kept."""
    id: str
    session: str
    org: str
    member: str
    harness: str
    version: str
    sandbox: str
    provider: str
    model: str
    turn: int
    created: float
    previous: str | None
    store: bool
    metadata: dict[str, str]
    status: str = "in_progress"
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    error: str = ""
    ended: float | None = None


@dataclass
class SessionRecord:
    id: str
    org: str
    member: str
    harness: str
    version: str
    created: float
    stored: bool = True
    responses: list[str] = field(default_factory=list)

    @property
    def turn(self) -> int:
        return len(self.responses)


class Feed:
    """A running response's output, for any number of followers, each from the start."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.closed = False
        self._wake = asyncio.Event()
        self._decoders = {s: codecs.getincrementaldecoder("utf-8")(errors="replace") for s in STREAMS}

    def publish(self, stream: str, data: bytes) -> None:
        if text := self._decoders[stream].decode(data):
            self.events.append((stream, text))
            self._wake.set()
            self._wake = asyncio.Event()

    def close(self) -> None:
        for stream, decoder in self._decoders.items():
            if text := decoder.decode(b"", final=True):
                self.events.append((stream, text))
        self.closed = True
        self._wake.set()

    def text(self, stream: str) -> str:
        return "".join(t for s, t in self.events if s == stream)

    async def follow(self) -> AsyncIterator[tuple[str, str]]:
        i = 0
        while True:
            while i < len(self.events):
                yield self.events[i]
                i += 1
            if self.closed:
                return
            await self._wake.wait()


@dataclass(eq=False)
class Live:
    record: Record
    config: contract.Config
    feed: Feed = field(default_factory=Feed)
    execution: Execution | None = None
    task: asyncio.Task | None = None
    stop_asked: bool = False


class Sessions:
    def __init__(self, store: Store, runtimes: Runtimes):
        self.store, self.runtimes = store, runtimes
        self._live: dict[str, Live] = {}             # by response id
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._index = JsonStore(store.root / "index", dict)

    # paths and records
    def _dir(self, s: SessionRecord) -> Path:
        return self.store.sessions_root / s.org / s.member / s.harness / s.id

    def _home(self, org: str, member: str, harness: str) -> Path:
        return self.store.sessions_root / org / member / harness / "home"

    def _save_session(self, s: SessionRecord) -> None:
        JsonStore(self._dir(s), lambda d: SessionRecord(**d)).put("session", s)

    def _save_record(self, s: SessionRecord, r: Record) -> None:
        JsonStore(self._dir(s) / "responses", lambda d: Record(**d)).put(r.id, r)

    def _trace(self, s: SessionRecord, kind: str, rid: str, body: Any) -> None:
        with open(self._dir(s) / "trace.jsonl", "a") as f:
            f.write(json.dumps({"at": time.time(), "kind": kind, "response": rid, "body": body}) + "\n")

    def _session_by_id(self, sid: str) -> SessionRecord:
        entry = self._index.get(sid) if sid.startswith("sess_") and sid[5:].isalnum() else None
        s = JsonStore(self.store.sessions_root / entry["path"], lambda d: SessionRecord(**d)).get("session") if entry else None
        if s is None:
            raise NotFound(f"no session {sid}")
        return s

    def _record_by_id(self, rid: str) -> tuple[SessionRecord, Record]:
        entry = self._index.get(rid) if rid.startswith("resp_") and rid[5:].isalnum() else None
        if not entry:
            raise NotFound(f"no response {rid}")
        s = self._session_by_id(entry["session"])
        r = JsonStore(self._dir(s) / "responses", lambda d: Record(**d)).get(rid)
        if r is None:
            raise NotFound(f"no response {rid}")
        return s, r

    @staticmethod
    def _reachable(who: Member, s: SessionRecord) -> bool:
        return s.org == who.org and (who.owner or s.member == who.name)

    def session(self, who: Member, sid: str) -> SessionRecord:
        s = self._session_by_id(sid)
        if not self._reachable(who, s):
            raise NotFound(f"no session {sid}")
        return s

    def sessions(self, who: Member) -> list[SessionRecord]:
        base = self.store.sessions_root / who.org
        found = [JsonStore(p.parent, lambda d: SessionRecord(**d)).get("session")
                 for p in base.glob("*/*/sess_*/session.json")] if base.is_dir() else []
        return sorted((s for s in found if s and self._reachable(who, s)), key=lambda s: s.created)

    def response(self, who: Member, rid: str) -> Record:
        s, r = self._record_by_id(rid)
        if not self._reachable(who, s):
            raise NotFound(f"no response {rid}")
        return r

    def records(self, who: Member, sid: str) -> list[Record]:
        s = self.session(who, sid)
        return [self._record_by_id(rid)[1] for rid in s.responses]

    def trace(self, who: Member, sid: str) -> list[dict[str, Any]]:
        p = self._dir(self.session(who, sid)) / "trace.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.is_file() else []

    # the turn
    async def create(self, ask: Ask) -> Record:
        """Start a turn; it runs on after this returns. Conflict while the session is busy."""
        who = self.store.member(ask.org, ask.member)
        if ask.previous:
            s, prev = self._record_by_id(ask.previous)
            if not self._reachable(who, s):
                raise NotFound(f"no response {ask.previous}")
            if not s.stored:
                raise Invalid(f"{ask.previous} was not stored, so it cannot be continued")
            if any(live.record.session == s.id for live in self._live.values()):
                raise Conflict(f"session {s.id} is running a response")
            h = self.store.harness(ask.org, s.harness, s.version)
        else:
            h = self.store.harness(ask.org, ask.harness)
            s = SessionRecord(f"sess_{uuid.uuid4().hex}", ask.org, ask.member, h.name, h.digest, time.time(), ask.store)
        config = self.store.config(h)
        names = {"sandbox": ask.sandbox or config.sandbox, "provider": ask.provider or config.provider}
        for kind, name in names.items():
            if not name:
                raise Invalid(f"no {kind}: name one in the request's metadata or in harness.json's defaults")
        sandbox, provider = self.store.sandbox(ask.org, names["sandbox"]), self.store.provider(ask.org, names["provider"])
        folder, home, workspace, rundir = self.store.folder(h), self._home(ask.org, ask.member, h.name), *self._paths(s)
        await asyncio.to_thread(self._prepare, s, folder, home, workspace, rundir, ask.files, new=not ask.previous)
        record = Record(f"resp_{uuid.uuid4().hex}", s.id, s.org, s.member, s.harness, s.version, sandbox.name,
                        provider.name, ask.model or config.model, s.turn + 1, time.time(), ask.previous, ask.store,
                        dict(ask.metadata))
        s.responses.append(record.id)
        self._save_session(s)
        self._save_record(s, record)
        self._index.put(s.id, {"path": str(self._dir(s).relative_to(self.store.sessions_root))})
        self._index.put(record.id, {"session": s.id})
        self._trace(s, "request", record.id, dict(ask.body))
        live = Live(record, config)
        self._live[record.id] = live
        live.task = asyncio.create_task(self._run(live, s, h, folder, home, workspace, rundir, sandbox, provider, ask))
        return record

    def _paths(self, s: SessionRecord) -> tuple[Path, Path]:
        d = self._dir(s)
        return d / "workspace", d / "run"

    def _prepare(self, s: SessionRecord, folder: Path, home: Path, workspace: Path, rundir: Path,
                 files: Mapping[str, bytes], new: bool) -> None:
        """The session's directories, seeded, and the request's files in the workspace."""
        for p in (workspace, rundir, home):
            p.mkdir(parents=True, exist_ok=True)
        (rundir / "interrupt").unlink(missing_ok=True)
        if new and (project := contract.seed(folder, "project")):
            contract.copy_seed(project, workspace, overwrite=False)
        if not (home / ".hi-seeded").exists():
            if user := contract.seed(folder, "user"):
                contract.copy_seed(user, home, overwrite=False)
            (home / ".hi-seeded").write_text(s.harness)
        if org := contract.seed(folder, "org"):
            contract.copy_seed(org, home, overwrite=True)
        for rel, data in files.items():
            dest = workspace / posixpath.normpath(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

    async def _run(self, live: Live, s: SessionRecord, h, folder: Path, home: Path, workspace: Path, rundir: Path,
                   sandbox, provider, ask: Ask) -> None:
        record, config = live.record, live.config
        outcome: Outcome | None = None
        try:
            async with self._slot(s.org):
                image = await self.runtimes.image_for(sandbox)
                tools = await self.runtimes.tools_for(folder, config, self.store.tools_root(h), sandbox, image)
                token = session_token(provider.api)
                prov = Provider(provider.url, provider.api, self.store.open_key(provider), "gateway", token)
                runtime = self.runtimes.runtime(image, sandbox, read_only=(folder, tools), writable=(home, rundir),
                                                provider=prov)
                env = {"HI_WORKSPACE": str(workspace), "HOME": str(home), "HI_DIR": str(rundir), "HI_SESSION": s.id,
                       "HI_RESPONSE": record.id, "HI_TURN": str(record.turn), "HI_MODEL": record.model,
                       "HI_INSTRUCTIONS": ask.instructions, "HI_HARNESS_DIR": str(folder), "HI_TOOLS": str(tools),
                       "PATH": path_with(tools), "HI_PROVIDER_URL": runtime.provider_url or "",
                       "HI_PROVIDER_KEY_FILE": str(runtime.key_path or "")}
                for name, value in ((config.key_env, token), (config.url_env, runtime.provider_url or "")):
                    if name:
                        env[name] = value
                spec = Spec(("bash", str(folder / "request.sh")), input=ask.prompt.encode(), env=env,
                            workspace=workspace, timeout_s=config.timeout_s)
                live.execution = await runtime.start(spec)
                if live.stop_asked:
                    live.execution.stop(config.stop_timeout_s)
                with open(self._dir(s) / "door.log", "ab") as door_log:
                    async for event in live.execution.events():
                        if event.stream in STREAMS:
                            live.feed.publish(event.stream, event.data)
                        else:
                            door_log.write(event.data)
                outcome = await live.execution.wait()
        except asyncio.CancelledError:
            outcome = Outcome.killed()
        except Exception as e:                       # the run could not be set up: that is the response
            outcome = Outcome.failed(str(e) or repr(e))
        finally:
            live.feed.close()
            self._finish(live, s, workspace, rundir, outcome or Outcome.killed())
            self._live.pop(record.id, None)

    def _finish(self, live: Live, s: SessionRecord, workspace: Path, rundir: Path, outcome: Outcome) -> None:
        r = live.record
        r.stdout, r.stderr, r.ended = live.feed.text("stdout"), live.feed.text("stderr"), time.time()
        if outcome.kind == "failed":
            r.status, r.error = "failed", outcome.reason
        elif outcome.kind == "timed_out":
            r.status, r.error = "incomplete", f"request.sh ran past {live.config.timeout_s:g} seconds"
        elif outcome.kind in ("stopped", "killed"):
            r.status, r.exit_code = "cancelled", outcome.code
        else:
            r.exit_code = outcome.code
            r.status = "completed" if outcome.code == 0 else "failed"
            r.error = "" if outcome.code == 0 else f"request.sh exited {outcome.code}"
        self._save_record(s, r)
        self._trace(s, "response", r.id, asdict(r))
        if not r.store:
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.rmtree(rundir, ignore_errors=True)
            s.stored = False
            self._save_session(s)

    def _slot(self, org: str) -> asyncio.Semaphore:
        if org not in self._slots:
            self._slots[org] = asyncio.Semaphore(self.store.org(org).max_runs)
        return self._slots[org]

    async def wait(self, rid: str) -> Record:
        """The response once it has ended."""
        if live := self._live.get(rid):
            await asyncio.shield(live.task)
        return self._record_by_id(rid)[1]

    def follow(self, who: Member, rid: str) -> AsyncIterator[tuple[str, str]]:
        """Its output as it arrives, or whole if it has ended."""
        r = self.response(who, rid)
        if live := self._live.get(rid):
            return live.feed.follow()

        async def replay() -> AsyncIterator[tuple[str, str]]:
            for stream in STREAMS:
                if text := getattr(r, stream):
                    yield stream, text
        return replay()

    async def cancel(self, who: Member, rid: str) -> Record:
        """Stop it: the signal now, a kill after the harness's grace; nothing if it has ended."""
        self.response(who, rid)
        if live := self._live.get(rid):
            live.stop_asked = True
            self._trace(self._session_by_id(live.record.session), "cancel", rid, {})
            if live.execution:
                live.execution.stop(live.config.stop_timeout_s)
            elif live.task:
                live.task.cancel()
            await asyncio.shield(live.task)
        return self._record_by_id(rid)[1]

    async def interrupt(self, who: Member, sid: str, text: str) -> Record:
        """Steer the session's running turn: the text in $HI_DIR/interrupt, then the harness's signal."""
        s = self.session(who, sid)
        live = next((l for l in self._live.values() if l.record.session == sid), None)
        if live is None or not isinstance(live.execution, ContainerExecution) or not live.execution.container:
            raise Conflict(f"session {sid} is not running a response")
        (self._paths(s)[1] / "interrupt").write_text(text)
        self._trace(s, "interrupt", live.record.id, {"input": text})
        if not await signal(live.execution.container, live.config.interrupt):
            raise Conflict("the response ended before the interrupt reached it")
        return live.record

    # the session's files
    async def archive(self, who: Member, sid: str) -> bytes:
        """The workspace, as a gzipped tar."""
        s = self.session(who, sid)
        workspace = self._paths(s)[0]
        if not s.stored or not workspace.is_dir():
            raise NotFound(f"session {sid} kept no workspace")

        def pack() -> bytes:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                tar.add(workspace, arcname=".")
            return buf.getvalue()
        return await asyncio.to_thread(pack)

    async def delete(self, who: Member, sid: str) -> None:
        s = self.session(who, sid)
        if any(live.record.session == sid for live in self._live.values()):
            raise Conflict(f"session {sid} is running a response")
        await asyncio.to_thread(shutil.rmtree, self._dir(s), True)
        for rid in s.responses:
            self._index.delete(rid)
        self._index.delete(sid)

    # the server's life
    async def recover(self) -> None:
        """Close what a restart cut off, and remove what its runs left behind."""
        await sweep(self.runtimes.owner)
        for p in self.store.sessions_root.glob("*/*/*/sess_*/responses/resp_*.json"):
            store = JsonStore(p.parent, lambda d: Record(**d))
            r = store.get(p.stem)
            if r and r.status == "in_progress":
                store.put(r.id, replace(r, status="failed", error="the server restarted while it ran", ended=time.time()))

    async def close(self) -> None:
        for live in list(self._live.values()):
            if live.execution:
                live.execution.kill()
            elif live.task:
                live.task.cancel()
        await asyncio.gather(*(l.task for l in self._live.values() if l.task), return_exceptions=True)
