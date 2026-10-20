"""The plumbing every adapter shares (hi_adapter.py, run inside the sandbox): its output is always a
whole JSON file and keeps any key it is given; line 1 is the task and resume, the model comes from
$HI_MODEL; JSON-RPC replies reach their callbacks and the CLI's requests are answered; and the loop
tells a stop from a failure, takes extra event sources, and lets an adapter close its CLI first."""
import io
import json
import os
import subprocess
import sys
import textwrap

import pytest

from harness_interface.harness import hi_adapter
from harness_interface.harness.folder import CANONICAL_ADAPTER


def test_output_is_whole_and_keeps_every_key(tmp_path):
    out = hi_adapter.Output(str(tmp_path / "o.json"))
    out.write(resume="abc")
    assert json.loads((tmp_path / "o.json").read_text())["status"] == "running"
    out.write(status="ok", answer="hi", turns=3, usage={"input_tokens": 1, "thinking_ms": 9})
    data = json.loads((tmp_path / "o.json").read_text())
    assert (data["resume"], data["turns"], data["usage"]["thinking_ms"]) == ("abc", 3, 9)
    assert os.listdir(tmp_path) == ["o.json"]
    with pytest.raises(AssertionError):
        out.write(status="interrupted")


def test_line_one_is_task_and_resume_and_the_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("HI_MODEL", "deepseek-chat")
    stdin = io.StringIO('{"task": "t", "resume": null}\n"a steer"\n')
    assert hi_adapter.read_request(stdin) == {"task": "t", "resume": None, "model": "deepseek-chat"}
    assert stdin.readline() == '"a steer"\n'                  # the steers are left for the loop
    monkeypatch.delenv("HI_MODEL")
    assert hi_adapter.read_request(io.StringIO('{"task": "t"}\n'))["model"] == ""
    with pytest.raises(SystemExit):
        hi_adapter.read_request(io.StringIO(""))


def test_loopback_is_never_proxied(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "hi-door")
    env = hi_adapter.child_env()
    assert set(env["NO_PROXY"].split(",")) == {"127.0.0.1", "localhost", "hi-door"} and env["no_proxy"] == env["NO_PROXY"]


class Proc:
    def __init__(self):
        self.stdin = io.StringIO()

    def sent(self):
        return [json.loads(line) for line in self.stdin.getvalue().splitlines()]


def test_json_rpc_replies_reach_their_callbacks_and_requests_are_answered():
    proc, got = Proc(), []
    rpc = hi_adapter.JsonRpc(proc, answer=lambda method, params: {"decision": "accept", "for": method})
    first = rpc.call("initialize", {"v": 1}, lambda result, error: got.append(("init", result, error)))
    second = rpc.call("turn/start", {}, lambda result, error: got.append(("turn", result, error)))
    rpc.notify("initialized")
    assert rpc.dispatch({"jsonrpc": "2.0", "id": second, "error": {"message": "busy"}}) is False
    assert rpc.dispatch({"jsonrpc": "2.0", "id": first, "result": {"ok": True}}) is False
    assert rpc.dispatch({"jsonrpc": "2.0", "id": 7, "method": "item/requestApproval", "params": {}}) is False
    assert rpc.dispatch({"jsonrpc": "2.0", "method": "turn/completed", "params": {}}) is True
    assert got == [("turn", None, {"message": "busy"}), ("init", {"ok": True}, None)]
    assert proc.sent() == [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"v": 1}},
        {"jsonrpc": "2.0", "id": 2, "method": "turn/start", "params": {}},
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "id": 7, "result": {"decision": "accept", "for": "item/requestApproval"}}]


# A CLI that prints what it reads until its stdin ends, then a last line; and an adapter for it that
# takes a second event source, finishes `stopped` only when asked to stop, and has a last word.
ADAPTER = textwrap.dedent("""
    import os, sys, time
    sys.path.insert(0, os.environ["ADAPTER_DIR"])
    from hi_adapter import Adapter

    class Echo(Adapter):
        stop_grace_s = 5.0
        def start(self, request):
            self.cli = self.spawn([sys.executable, "-u", "-c",
                                   "import sys\\nfor l in sys.stdin: print('cli', l.strip())\\nprint('cli closed')"])
            self.pump(["extra one", "extra two"], "extra")
            self.cli.stdin.write(request["task"] + "\\n"); self.cli.stdin.flush()
        def on_line(self, source, line):
            self.emit({"source": source, "line": line})
            if line == "cli closed":
                self.finish("stopped" if self.stopping else "fail")
        def steer(self, text):
            self.cli.stdin.write(text + "\\n"); self.cli.stdin.flush()
        def stop(self):
            self.cli.stdin.close()
        def on_finish(self):
            self.emit({"on_finish": True})

    Echo().main()
""")


def test_the_loop_tells_a_stop_from_a_failure_and_takes_more_sources(tmp_path):
    env = {"PATH": os.environ["PATH"], "HI_OUTPUT": str(tmp_path / "out.json"), "HI_WORKSPACE": str(tmp_path),
           "ADAPTER_DIR": str(CANONICAL_ADAPTER.parent)}
    done = subprocess.run([sys.executable, "-c", ADAPTER], input='{"task": "hello", "resume": "r1"}\n"steer one"\n',
                          capture_output=True, text=True, env=env, timeout=30)
    events = [json.loads(line) for line in done.stdout.splitlines()]
    lines = [e["line"] for e in events if "line" in e]
    assert "cli hello" in lines and "cli steer one" in lines and "cli closed" in lines
    assert {"extra one", "extra two"} <= set(lines)
    assert {"type": "hi.stop", "why": "eof"} in events                   # the end of stdin asked for the stop
    assert events[-1] == {"on_finish": True}                             # once, last, before the CLI is reaped
    out = json.loads((tmp_path / "out.json").read_text())
    assert (out["status"], out["resume"]) == ("stopped", "r1")
