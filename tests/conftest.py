"""Shared fixtures for the front end and the CLI: a server on the local runtime in a throwaway data
directory, an echo harness registered on it, and the same app on a real port."""
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from harness_interface.api.app import build, create_app
from harness_interface.api.config import Settings
from harness_interface.harness import Harness

ECHO = Harness.from_folder(Path(__file__).parent / "echo")


@pytest.fixture
def service(tmp_path):
    return build(Settings(data_dir=tmp_path / "data", runtime="local"))


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as c:      # one event loop for the test, so background turns live on
        yield c


@pytest.fixture
def echo(client):
    """The echo harness, and the provider it names, registered."""
    assert client.put("/providers/none", json={"name": "none", "url": "https://example.invalid/v1", "key": "k"}).status_code == 200
    assert client.put("/harnesses/echo", json=ECHO.to_dict()).status_code == 200
    return ECHO


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live(service, echo):
    """The app on a real server, for what a test client can't show: streams still running, clients
    that leave, requests at the same time."""
    server = uvicorn.Server(uvicorn.Config(create_app(service), host="127.0.0.1", port=free_port(), log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    with httpx.Client(base_url=f"http://127.0.0.1:{server.config.port}", timeout=30) as c:
        yield c
    server.should_exit = True
    thread.join(10)
