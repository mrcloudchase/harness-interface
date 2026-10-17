"""Output capture, verdicts from check / status / person / judge, and the evidence on cards."""
import asyncio
import json

from hi.evidence import history, sentence
from hi.models import JudgeSpec, Run, RunRequest, Verdict
from hi.router.jev import JevJudge


def test_output_endpoint_keeps_the_stream(client, echo):
    r = client.post("/runs", json={"task": "keep me", "harness": "echo", "stream": False})
    run_id = r.headers["x-run-id"]
    out = client.get(f"/runs/{run_id}/output")
    assert out.status_code == 200 and out.headers["content-type"].startswith("application/x-ndjson")
    assert out.text == r.json()["body"]
    assert json.loads(out.text.splitlines()[0])["text"] == "echo: keep me"


def test_check_sets_verdict(client, echo):
    ok = client.post("/runs", json={"task": "x", "harness": "echo", "check": "test -f hello.txt", "stream": False}).json()["run"]
    assert ok["verdict"] == {**ok["verdict"], "success": True, "by": "check"}
    bad = client.post("/runs", json={"task": "x", "harness": "echo", "check": "false", "stream": False}).json()["run"]
    assert bad["verdict"]["success"] is False and bad["verdict"]["by"] == "check"


def test_failed_harness_is_a_failed_verdict(client, echo):
    spec = echo.model_dump(mode="json")
    spec["run"]["argv"] = ["bash", "-c", "exit 3"]
    client.put("/harnesses/echo", json=spec)
    run = client.post("/runs", json={"task": "x", "harness": "echo", "stream": False}).json()["run"]
    assert run["status"] == "fail" and run["verdict"]["by"] == "status" and run["verdict"]["success"] is False


def test_no_check_no_judge_means_no_verdict(client, echo):
    run = client.post("/runs", json={"task": "x", "harness": "echo", "stream": False}).json()["run"]
    assert run["verdict"] is None


def test_person_overrides(client, echo):
    run = client.post("/runs", json={"task": "x", "harness": "echo", "check": "false", "stream": False}).json()["run"]
    r = client.patch(f"/runs/{run['id']}", json={"success": True, "note": "looked fine to me"})
    v = r.json()["verdict"]
    assert v["success"] is True and v["by"] == "human" and v["note"] == "looked fine to me"
    assert client.patch("/runs/r_nope", json={"success": True}).status_code == 404


def test_cards_carry_history_as_recorded(client, echo):
    assert client.get("/cards").json()[0]["evidence"] == "History: no runs yet."
    client.post("/runs", json={"task": "first task", "harness": "echo", "check": "true", "stream": False})
    client.post("/runs", json={"task": "second task", "harness": "echo", "check": "false", "stream": False})
    card = client.get("/cards").json()[0]
    h = card["history"]
    assert [x["task"] for x in h] == ["second task", "first task"]           # newest first
    assert h[0]["verdict"] == {"success": False, "by": "check"} and h[1]["verdict"]["success"] is True
    assert h[0]["usage"] == {"input_tokens": 1, "output_tokens": 1} and h[0]["cost_usd"] is None
    assert card["evidence"].startswith('History (newest first): task "second task"; status ok; failure by check; ')
    assert 'usage {"input_tokens":1,"output_tokens":1}' in card["evidence"]


def test_history_and_sentence():
    def run(h, ok, lat, usage=None, cost=None, started=0.0):
        r = Run(session="s", harness=h, request=RunRequest(task="t"), status="ok", latency_s=lat,
                usage=usage, output={"cost_usd": cost} if cost is not None else {}, started_at=started)
        if ok is not None:
            r.verdict = Verdict(success=ok, by="jev", score=0.9 if ok else 0.2)
        return r
    runs = [run("a", True, 2.0, {"in": 10}, 0.01, started=1), run("a", None, 6.0, started=2), run("b", None, 1.0)]
    h = history(runs, "a")
    assert [x["latency_s"] for x in h] == [6.0, 2.0]
    assert h[1] == {"task": "t", "status": "ok", "verdict": {"success": True, "by": "jev", "score": 0.9},
                    "latency_s": 2.0, "usage": {"in": 10}, "cost_usd": 0.01}
    assert sentence(h) == ('History (newest first): task "t"; status ok; unjudged; 6.0s | '
                           'task "t"; status ok; success by jev 0.9; 2.0s; cost 0.01; usage {"in":10}')
    assert history(runs, "a", limit=1) == h[:1]
    assert sentence([]) == "History: no runs yet."


class FakeJev:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def evaluate(self, model, state, questions):
        self.calls.append((model, state, questions))
        return self.answers


def judge_spec():
    return JudgeSpec(questions={"success": {"type": "noul", "instructions": "done?"},
                                "quality": {"type": "score", "instructions": "how good?", "criteria": ["bad", "ok", "good"]}},
                     success_when="success.probability >= 0.7")


def test_jev_judge_reads_task_answer_and_files():
    fake = FakeJev({"success": {"type": "noul", "noul": 0.92},
                    "quality": {"type": "score", "score": 1.8, "confidence": 0.6, "probabilities": {"0": 0.0, "1": 0.2, "2": 0.8}}})
    run = Run(session="s", harness="h", request=RunRequest(task="summarize", instructions="short"), status="ok")
    v = asyncio.run(JevJudge(judge_spec(), fake).judge(run, "the summary", {"out.md": "# Summary"}))
    assert v.success is True and v.by == "jev" and v.score == 0.92 and v.answers["quality"]["level"] == 2
    model, state, questions = fake.calls[0]
    assert state["task"] == "summarize" and state["answer"] == "the summary" and state["files"] == {"out.md": "# Summary"}
    assert set(questions) == {"success", "quality"} and "criteria" not in questions["success"]


def test_jev_judge_below_threshold_fails():
    fake = FakeJev({"success": {"type": "noul", "noul": 0.4}, "quality": {"type": "score", "score": 0.5, "probabilities": {}}})
    run = Run(session="s", harness="h", request=RunRequest(task="t"), status="ok")
    v = asyncio.run(JevJudge(judge_spec(), fake).judge(run, "meh", {}))
    assert v.success is False and v.score == 0.4


def test_judge_spec_rejects_unknown_reference():
    import pytest
    with pytest.raises(ValueError):
        JudgeSpec(questions={"a": {"type": "noul", "instructions": "?"}}, success_when="b.probability > 0.5")
