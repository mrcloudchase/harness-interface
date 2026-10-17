"""Fan-out through the whole server: two harnesses, a judge, a referee, a record."""
import asyncio
import json

import pytest

from hi.models import ArenaSpec, RunRequest
from hi.router.jev import JevClient, JevReferee

JUDGE = {"questions": {"completed": {"type": "noul", "instructions": "done?"}}, "success_when": "completed.probability >= 0.5"}


class FakeJev:
    """Answers the judge's noul and the referee's choice; `winner` names who the referee picks."""

    def __init__(self, winner=None):
        self.winner, self.calls = winner, []

    async def evaluate(self, model, state, questions):
        self.calls.append((model, state, questions))
        if "completed" in questions:
            return {"completed": {"type": "noul", "noul": 0.9}}
        options = list(questions["winner"]["criteria"])
        pick = self.winner or options[-1]
        return {"winner": {"type": "choice", "choice": pick, "confidence": 0.8,
                           "probabilities": {o: (0.8 if o == pick else 0.2 / (len(options) - 1)) for o in options}}}


@pytest.fixture
def arena(client, echo, monkeypatch):
    """Two echo harnesses, a judged route, a Jev key, and Jev faked. Returns the fake."""
    fake = FakeJev()
    monkeypatch.setattr(JevClient, "evaluate", lambda self, *a: fake.evaluate(*a))
    second = echo.model_dump(mode="json")
    second["name"] = "echo2"
    assert client.put("/harnesses/echo2", json=second).status_code == 200
    assert client.put("/route", json={"kind": "Route", "engine": "static", "default": "echo", "judge": JUDGE}).status_code == 200
    client.put("/secrets/TYPESAFE_API_KEY", content="k")
    return fake


def test_fanout_needs_a_judge(client, echo):
    r = client.post("/runs", json={"task": "x", "stream": False})
    assert r.status_code == 400 and "judge" in r.text


def test_fanout_runs_everyone_and_the_referee_picks(client, arena):
    arena.winner = "echo"
    r = client.post("/runs", json={"task": "say hi", "stream": False})
    assert r.status_code == 200
    contest, runs = r.json()["contest"], r.json()["runs"]
    assert r.headers["x-contest-id"] == contest["id"]
    assert set(runs) == {"echo", "echo2"} and contest["status"] == "done" and contest["winner"] == "echo"
    assert contest["session"] == runs["echo"]["session"]
    for name, run in runs.items():
        assert run["mode"] == "fanout" and run["contest"] == contest["id"] and run["harness"] == name
        assert run["verdict"]["success"] is True and run["verdict"]["by"] == "jev"
    assert runs["echo"]["session"] != runs["echo2"]["session"]      # each entrant works alone
    # the referee saw the task and one option per deliverer, each being what it produced
    model, state, questions = arena.calls[-1]
    assert state == {"task": "say hi", "instructions": ""}
    opts = {k: json.loads(v) for k, v in questions["winner"]["criteria"].items()}
    assert set(opts) == {"echo", "echo2"} and opts["echo"]["answer"] == "echo: say hi" and opts["echo"]["files"] == {"hello.txt": "hello from echo\n"}
    assert contest["answers"]["winner"]["choice"] == "echo"
    # the record: one contest each, the winner won, the other lost; both delivered
    cards = {c["name"]: c for c in client.get("/cards").json()}
    assert cards["echo"]["record"] == "1 runs: 1 delivered, 0 failed (100%). 1 contests: 1 won, 0 lost."
    assert cards["echo2"]["record"] == "1 runs: 1 delivered, 0 failed (100%). 1 contests: 0 won, 1 lost."
    assert client.get(f"/contests/{contest['id']}").json()["winner"] == "echo"
    assert [c["id"] for c in client.get("/contests").json()] == [contest["id"]]
    # continuing from the contest continues the winner's session on the winner's harness
    follow = client.post("/runs", json={"task": "again", "session": contest["session"], "stream": False}).json()["run"]
    assert follow["harness"] == "echo" and follow["mode"] == "named" and follow["contest"] is None


def test_fanout_streams_lines_tagged_by_harness(client, arena):
    with client.stream("POST", "/runs", json={"task": "go"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
        contest_id = r.headers["x-contest-id"]
        lines = [json.loads(l) for l in b"".join(r.iter_bytes()).decode().splitlines() if l.strip()]
    tagged, final = lines[:-1], lines[-1]
    assert {l["harness"] for l in tagged} == {"echo", "echo2"}
    assert all(json.loads(l["line"]) for l in tagged)                 # each line is one line of that harness's own output
    assert final["contest"]["id"] == contest_id and final["contest"]["status"] == "done" and final["contest"]["winner"]


def test_one_deliverer_wins_outright_and_none_means_no_winner(client, arena):
    broken = client.get("/harnesses/echo2").json()
    broken["run"]["argv"] = ["bash", "-c", "exit 3"]
    client.put("/harnesses/echo2", json=broken)
    before = len(arena.calls)
    contest = client.post("/runs", json={"task": "x", "stream": False}).json()["contest"]
    assert contest["winner"] == "echo" and contest["answers"] == {}
    assert len(arena.calls) == before + 1                               # one judge call, no referee
    cards = {c["name"]: c for c in client.get("/cards").json()}
    assert cards["echo2"]["stats"]["failed"] == 1 and cards["echo2"]["stats"]["losses"] == 1

    fixed = client.get("/harnesses/echo").json()
    fixed["run"]["argv"] = ["bash", "-c", "exit 3"]
    client.put("/harnesses/echo", json=fixed)
    contest = client.post("/runs", json={"task": "x", "stream": False}).json()["contest"]
    assert contest["status"] == "done" and contest["winner"] is None and contest["session"] is None
    cards = {c["name"]: c for c in client.get("/cards").json()}
    assert cards["echo"]["stats"]["losses"] == 1 and cards["echo2"]["stats"]["losses"] == 2


def test_referee_failure_voids_the_contest(client, arena):
    arena.winner = "nobody"
    contest = client.post("/runs", json={"task": "x", "stream": False}).json()["contest"]
    assert contest["status"] == "void" and contest["winner"] is None and "did not enter" in contest["note"]
    cards = {c["name"]: c for c in client.get("/cards").json()}
    assert cards["echo"]["stats"]["contests"] == 0 and cards["echo"]["record"] == "1 runs: 1 delivered, 0 failed (100%)."


def test_referee_questions_are_excerpts():
    referee = JevReferee(ArenaSpec(instructions="best?"), FakeJev("b"))
    entrants = {"a": ("x" * 5000, {f"f{i}.txt": "y" * 2000 for i in range(6)}), "b": ("short", {})}
    q = referee.questions(entrants)["winner"]
    assert q["type"] == "choice" and q["instructions"] == "best?"
    a = json.loads(q["criteria"]["a"])
    assert len(a["answer"]) == 4000 and len(a["files"]) == 4 and all(len(v) == 1000 for v in a["files"].values())
    winner, answers = asyncio.run(referee.pick(RunRequest(task="t"), entrants))
    assert winner == "b" and answers["winner"]["choice"] == "b"
