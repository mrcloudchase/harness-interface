import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hi.app import build, create_app            # noqa: E402
from hi.cli import packed                       # noqa: E402
from hi.config import Settings                  # noqa: E402

ECHO = packed(ROOT / "harnesses" / "echo")


@pytest.fixture
def container(tmp_path):
    return build(Settings(data_dir=tmp_path / "data", runtime="local"))


@pytest.fixture
def client(container):
    return TestClient(create_app(container))


@pytest.fixture
def echo(client):
    """The echo harness and the provider it names, registered."""
    assert client.put("/providers/none", json={"name": "none", "url": "https://example.invalid/v1", "key": "k"}).status_code == 200
    r = client.put("/harnesses/echo", json=ECHO.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    return ECHO
