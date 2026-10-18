"""From outside, everything a harness does: stdout and stderr as they come, every file it adds,
changes or deletes, the diff of each turn (live while it runs), and each turn's files as it left them."""
import json
import time

SCRIPT = {
    1: 'echo "to stdout"; echo "to stderr" >&2; printf "one\\n" > a.txt; printf "x\\n" > gone.txt\n',
    2: 'echo "turn two"; printf "two\\n" > a.txt; rm gone.txt; printf \'{"status":"ok","session_id":"s"}\' > "$HI_OUTPUT"\n',
}


def harness(client, echo, script, name="seen"):
    spec = {**echo.model_dump(mode="json"), "name": name, "scripts": {"run.sh": script}}
    assert client.put(f"/harnesses/{name}", json=spec).status_code == 200
    return name


def sse(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_stdout_and_stderr_stream_as_they_come(client, echo):
    name = harness(client, echo, SCRIPT[1])
    with client.stream("POST", "/responses", json={"model": name, "input": "x", "stream": True}) as r:
        events = sse(b"".join(r.iter_bytes()).decode())
    middle = [(e, d["line"]) for e, d in events[1:-1]]
    assert ("harness.output", "to stdout") in middle and ("harness.log", "to stderr") in middle
    rid = events[0][1]["response"]["id"]
    assert client.get(f"/responses/{rid}/log").text == "to stderr\n"          # and kept


def test_every_change_and_each_turns_files(client, echo):
    name = harness(client, echo, SCRIPT[1])
    first = client.post("/responses", json={"model": name, "input": "x"}).json()
    assert first["harness"]["files"] == ["a.txt", "gone.txt"] and first["harness"]["deleted"] == []
    harness(client, echo, SCRIPT[2])
    second = client.post("/responses", json={"model": name, "input": "y", "previous_response_id": first["id"]}).json()
    h = second["harness"]
    assert h["files"] == ["a.txt"] and h["deleted"] == ["gone.txt"]            # deletions are seen
    assert h["base"] and h["commit"] and h["base"] != h["commit"]

    diff = client.get(f"/responses/{second['id']}/diff").text
    assert "-one" in diff and "+two" in diff and "deleted file mode" in diff and "gone.txt" in diff

    # each response's files as it left them, not as they are now
    assert client.get(f"/responses/{first['id']}/files/a.txt").text == "one\n"
    assert client.get(f"/responses/{second['id']}/files/a.txt").text == "two\n"
    assert client.get(f"/responses/{first['id']}/files/gone.txt").text == "x\n"
    assert client.get(f"/responses/{second['id']}/files/gone.txt").status_code == 404
    assert "gone.txt" in client.get(f"/responses/{first['id']}/files").json()
    assert "gone.txt" not in client.get(f"/responses/{second['id']}/files").json()


def test_the_diff_is_live_while_the_harness_works(live, echo):
    name = harness(live, echo, 'printf "draft\\n" > notes.md; sleep 3; printf \'{"status":"ok"}\' > "$HI_OUTPUT"\n', name="slowdiff")
    with live.stream("POST", "/responses", json={"model": name, "input": "x", "stream": True}) as r:
        rid = r.headers["x-response-id"]
        deadline, diff = time.time() + 5, ""
        while "+draft" not in diff and time.time() < deadline:
            diff = live.get(f"/responses/{rid}/diff").text
            time.sleep(0.2)
        assert "+draft" in diff and "notes.md" in diff                         # before the run has ended
        assert live.get(f"/responses/{rid}").json()["status"] == "in_progress"
        assert "notes.md" in live.get(f"/responses/{rid}/files").json()
        assert live.get(f"/responses/{rid}/files/.hi/request.json").status_code == 404   # internal, even mid-run
        list(r.iter_lines())


def test_a_projects_gitignore_never_exposes_the_harnesss_own_state(client, echo):
    """A request's .gitignore replaces nothing the server relies on: the harness's private state,
    .home and .hi, is never committed, diffed or listed."""
    name = harness(client, echo, 'mkdir -p .home && echo secret > .home/auth.json; echo code > app.py\n', name="private")
    body = {"model": name, "input": [{"type": "input_text", "text": "x"},
                                      {"type": "input_file", "filename": ".gitignore", "file_data": "build/\n"}]}
    d = client.post("/responses", json=body).json()
    assert d["harness"]["files"] == ["app.py"]
    diff = client.get(f"/responses/{d['id']}/diff").text
    listed = client.get(f"/responses/{d['id']}/files").json()
    assert "secret" not in diff and ".home" not in diff and ".hi/" not in diff
    assert not any(p.startswith((".home", ".hi")) for p in listed) and "app.py" in listed and ".gitignore" in listed
    assert client.get(f"/responses/{d['id']}/files/.home/auth.json").status_code == 404
