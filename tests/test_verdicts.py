"""Output capture, verdicts from check / status / person / judge, and the evidence on cards."""
import asyncio
import json

from hi.evidence import sentence, summarize
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


def test_cards_carry_evidence(client, echo):
    assert client.get("/cards").json()[0]["evidence"] == "Evidence: no runs yet."
    client.post("/runs", json={"task": "x", "harness": "echo", "check": "true", "stream": False})
    client.post("/runs", json={"task": "x", "harness": "echo", "check": "false", "stream": False})
    card = client.get("/cards").json()[0]
    assert card["stats"]["runs"] == 2 and card["stats"]["judged"] == 2 and card["stats"]["success_rate"] == 0.5
    assert card["stats"]["median_usage"] == {"input_tokens": 1.0, "output_tokens": 1.0}
    assert card["evidence"].startswith("Evidence: 2 runs, 50% successful of 2 judged, median ")
    assert card["evidence"].endswith("no cost reported, median usage input_tokens 1, output_tokens 1.")


def test_summarize_keeps_each_harness_own_usage_names():
    def run(h, ok, lat, usage=None, cost=None):
        r = Run(session="s", harness=h, request=RunRequest(task="t"), status="ok", latency_s=lat,
                usage=usage, output={"cost_usd": cost} if cost is not None else {})
        if ok is not None:
            r.verdict = Verdict(success=ok, by="check")
        return r
    stats = summarize([
        run("a", True, 2.0, {"input_tokens": 10, "cache_read_input_tokens": 100, "detail": {"thinking": 4}}, 0.01),
        run("a", False, 4.0, {"input_tokens": 30, "cache_read_input_tokens": 300, "detail": {"thinking": 6}}, 0.03),
        run("a", None, 6.0),
        run("b", None, 1.0, {"cached_input_tokens": 500}),
    ])
    assert stats["a"] == {"runs": 3, "judged": 2, "success_rate": 0.5, "median_latency_s": 4.0,
                          "median_usage": {"input_tokens": 20.0, "cache_read_input_tokens": 200.0, "detail.thinking": 5.0},
                          "median_cost_usd": 0.02}
    assert stats["b"] == {"runs": 1, "judged": 0, "success_rate": None, "median_latency_s": 1.0,
                          "median_usage": {"cached_input_tokens": 500.0}, "median_cost_usd": None}
    assert sentence(stats["a"]) == ("Evidence: 3 runs, 50% successful of 2 judged, median 4.0s, median cost $0.02, "
                                    "median usage input_tokens 20, cache_read_input_tokens 200, detail.thinking 5.")
    assert sentence(stats["b"]) == "Evidence: 1 runs, median 1.0s, no cost reported, median usage cached_input_tokens 500."
    assert sentence(None) == "Evidence: no runs yet."


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


def test_ui_and_preview(client, echo):
    assert client.get("/ui").status_code == 200 and "<title>" in client.get("/ui").text
    assert client.get("/", follow_redirects=False).status_code in (302, 307)
    before = len(client.get("/runs").json())
    r = client.post("/route/preview", json={"task": "anything"})
    assert r.status_code == 200
    d = r.json()
    assert d["engine"] == "static" and d["jev_request"] is None and d["decision"]["harness"] == "echo"
    assert len(client.get("/runs").json()) == before            # a preview never runs anything
