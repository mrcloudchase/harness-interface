"""Layer 3: the contract. A harness gets line 1 and exactly its environment; its config artifacts are
re-applied every response, its `files` rendered and deleted when empty, its work artifacts seeded
once, the request's files written byte for byte; and what it gives back is its own status (never the
exit code), every key it wrote, its work's changes and the artifacts it reports. Run with the
template's stand-in on this machine."""
import asyncio
import json
import os

import pytest

from harness_interface.errors import Invalid
from harness_interface.execution import Outcome
from harness_interface.harness.contract import OUTPUT, Request, collect, prepare, session_token
from harness_interface.harness.folder import HarnessFolder
from harness_interface.runtimes.local import LocalRuntime
from harness_interface.workspace import Workspace
from standin import TEMPLATE, events, tools, variant

PATH = os.environ["PATH"]


@pytest.fixture
def folder():
    return HarnessFolder.load(TEMPLATE)


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "session" / "workspace")


@pytest.fixture
def kit(tmp_path):
    return {"tools": tools(tmp_path / "tools"), "path": PATH}


def ready(folder, ws, request, kit, tmp_path, n=1, **kw):
    return prepare(folder, ws, request, rundir=tmp_path / f"run-{n}", **kit, **kw)


async def respond(folder, ws, request, kit, tmp_path, n=1, *, new_session=False, until=None, then=None):
    """One response, run to its end on this machine: its events, its Result. `then(execution)` runs
    once an event matches `until`."""
    prepared = ready(folder, ws, request, kit, tmp_path, n, new_session=new_session)
    execution = await LocalRuntime().start(prepared.spec)
    out = b""
    async for event in execution.events():
        if event.stream == "stdout":
            out += event.data
            if until and then and any(until(e) for e in events(out)):
                await then(execution)
                then = None
    outcome = await execution.wait()
    return events(out), collect(folder, ws, prepared, outcome=outcome)


def test_line_one_is_the_task_and_resume_and_input_stays_open(folder, ws, kit, tmp_path):
    spec = ready(folder, ws, Request("count to 3", resume="abc", instructions="be brief", model="m"), kit, tmp_path).spec
    assert spec.input == b'{"task":"count to 3","resume":"abc"}\n' and spec.interactive
    assert spec.command == ("bash", str(TEMPLATE / "run.sh")) and spec.workspace == ws.path
    assert ready(folder, ws, Request("t"), kit, tmp_path).spec.input == b'{"task":"t","resume":null}\n'


def test_the_environment_is_the_contracts_and_nothing_else(folder, ws, kit, tmp_path):
    rundir = tmp_path / "run-1"
    spec = ready(folder, ws, Request("t", model="deepseek-chat"), kit, tmp_path).spec
    assert dict(spec.env) == {"HI_WORKSPACE": str(ws.path), "HOME": str(ws.path / ".home"),
                              "HI_HARNESS_DIR": str(TEMPLATE), "HI_OUTPUT": str(rundir / OUTPUT),
                              "HI_MODEL": "deepseek-chat", "PATH": f"{kit['tools']}/bin:{PATH}"}
    spec = ready(folder, ws, Request("t"), kit, tmp_path, provider_url="http://hi-provider:8080/anthropic",
                 provider_api="anthropic-messages", key_file="/run/hi/key").spec
    assert {k: spec.env[k] for k in ("HI_PROVIDER_URL", "HI_PROVIDER_API", "HI_PROVIDER_KEY_FILE", "HI_MODEL")} == \
        {"HI_PROVIDER_URL": "http://hi-provider:8080/anthropic", "HI_PROVIDER_API": "anthropic-messages",
         "HI_PROVIDER_KEY_FILE": "/run/hi/key", "HI_MODEL": ""}
    assert len(spec.env) == 9
    assert not rundir.is_relative_to(ws.path)


def test_a_one_shot_reports_its_own_status_answer_and_every_key(folder, ws, kit, tmp_path):
    seen, result = asyncio.run(respond(folder, ws, Request("count to 3"), kit, tmp_path))
    assert (result.status, result.answer, result.outcome) == ("ok", "Counted to 3.", Outcome.exited(0))
    assert result.output["count"] == 3 and result.usage == {"input_tokens": 3, "output_tokens": 3}
    assert result.resume == next(e["id"] for e in seen if e["type"] == "session")
    assert result.changes == {"count.txt": b"1\n2\n3\n"} and result.base != result.commit


def test_instructions_reach_the_harness_through_files_and_an_empty_render_deletes_them(folder, ws, kit, tmp_path):
    target = ws.path / ".home/.standin/AGENTS.md"
    seen, _ = asyncio.run(respond(folder, ws, Request("count to 1", instructions="Say PAPAYA."), kit, tmp_path))
    assert next(e for e in seen if e["type"] == "loaded")["instructions"] == "Say PAPAYA."
    seen, result = asyncio.run(respond(folder, ws, Request("count to 2"), kit, tmp_path, 2))
    assert next(e for e in seen if e["type"] == "loaded")["instructions"] is None and not target.exists()
    assert result.changes == {"count.txt": b"1\n1\n2\n"}                 # .home is never the work


def test_home_is_reapplied_every_response_and_the_harness_state_kept(folder, ws, kit, tmp_path):
    _, first = asyncio.run(respond(folder, ws, Request("count to 1"), kit, tmp_path))
    config = ws.path / ".home/.standin/config.json"
    config.write_text('{"note": "changed by the harness"}')
    seen, _ = asyncio.run(respond(folder, ws, Request("count to 2", resume=first.resume), kit, tmp_path, 2))
    loaded = next(e for e in seen if e["type"] == "loaded")
    assert loaded["config"] == json.loads((TEMPLATE / "home/.standin/config.json").read_text())
    assert loaded["skills"] == ["count"]
    assert next(e for e in seen if e["type"] == "session")["count"] == 1   # its session state survived


def test_the_workspace_is_seeded_once_when_the_session_starts(folder, ws, kit, tmp_path):
    asyncio.run(respond(folder, ws, Request("count to 1"), kit, tmp_path, new_session=True))
    readme = ws.path / "README.md"
    assert readme.read_bytes() == (TEMPLATE / "workspace/README.md").read_bytes()
    readme.write_text("the session's own now\n")
    _, result = asyncio.run(respond(folder, ws, Request("count to 2"), kit, tmp_path, 2))
    assert readme.read_text() == "the session's own now\n" and "README.md" not in result.changes


def test_request_files_are_written_byte_for_byte_and_are_not_the_harness_work(folder, ws, kit, tmp_path):
    blob = bytes(range(256))
    request = Request("count to 1", files={"data/blob.bin": blob, "notes.md": "héllo"})
    _, result = asyncio.run(respond(folder, ws, request, kit, tmp_path))
    assert (ws.path / "data/blob.bin").read_bytes() == blob and (ws.path / "notes.md").read_text() == "héllo"
    assert ws.read("data/blob.bin", result.base) == blob and set(result.changes) == {"count.txt"}


@pytest.mark.parametrize("rel", [".home/.standin/config.json", "./.home/x", ".git/config", "a/__pycache__/x.pyc"])
def test_a_request_file_never_lands_in_an_internal_path(rel):
    with pytest.raises(Invalid):
        Request("t", files={rel: "x"})


def test_a_request_file_never_lands_outside(folder, ws, kit, tmp_path):
    for rel in ("../escape.txt", "/tmp/escape.txt"):
        with pytest.raises(Invalid):
            ready(folder, ws, Request("t", files={rel: "x"}), kit, tmp_path)
    assert not (ws.path.parent / "escape.txt").exists()


def test_a_home_that_is_a_link_is_refused_and_nothing_is_written_through_it(folder, ws, kit, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    ws.path.mkdir(parents=True)
    (ws.path / ".home").symlink_to(outside)
    with pytest.raises(Invalid):
        ready(folder, ws, Request("t", instructions="x"), kit, tmp_path)
    assert list(outside.iterdir()) == []


def test_reported_artifacts_come_back_when_they_change(folder, ws, kit, tmp_path):
    _, first = asyncio.run(respond(folder, ws, Request("count to 2"), kit, tmp_path))
    memory = f".standin/memory/{first.resume}.md"
    assert dict(first.home) == {memory: b"- count to 2\n"}
    _, second = asyncio.run(respond(folder, ws, Request("count to 3", resume=first.resume), kit, tmp_path, 2))
    assert dict(second.home) == {memory: b"- count to 2\n- count to 3\n"}
    (ws.path / ".home" / memory).unlink()
    (ws.path / ".home/.standin/memory/other.md").write_text("kept")
    prepared = ready(folder, ws, Request("t"), kit, tmp_path, 3)
    (ws.path / ".home/.standin/memory/other.md").unlink()
    result = collect(folder, ws, prepared, outcome=Outcome.exited(0))
    assert dict(result.home) == {".standin/memory/other.md": None}
    assert ".standin/sessions" not in str(dict(second.home))           # what it doesn't report stays home


def test_the_end_of_stdin_stops_the_harness_gracefully(folder, ws, kit, tmp_path):
    async def end_input(execution):
        await execution.end_input()
    seen, result = asyncio.run(respond(folder, ws, Request("count to 100"), kit, tmp_path,
                                       until=lambda e: e.get("type") == "count", then=end_input))
    assert {"type": "hi.stop", "why": "eof"} in seen and result.status == "stopped"
    assert result.output["count"] < 100 and result.resume


def write_output(prepared, data):
    prepared.output.write_text(data if isinstance(data, str) else json.dumps(data))


@pytest.mark.parametrize("written, stop, outcome, status", [
    ({"status": "ok"}, None, Outcome.exited(1), "ok"),              # never the exit code
    ({"status": "fail", "answer": "credit balance is too low"}, None, Outcome.exited(0), "fail"),
    ({"status": "stopped"}, "requested", Outcome.stopped(0), "stopped"),
    ({"status": "running", "resume": "r1"}, "requested", Outcome.killed(), "stopped"),
    ({"status": "running", "resume": "r1"}, None, Outcome.killed(), "fail"),
    ({"status": "running"}, "requested", Outcome.killed(), "fail"),
    ({"status": "running", "resume": "r1"}, "timeout", Outcome.killed(), "stopped"),
    (None, "requested", Outcome.killed(), "fail"),
    ("{half a write", None, Outcome.exited(0), "fail"),
    ({"status": "done"}, None, Outcome.exited(0), "fail"),
])
def test_the_status_is_the_harness_own_or_what_a_cut_off_means(folder, ws, kit, tmp_path, written, stop, outcome,
                                                                 status):
    prepared = ready(folder, ws, Request("t"), kit, tmp_path)
    if written is not None:
        write_output(prepared, written)
    assert collect(folder, ws, prepared, outcome=outcome, stop=stop).status == status


def test_every_key_comes_back_and_usage_is_as_reported(folder, ws, kit, tmp_path):
    prepared = ready(folder, ws, Request("t"), kit, tmp_path)
    usage = {"input_tokens": 5, "cache_read_tokens": 2, "inputTokens": 5, "reasoning_tokens": 1}
    write_output(prepared, {"status": "ok", "answer": "a", "usage": usage, "cost_usd": 0.25, "steers": 2,
                            "turns": [1, 2], "model_said": {"x": True}})
    result = collect(folder, ws, prepared, outcome=Outcome.exited(0), steers_sent=3)
    assert dict(result.usage) == usage and result.cost_usd == 0.25 and (result.steers, result.undelivered) == (2, 1)
    assert result.output["turns"] == [1, 2] and result.output["model_said"] == {"x": True}


def test_what_isnt_its_type_is_dropped_not_trusted(folder, ws, kit, tmp_path):
    prepared = ready(folder, ws, Request("t"), kit, tmp_path)
    write_output(prepared, {"status": "ok", "answer": 3, "resume": "", "usage": [1], "cost_usd": "free", "steers": True})
    result = collect(folder, ws, prepared, outcome=Outcome.exited(0))
    assert (result.answer, result.resume, dict(result.usage), result.cost_usd, result.steers) == ("", None, {}, None, 0)


def test_a_harness_that_never_started_says_why(folder, ws, kit, tmp_path):
    prepared = ready(folder, ws, Request("t"), kit, tmp_path)
    result = collect(folder, ws, prepared, outcome=Outcome.failed("could not start bash"))
    assert (result.status, result.answer) == ("fail", "could not start bash")


def test_a_stale_output_never_passes_for_this_one(folder, ws, kit, tmp_path):
    prepared = ready(folder, ws, Request("t"), kit, tmp_path)
    write_output(prepared, {"status": "ok", "answer": "the last response's"})
    prepared = ready(folder, ws, Request("t"), kit, tmp_path)
    assert collect(folder, ws, prepared, outcome=Outcome.killed()).status == "fail"


def test_a_folder_with_no_home_or_workspace_still_runs(ws, kit, tmp_path):
    import shutil
    folder = variant(tmp_path / "bare")
    shutil.rmtree(folder.path / "home")
    shutil.rmtree(folder.path / "workspace")
    folder = HarnessFolder.load(folder.path)
    _, result = asyncio.run(respond(folder, ws, Request("count to 1"), kit, tmp_path, new_session=True))
    assert result.status == "ok" and set(result.changes) == {"count.txt"}


def test_a_session_token_is_shaped_for_its_api_and_never_repeats():
    a, b = session_token("anthropic-messages"), session_token("anthropic-messages")
    assert a.startswith("sk-ant-api03-hi-") and a != b and len(a) > 40
    assert session_token("openai-chat").startswith("sk-hi-")
