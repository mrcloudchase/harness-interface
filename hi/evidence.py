"""Per-harness evidence for the router: the harness's recent runs, exactly as recorded. No rates,
no medians, nothing normalized. Each line is what the harness itself reported, and Jev reads the
lines the way a person would read a log. A card carries a track record, not a summary of one."""
from __future__ import annotations

import json

from .models import Run, Verdict

RECENT = 10          # lines per card: enough history to read, small enough for one Jev state
TASK_CHARS = 80


def label(run: Run) -> Verdict | None:
    """A run's verdict; a run recorded before verdicts existed is read from its check."""
    if run.verdict is not None:
        return run.verdict
    if run.check is not None:
        return Verdict(success=bool(run.check.get("pass")), by="check", note=str(run.check.get("cmd") or ""))
    return None


def history(runs: list[Run], harness: str, limit: int = RECENT) -> list[dict]:
    """The newest `limit` finished runs of one harness, as recorded."""
    mine = sorted((r for r in runs if r.harness == harness and r.status != "running"),
                  key=lambda r: r.started_at, reverse=True)[:limit]
    out = []
    for r in mine:
        v = label(r)
        out.append({
            "task": r.request.task[:TASK_CHARS],
            "status": r.status,
            "verdict": ({"success": v.success, "by": v.by, **({"score": v.score} if v.score is not None else {})}
                        if v else None),
            "latency_s": r.latency_s,
            "usage": r.usage,
            "cost_usd": r.output.get("cost_usd"),
        })
    return out


def sentence(lines: list[dict]) -> str:
    """The history as text for an option's description. Every field as the harness gave it."""
    if not lines:
        return "History: no runs yet."
    rows = []
    for h in lines:
        v = h["verdict"]
        verdict = ("success" if v["success"] else "failure") + f" by {v['by']}" + (f" {v['score']}" if "score" in v else "") if v else "unjudged"
        bits = [f"task {json.dumps(h['task'])}", f"status {h['status']}", verdict]
        if h["latency_s"] is not None:
            bits.append(f"{h['latency_s']}s")
        if h["cost_usd"] is not None:
            bits.append(f"cost {h['cost_usd']}")
        if h["usage"]:
            bits.append("usage " + json.dumps(h["usage"], separators=(",", ":")))
        rows.append("; ".join(bits))
    return "History (newest first): " + " | ".join(rows)
