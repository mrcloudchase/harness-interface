import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hi.app import build, create_app            # noqa: E402
from hi.models import Harness                    # noqa: E402
from hi.config import Settings                  # noqa: E402

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
    return TestClient(create_app(container))


@pytest.fixture
def echo(client):
    """The echo harness and the provider it names, registered."""
    assert client.put("/providers/none", json={"name": "none", "url": "https://example.invalid/v1", "key": "k"}).status_code == 200
    r = client.put("/harnesses/echo", json=ECHO.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    return ECHO
