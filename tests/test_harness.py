"""Layer 3: the harness contract gives every harness exactly what it promises and reads back exactly
what it reports; the key reaches only the environment; every shipped harness loads, prepares, and
puts the artifacts dropped in its folder in place, never outside its home;
a turn runs end to end on a runtime, and can be cancelled at any point."""
import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from harness_interface.errors import Invalid
from harness_interface.execution import NeverStarted, Outcome
from harness_interface.harness import Harness, Provider, Request, Turn, collect, prepare
from harness_interface.runtimes import LocalRuntime
from harness_interface.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
ECHO_DIR = Path(__file__).parent / "echo"
PROVIDER = Provider("none", "https://example.invalid/v1", "sk-test-key")
CONTRACT = {"HI_TASK", "HI_MODEL", "HI_SESSION_ID", "HI_REQUEST", "HI_OUTPUT", "HI_WORKSPACE",
            "HI_HARNESS_DIR", "HI_PROVIDER_URL", "HI_PROVIDER_KEY"}


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.init()
    return w


def echo(**changes) -> Harness:
    data = Harness.from_folder(ECHO_DIR).to_dict()
    data.update(changes)
    return Harness.from_dict(data)


# ── the contract ───────────────────────────────────────────────────────────────────────────────
def test_a_harness_is_given_exactly_the_contract(ws, tmp_path):
    h = echo(files={"AGENTS.md": "{instructions}", "cfg.json": '{"a": {"b": 1}}'},
             run={"argv": ["bash", "{harness_dir}/run.sh", "{model}"], "env": {"WHERE": "{provider_url} as {model}"}})
    req = Request("say hi", instructions="be brief", model="m1", files={"in/a.txt": "A"}, session_id="s0",
                  metadata={"who": "test"})
    spec = prepare(h, PROVIDER, req, ws, tmp_path / "scripts")
    assert {k for k in spec.env if k.startswith("HI_")} == CONTRACT
    assert spec.env["HI_TASK"] == "say hi" and spec.env["HI_MODEL"] == "m1" and spec.env["HI_SESSION_ID"] == "s0"
    assert spec.env["HI_WORKSPACE"] == str(ws.path) and spec.env["HI_HARNESS_DIR"] == str(tmp_path / "scripts")
    assert spec.env["WHERE"] == "https://example.invalid/v1 as m1"
    assert spec.command == ("bash", f"{tmp_path / 'scripts'}/run.sh", "m1") and spec.workspace == ws.path
    request = json.loads(spec.input)
    assert request == json.loads((ws.path / ".hi/request.json").read_text())
    assert request == {"task": "say hi", "instructions": "be brief", "model": "m1", "session_id": "s0",
                       "files": ["in/a.txt"], "metadata": {"who": "test"}}
    assert (ws.path / "AGENTS.md").read_text() == "be brief" and (ws.path / "in/a.txt").read_text() == "A"
    assert json.loads((ws.path / "cfg.json").read_text()) == {"a": {"b": 1}}       # braces that aren't placeholders pass


def test_the_key_reaches_only_the_environment(ws, tmp_path):
    spec = prepare(echo(), PROVIDER, Request("x"), ws, tmp_path)
    assert spec.env["HI_PROVIDER_KEY"] == "sk-test-key"
    assert not any("sk-test-key" in a for a in spec.command) and b"sk-test-key" not in spec.input
    assert "sk-test-key" not in repr(PROVIDER)
    assert not any("sk-test-key" in p.read_text(errors="ignore") for p in ws.path.rglob("*") if p.is_file() and ".git" not in p.parts)


def test_refusals_happen_before_anything_runs(ws, tmp_path):
    with pytest.raises(Invalid, match="unknown placeholder"):
        prepare(echo(files={"x": "{nope}"}), PROVIDER, Request("x"), ws, tmp_path)
    with pytest.raises(Invalid, match="escapes"):
        prepare(echo(), PROVIDER, Request("x", files={"../out.txt": "x"}), ws, tmp_path)
    with pytest.raises(Invalid):
        Request("   ")


def test_only_this_turns_report_counts(ws, tmp_path):
    (ws.path / ".hi/output.json").write_text('{"answer": "from an earlier turn"}')
    prepare(echo(), PROVIDER, Request("x"), ws, tmp_path)
    assert collect(Outcome.exited(0), ws).answer == ""


@pytest.mark.parametrize("outcome,reported,status", [
    (Outcome.exited(0), {}, "ok"),
    (Outcome.exited(2), {}, "fail"),
    (Outcome.exited(0), {"status": "fail"}, "fail"),
    (Outcome.exited(1), {"status": "ok"}, "ok"),
    (Outcome.exited(0), {"status": "weird"}, "ok"),
    (Outcome.timed_out(), {"status": "ok"}, "timeout"),
    (Outcome.cancelled(), {"status": "ok"}, "cancelled"),
])
def test_how_it_ended_decides_before_what_it_reported(ws, outcome, reported, status):
    (ws.path / ".hi/output.json").write_text(json.dumps(reported))
    assert collect(outcome, ws).status == status


def test_what_a_harness_reports_is_read_strictly(ws):
    (ws.path / ".hi/output.json").write_text(json.dumps(
        {"answer": "hi", "session_id": 42, "usage": {"in": 1}, "cost_usd": 0.5}))
    r = collect(Outcome.exited(0), ws)
    assert (r.answer, r.session_id, r.usage, r.cost_usd, r.exit_code) == ("hi", "42", {"in": 1}, 0.5, 0)
    (ws.path / ".hi/output.json").write_text(json.dumps({"answer": "  ", "usage": "lots", "cost_usd": True}))
    r = collect(Outcome.exited(0), ws)
    assert (r.answer, r.usage, r.cost_usd) == ("", None, None)
    (ws.path / ".hi/output.json").write_text("not json")
    assert collect(Outcome.exited(0), ws).status == "ok"
    assert collect(Outcome.failed("no image"), ws) .error == "no image"


def test_a_harness_definition_is_checked():
    with pytest.raises(Invalid, match="plain filename"):
        echo(scripts={"../x": "y"})
    with pytest.raises(Invalid, match="unknown harness fields"):
        Harness.from_dict({"name": "x", "provider": "p", "colour": "red"})
    with pytest.raises(Invalid):
        Harness.from_dict({"name": "x", "provider": "p", "run": {"timeout_s": 0}})
    with pytest.raises(Invalid, match="no harness.json"):
        Harness.from_folder(ROOT)


def test_every_shipped_harness_loads_and_prepares(tmp_path):
    folders = sorted(p for p in (ROOT / "harnesses").iterdir() if (p / "harness.json").is_file())
    assert len(folders) == 23
    for folder in folders:
        h = Harness.from_folder(folder)
        ws = Workspace(tmp_path / h.name)
        ws.init()
        spec = prepare(h, PROVIDER, Request("x", instructions="be brief"), ws, folder)
        assert spec.command and {k for k in spec.env if k.startswith("HI_")} == CONTRACT, h.name


def artifacts_block(run_sh: Path) -> str:
    lines = run_sh.read_text().split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("# Artifacts:"))
    return "\n".join(lines[start:lines.index("fi", start) + 1])


def place(block: str, folder: Path, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f"set -euo pipefail\n{block}"], capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], "HOME": str(home), "HI_HARNESS_DIR": str(folder)})


def test_every_shipped_harness_puts_dropped_artifacts_in_place(tmp_path):
    blocks = {artifacts_block(p) for p in (ROOT / "harnesses").glob("*/run.sh")}
    assert len(blocks) == 1                                            # the same few lines in every harness
    block = blocks.pop()
    shipped = sorted(p.parent for p in (ROOT / "harnesses").glob("*/harness.json"))
    assert all((f / "artifacts").is_file() for f in shipped)         # every folder ships one, bringing nothing
    for f in shipped:
        assert place(block, f, tmp_path / "shipped").returncode == 0, f.name
    assert not (tmp_path / "shipped").exists()
    folder, home = tmp_path / "harness", tmp_path / "home"
    folder.mkdir()
    assert place(block, folder, home).returncode == 0 and not home.exists()     # no artifacts file: nothing to do
    (folder / "review.md").write_text("# review")
    (folder / "settings.json").write_text("{}")
    (folder / "artifacts").write_text("# file  where under $HOME\n\nreview.md .claude/skills/review/SKILL.md\n"
                                      "  settings.json   .claude/settings.json")   # no final newline
    assert place(block, folder, home).returncode == 0
    assert (home / ".claude/skills/review/SKILL.md").read_text() == "# review"
    assert (home / ".claude/settings.json").read_text() == "{}"
    for line in ("review.md ../out.md", "review.md /tmp/out.md", "review.md a/../../out.md", "review.md",
                 "../review.md x.md", "missing.md x.md"):
        (folder / "artifacts").write_text(line + "\n")
        assert place(block, folder, home).returncode != 0, line
    assert not (tmp_path / "out.md").exists()


# ── a turn ─────────────────────────────────────────────────────────────────────────────────────
async def turn_of(harness, request, tmp_path, runtime=None):
    harness.write_scripts(tmp_path / "scripts")
    turn = await Turn.start(runtime or LocalRuntime(), harness, PROVIDER, request, tmp_path / "ws", tmp_path / "scripts")
    out = b"".join([e.data async for e in turn.events() if e.stream == "stdout"])
    return out, await turn.result()


def test_a_turn_end_to_end(tmp_path):
    out, r = asyncio.run(turn_of(echo(), Request("say hi"), tmp_path))
    assert b'"text":"echo: say hi"' in out
    assert (r.status, r.exit_code, r.answer, r.session_id) == ("ok", 0, "echo: say hi", "echo-1")
    assert r.files == ("hello.txt",) and r.deleted == () and r.base and r.commit and r.base != r.commit
    assert Workspace(tmp_path / "ws").read("hello.txt", r.commit) == b"hello from echo\n"


def test_a_second_turn_continues_in_the_same_workspace(tmp_path):
    asyncio.run(turn_of(echo(), Request("one"), tmp_path))
    out, r = asyncio.run(turn_of(echo(), Request("two", session_id="echo-1"), tmp_path))
    assert b'"session_id_in":"echo-1"' in out and r.files == ()      # hello.txt is unchanged since the first


def test_failure_timeout_and_never_started(tmp_path):
    _, r = asyncio.run(turn_of(echo(scripts={"run.sh": "exit 3\n"}), Request("x"), tmp_path))
    assert (r.status, r.exit_code) == ("fail", 3)
    _, r = asyncio.run(turn_of(echo(scripts={"run.sh": "sleep 30\n"}, run={"timeout_s": 1}), Request("x"), tmp_path))
    assert r.status == "timeout"

    class Broken:
        async def start(self, spec):
            return NeverStarted("sandbox 'default' failed to build")
    _, r = asyncio.run(turn_of(echo(), Request("x"), tmp_path, runtime=Broken()))
    assert (r.status, r.error) == ("fail", "sandbox 'default' failed to build")


def test_cancel_while_running_and_while_setting_up(tmp_path):
    slow = echo(scripts={"run.sh": "echo start; sleep 30\n"})
    slow.write_scripts(tmp_path / "scripts")

    async def running():
        turn = await Turn.start(LocalRuntime(), slow, PROVIDER, Request("x"), tmp_path / "a", tmp_path / "scripts")
        async for _ in turn.events():
            await asyncio.to_thread(turn.cancel)     # from another thread
        return await turn.result()
    assert asyncio.run(running()).status == "cancelled"

    class SlowSetup:
        async def start(self, spec):
            await asyncio.sleep(30)

    async def setting_up():
        turn = await Turn.start(SlowSetup(), echo(), PROVIDER, Request("x"), tmp_path / "b", ECHO_DIR)
        turn.cancel()
        assert [e async for e in turn.events()] == []
        return await turn.result()
    r = asyncio.run(setting_up())
    assert (r.status, r.exit_code) == ("cancelled", None) and not (tmp_path / "b" / "hello.txt").exists()
