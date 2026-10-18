"""Layer 8: `hi`, the command line, against a real server. Every command is an API call."""
import json
import socket
from pathlib import Path

import pytest

from hi_cli import daemon, main
from hi_cli.harness import BUILTIN, builtin, pack

ECHO = Path(__file__).parent / "echo"


@pytest.fixture
def hi(live, tmp_path, monkeypatch, capsys):
    """Run `hi` against the live server; returns (exit code, stdout, stderr)."""
    monkeypatch.setenv("HI_URL", str(live.base_url))
    monkeypatch.setattr(main, "LAST", tmp_path / "last-response")

    def call(*argv):
        code = main.main(list(argv))
        out, err = capsys.readouterr()
        return code, out, err
    return call



def test_pack_and_the_shipped_harnesses():
    spec = pack(ECHO)
    assert spec["name"] == "echo" and set(spec["scripts"]) == {"run.sh"}
    shipped = builtin([])
    assert len(shipped) == 23 and BUILTIN.name == "harnesses"
    assert [p.name for p in builtin(["claude-code"])] == ["claude-code"]
    with pytest.raises(ValueError, match="no built-in harness nope"):
        builtin(["nope"])


def test_add_run_continue_and_read(hi, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    assert hi("provider", "add", "none", "--url", "https://example.invalid/v1", "--key-env", "TEST_KEY")[0] == 0
    code, out, _ = hi("provider", "ls")
    assert code == 0 and "none" in out and "k" not in out.split()          # the key never comes back
    assert hi("harness", "add", str(ECHO))[0] == 0
    assert "echo" in hi("harness", "ls")[1]

    code, out, err = hi("run", "echo", "say hi", "-i", "be brief")
    assert code == 0 and out == "echo: say hi\n"                           # stdout is the answer alone
    assert "completed" in err and '"type":"text"' in err                    # the stream and the summary go to stderr
    first = json.loads(hi("ls", "--json")[1])[0]["id"]

    code, out, _ = hi("run", "echo", "again", "-c", "--json")              # -c continues the last response
    second = json.loads(out)
    assert code == 0 and second["previous_response_id"] == first and second["harness"]["session_id"] == "echo-1"

    assert json.loads(hi("show", first)[1])["status"] == "completed"
    assert '"type":"text"' in hi("output", first)[1]
    assert hi("files", first, "hello.txt")[1] == "hello from echo\n"
    assert "hello.txt" in hi("files", first)[1].split()                      # no path: the list
    assert "+hello from echo" in hi("diff", first)[1]
    assert hi("cancel", first)[0] == 1                                     # already over
    assert hi("harness", "rm", "echo")[0] == 0 and hi("harness", "rm", "echo")[0] == 1


def test_a_failed_run_fails_the_command(hi, tmp_path):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "harness.json").write_text(json.dumps({"name": "broken", "provider": "none"}))
    (folder / "run.sh").write_text("exit 3\n")
    hi("harness", "add", str(folder))
    code, out, err = hi("run", "broken", "x")
    assert code == 1 and out == "" and "failed" in err and "exit 3" in err


def test_no_server_says_how_to_start_one(monkeypatch, capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert main.main(["--url", f"http://127.0.0.1:{port}", "harness", "ls"]) == 1
    assert "hi server start" in capsys.readouterr().err


def test_server_start_status_stop(tmp_path, monkeypatch, capsys):
    """A real background server, on the local runtime, in a throwaway home."""
    monkeypatch.setattr(daemon, "HOME", tmp_path)
    monkeypatch.setattr(daemon, "PID", tmp_path / "server.pid")
    monkeypatch.setattr(daemon, "LOG", tmp_path / "server.log")
    monkeypatch.setenv("HI_RUNTIME", "local")
    monkeypatch.setenv("HI_DATA_DIR", str(tmp_path / "data"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = ["--url", f"http://127.0.0.1:{port}"]
    try:
        assert main.main([*url, "server", "start"]) == 0
        assert main.main([*url, "server", "status"]) == 0
        assert main.main([*url, "sandbox", "ls"]) == 0 and "default" in capsys.readouterr().out
        assert (tmp_path / "data" / "providers").is_dir()                  # the server used the data dir it was given
    finally:
        assert main.main([*url, "server", "stop"]) == 0
    assert main.main([*url, "server", "status"]) == 1
