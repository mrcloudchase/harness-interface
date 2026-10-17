"""Per-harness record from the run log and the contest log: how often it delivered, how often it
won, how fast, what it used and what it cost. The usage figures are medians of whatever keys the
harness itself reports, under the harness's own names; nothing is renamed or converted between
harnesses. The sentence is the whole of what Jev sees about a harness when it routes: the name
and the numbers, never the description."""
from __future__ import annotations

from statistics import median

from .models import Contest, Run


def summarize(runs: list[Run], contests: list[Contest]) -> dict[str, dict]:
    by: dict[str, list[Run]] = {}
    for r in runs:
        if r.status != "running":
            by.setdefault(r.harness, []).append(r)
    record = _record(contests)
    out = {}
    for name, rs in by.items():
        verdicts = [r.verdict for r in rs if r.verdict is not None]
        successes = sum(1 for v in verdicts if v.success)
        latencies = [r.latency_s for r in rs if r.latency_s is not None]
        wins, losses = record.get(name, (0, 0))
        out[name] = {
            "runs": len(rs),
            "judged": len(verdicts),
            "delivered": successes,
            "failed": len(verdicts) - successes,
            "success_rate": round(successes / len(verdicts), 3) if verdicts else None,
            "contests": wins + losses,
            "wins": wins,
            "losses": losses,
            "median_latency_s": round(median(latencies), 1) if latencies else None,
            "median_usage": _median_usage(rs),
            "median_cost_usd": _median_cost(rs),
        }
    return out


def _record(contests: list[Contest]) -> dict[str, tuple[int, int]]:
    """(wins, losses) per harness. Only a settled contest counts; every entrant but the winner lost."""
    out: dict[str, list[int]] = {}
    for c in contests:
        if c.status != "done":
            continue
        for name in c.runs:
            out.setdefault(name, [0, 0])[0 if name == c.winner else 1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def _numbers(d: dict, prefix: str = "") -> dict[str, float]:
    """Every numeric field in a usage object, nested ones joined with dots, names as the harness gave them."""
    out: dict[str, float] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[key] = float(v)
        elif isinstance(v, dict):
            out.update(_numbers(v, key + "."))
    return out


def _median_usage(rs: list[Run]) -> dict[str, float]:
    cols: dict[str, list[float]] = {}
    for r in rs:
        for k, v in _numbers(r.usage or {}).items():
            cols.setdefault(k, []).append(v)
    return {k: round(median(v), 1) for k, v in cols.items()}


def _median_cost(rs: list[Run]) -> float | None:
    costs = [float(r.output["cost_usd"]) for r in rs
             if isinstance(r.output.get("cost_usd"), (int, float)) and not isinstance(r.output.get("cost_usd"), bool)]
    return round(median(costs), 4) if costs else None


def sentence(stats: dict | None) -> str:
    """The record, in words: runs and how they were judged, contests and how they went."""
    if not stats or not stats.get("runs"):
        return "No runs yet."
    runs = f"{stats['runs']} runs"
    if stats["judged"]:
        runs += f": {stats['delivered']} delivered, {stats['failed']} failed ({int(stats['success_rate'] * 100)}%)"
    out = runs + "."
    if stats["contests"]:
        out += f" {stats['contests']} contests: {stats['wins']} won, {stats['losses']} lost."
    return out
