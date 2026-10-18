import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness_interface.app import build, create_app            # noqa: E402
from harness_interface.models import Harness                    # noqa: E402
from harness_interface.config import Settings                  # noqa: E402

def packed(folder: Path) -> Harness:
    """A harness folder as the resource its PUT takes: harness.json plus every other file as a script."""
    import json
    spec = json.loads((folder / "harness.json").read_text())
    spec["scripts"] = {p.name: p.read_text() for p in sorted(folder.iterdir()) if p.is_file() and p.name != "harness.json"}
    return Harness(**spec)


ECHO = packed(Path(__file__).parent / "echo")


@pytest.fixture
def container(tmp_path):
    return build(Settings(data_dir=tmp_path / "data", runtime="local"))


@pytest.fixture
def client(container):
    with TestClient(create_app(container)) as c:     # one event loop for the test, so background runs live on
        yield c


@pytest.fixture
def echo(client):
    """The echo harness and the provider it names, registered."""
    assert client.put("/providers/none", json={"name": "none", "url": "https://example.invalid/v1", "key": "k"}).status_code == 200
    r = client.put("/harnesses/echo", json=ECHO.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    return ECHO


@pytest.fixture
def live(container, echo):
    """The app on a real server, for what a test client cannot show: streams that are still
    running, clients that leave, requests at the same time."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(container), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as c:
        yield c
    server.should_exit = True
    thread.join(10)
