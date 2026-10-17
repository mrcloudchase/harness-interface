"""Providers, sandboxes and harnesses over the API."""
from hi.registry import DEFAULT_SANDBOX


def test_provider_key_is_never_returned(client):
    r = client.put("/providers/deepseek", json={"name": "deepseek", "url": "https://api.deepseek.com/anthropic", "key": "sk-secret"})
    assert r.status_code == 200 and r.json() == {"name": "deepseek", "url": "https://api.deepseek.com/anthropic"}
    assert "sk-secret" not in client.get("/providers").text
    assert "sk-secret" not in client.get("/providers/deepseek").text
    assert client.put("/providers/other", json={"name": "deepseek", "url": "u", "key": "k"}).status_code == 400
    assert client.delete("/providers/deepseek").json() == {"deleted": True}
    assert client.get("/providers/deepseek").status_code == 404


def test_default_sandbox_is_built_in_and_reserved(client):
    names = [s["name"] for s in client.get("/sandboxes").json()]
    assert names == [DEFAULT_SANDBOX]
    d = client.get(f"/sandboxes/{DEFAULT_SANDBOX}").json()
    assert d["dockerfile"].startswith("#") and d["egress"] == []
    assert client.put(f"/sandboxes/{DEFAULT_SANDBOX}", json={"name": DEFAULT_SANDBOX, "dockerfile": "FROM x"}).status_code == 400
    assert client.delete(f"/sandboxes/{DEFAULT_SANDBOX}").status_code == 400
    r = client.put("/sandboxes/py", json={"name": "py", "dockerfile": "FROM python:3.12", "egress": ["pypi.org"]})
    assert r.status_code == 200 and r.json()["egress"] == ["pypi.org"]
    assert [s["name"] for s in client.get("/sandboxes").json()] == [DEFAULT_SANDBOX, "py"]
    assert client.delete("/sandboxes/py").json() == {"deleted": True}


def test_harness_scripts_land_on_disk(client, container, echo):
    d = container.resources.harness_dir("echo")
    assert (d / "run.sh").read_text() == echo.scripts["run.sh"]
    got = client.get("/harnesses/echo").json()
    assert got["provider"] == "none" and got["sandbox"] == DEFAULT_SANDBOX and set(got["scripts"]) == {"run.sh"}
    assert [h["name"] for h in client.get("/harnesses").json()] == ["echo"]
    bad = {**echo.model_dump(mode="json"), "scripts": {"../x": "y"}}
    assert client.put("/harnesses/echo", json=bad).status_code == 400
    assert client.delete("/harnesses/echo").json() == {"deleted": True} and not d.exists()
