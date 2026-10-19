"""Which tasks a GitHub event starts. Only the human's own actions start work; Keeper's own steps
arrive as dispatches. Everyone else's events start nothing."""
from __future__ import annotations

from jobs import follow_ups

PR_ACTIONS = ("opened", "synchronize", "reopened", "ready_for_review")


def route(config, event: str, payload: dict) -> list[tuple[str, str]]:
    human = payload.get("sender", {}).get("login") == config.human
    if event == "workflow_dispatch":
        inputs = payload.get("inputs", {})
        return [(inputs["task"], inputs.get("item", ""))] if inputs.get("task") else []
    if event == "schedule":
        return [(task, "") for task in config.tasks_for(payload.get("schedule", ""))]
    if event == "pull_request":
        pr = payload["pull_request"]
        same_repo = pr["head"]["repo"] and pr["head"]["repo"]["full_name"] == payload["repository"]["full_name"]
        return [("gate", str(pr["number"]))] if payload["action"] in PR_ACTIONS and same_repo else []
    if not human:
        return []
    if event == "pull_request_review" and payload["action"] == "submitted":
        return [("gate", str(payload["pull_request"]["number"]))]
    if event == "issues":
        n = str(payload["issue"]["number"])
        if payload["action"] == "opened":
            return [("triage", n)]
        if payload["action"] == "labeled" and payload["label"]["name"] == "agent:ready":
            return [("spec", n)]
        return []
    if event == "issue_comment" and payload["action"] == "created" and "@keeper" in payload["comment"]["body"]:
        return [("answer", str(payload["issue"]["number"]))]
    if event == "push":
        branch = payload["ref"].removeprefix("refs/heads/")
        if branch not in (config.work, config.release):
            return []
        paths = sorted({p for c in payload.get("commits", []) for k in ("added", "modified", "removed") for p in c[k]})
        return follow_ups(config, paths, branch)
    return []
