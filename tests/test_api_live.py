"""Layer 6, against a real Docker daemon, with the template's stand-in: the server installs a harness it
is sent in the sandbox, and a session's response streams, is steered, stopped through tini and
continued in a fresh container, reaching its provider through the gateway with only a token; no key
is in anything served or kept, and nothing is left running. Run with `pytest -m docker`."""
import json
import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from harness_interface import Placement, Sessions
from harness_interface.api.app import create_app
from harness_interface.runtimes.docker import Images
from test_api import Stream, idle, settled_install
from test_docker_live import docker_ok, leftovers
from test_harness_live import CA
from test_store import folder_map
from standin import TEMPLATE
from upstream import Upstream

pytestmark = pytest.mark.docker
KEY = "sk-api-live-key-" + os.urandom(8).hex()


@pytest.fixture
def server(tmp_path):
    if not docker_ok():
        pytest.skip("no Docker daemon")
    bridge = subprocess.run(["docker", "network", "inspect", "bridge", "-f", "{{(index .IPAM.Config 0).Gateway}}"],
                            capture_output=True, text=True, check=True).stdout.strip()
    up = Upstream(tmp_path, ip=bridge, bind=bridge)
    bundle = tmp_path / "ca.pem"                     # this machine's re-signing CA, for the install, and the stand-in's
    bundle.write_text((CA.read_text() if CA else "") + up.ca.read_text())
    sessions = Sessions(tmp_path / "data", Placement(Images(tmp_path / "data" / "logs"), ca_file=bundle))
    with TestClient(create_app(sessions)) as c:
        yield c, up
    up.close()
    assert leftovers() == []


def test_a_sandboxed_session_streams_is_steered_stopped_and_continued(server, tmp_path):
    c, up = server
    url = up.url + "/anthropic"
    assert c.put("/providers/up", json={"url": url, "api": "anthropic-messages", "key": KEY}).status_code == 200
    body = folder_map(TEMPLATE)
    spec = json.loads(body["harness.json"])
    spec["provider"]["url"] = url
    body["harness.json"] = json.dumps(spec)
    assert c.put("/harnesses/template", json=body).json()["install"]["state"] == "installing"
    assert settled_install(c, "template")["install"]["state"] == "ready"

    with c.stream("POST", "/responses", json={"model": "template", "input": "count to 50", "stream": True}) as r:
        sid, stream, steered = r.headers["x-session-id"], Stream(r.iter_lines()), None
        for event, _ in stream:
            if event != "harness.stdout":
                continue
            if stream.count() == 1 and not steered:
                steered = c.post(f"/sessions/{sid}/interrupt", json={"input": "count to 60"}).json()["outcome"]
            elif stream.count() == 3:
                stopped = c.post(f"/sessions/{sid}/stop").json()
                break
    assert steered == "steered" and stopped["outcome"] == "stopped"
    first = stopped["session"]["responses"][0]
    assert (first["status"], first["harness"]["stop"]) == ("cancelled", "stopped") and first["harness"]["resume"]
    seen = [json.loads(d["line"]) for e, d in stream.seen if e == "harness.stdout"]
    assert {"type": "provider", "status": 200} in seen
    assert '{"type": "hi.stop", "why": "SIGINT"}' in first["harness"]["stdout"]          # through tini

    second = c.post("/responses", json={"model": "template", "input": "count to 5",
                                        "previous_response_id": first["id"]}).json()
    assert second["status"] == "completed" and second["output"][0]["content"][0]["text"] == "Counted to 5."
    resumed = next(json.loads(x) for x in second["harness"]["stdout"].splitlines() if '"session"' in x)
    assert resumed["resumed"] and resumed["count"] >= 3
    s = idle(c, sid)
    served = json.dumps(s) + c.get("/providers").text + c.get("/sessions").text
    assert KEY not in served and f"x-api-key: {KEY}" in up.requests[0].decode("latin-1")
    for p in (tmp_path / "data").rglob("*"):
        if p.is_file() and "providers" not in p.parts:
            assert KEY.encode() not in p.read_bytes(), p
