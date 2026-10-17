import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hi.app import build, create_app            # noqa: E402
from hi.config import Settings                   # noqa: E402
from hi.registry import load_spec                # noqa: E402


@pytest.fixture
def client(tmp_path):
    c = build(Settings(data_dir=tmp_path / "data"))
    return TestClient(create_app(c))


@pytest.fixture
def echo(client):
    spec = load_spec(ROOT / "harnesses" / "echo" / "harness.yaml")
    r = client.put(f"/harnesses/{spec.name}", json=spec.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    r = client.put("/route", json={"kind": "Route", "engine": "static", "default": "echo"})
    assert r.status_code == 200, r.text
    return spec
