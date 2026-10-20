"""The live suite's secret audit blames only what the runs started: a container that has just stopped
(Docker reports its pid as 0) does not make every process on the host one of the runs'."""
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live.py"


def load():
    spec = importlib.util.spec_from_file_location("live_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module                  # its dataclasses look their module up
    spec.loader.exec_module(module)
    return module


def test_a_stopped_container_does_not_make_the_hosts_own_processes_suspects(monkeypatch):
    live = load()

    def docker_out(*args):
        if args[:2] == ("ps", "--filter"):
            return b"hi-door-0123456789ab\n"
        if args[:3] == ("inspect", "-f", "{{.State.Pid}}"):
            return b"0\n"
        return b"{}"
    monkeypatch.setattr(live, "docker_out", docker_out)
    monkeypatch.setattr(live, "holders", lambda key: {1: (False, {"MACHINES_OWN_KEY"})})
    assert live.live_audit(b"sk-key", "gateway", {"MACHINES_OWN_KEY"}, docker=True) == []
