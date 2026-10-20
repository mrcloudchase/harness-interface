"""The live suite's secret audit blames only what its own runs started: a container that has just
stopped (Docker reports its pid as 0) does not make every process on the host one of the runs', and
another server's containers on the machine (a file-mode run holds its key) are not its own."""
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
    assert live.live_audit(b"sk-key", "gateway", {"MACHINES_OWN_KEY"}, owner="0123456789ab") == []


def test_the_audit_inspects_its_own_servers_containers_and_no_one_elses(monkeypatch, tmp_path):
    live = load()
    mine, theirs = live.owner_of(tmp_path / "mine"), live.owner_of(tmp_path / "theirs")
    containers = {"hi-run-000000000001": mine, "hi-door-000000000001": mine, "hi-run-000000000002": theirs}
    asked = []

    def docker_out(*args):
        if args[0] == "ps":
            asked.append(args)
            labels = [a.removeprefix("label=") for a in args if a.startswith("label=")]
            return "\n".join(n for n, o in containers.items() if all(lb == f"hi.owner={o}" for lb in labels)).encode()
        name = args[-1] if args[0] == "inspect" else args[args.index("-u") + 2]
        return b"sk-key" if containers[name] == theirs else b"123" if args[1] == "-f" else b"{}"
    monkeypatch.setattr(live, "docker_out", docker_out)
    monkeypatch.setattr(live, "holders", lambda key: {})
    assert live.live_audit(b"sk-key", "file", set(), owner=mine) == [] and asked
    assert live.live_audit(b"sk-key", "file", set(), owner=theirs)      # the same audit finds what theirs holds
