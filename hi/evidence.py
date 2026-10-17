"""Per-harness evidence from the run log: how often it succeeded, how fast, what it used and what
it cost. The usage figures are medians of whatever keys the harness itself reports, under the
harness's own names; nothing is renamed or converted between harnesses. The sentence is appended
to the harness's description when Jev chooses, so the options compare track records, each in its
own units, and Jev does the comparing."""
from __future__ import annotations

from statistics import median

from .models import Run, Verdict


def label(run: Run) -> Verdict | None:
    """A run's verdict; a run recorded before verdicts existed is read from its check."""
    if run.verdict is not None:
        return run.verdict
    if run.check is not None:
        return Verdict(success=bool(run.check.get("pass")), by="check", note=str(run.check.get("cmd") or ""))
    return None


def summarize(runs: list[Run]) -> dict[str, dict]:
    by: dict[str, list[Run]] = {}
    for r in runs:
        if r.status != "running":
            by.setdefault(r.harness, []).append(r)
    out = {}
    for name, rs in by.items():
        verdicts = [v for v in (label(r) for r in rs) if v is not None]
        successes = sum(1 for v in verdicts if v.success)
        latencies = [r.latency_s for r in rs if r.latency_s is not None]
        out[name] = {
            "runs": len(rs),
            "judged": len(verdicts),
            "success_rate": round(successes / len(verdicts), 3) if verdicts else None,
            "median_latency_s": round(median(latencies), 1) if latencies else None,
            "median_usage": _median_usage(rs),
            "median_cost_usd": _median_cost(rs),
        }
    return out


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
    if not stats or not stats.get("runs"):
        return "Evidence: no runs yet."
    parts = [f"{stats['runs']} runs"]
    if stats.get("judged"):
        parts.append(f"{int(stats['success_rate'] * 100)}% successful of {stats['judged']} judged")
    if stats.get("median_latency_s") is not None:
        parts.append(f"median {stats['median_latency_s']}s")
    parts.append(f"median cost ${stats['median_cost_usd']}" if stats.get("median_cost_usd") is not None
                 else "no cost reported")
    if stats.get("median_usage"):
        parts.append("median usage " + ", ".join(f"{k} {v:g}" for k, v in stats["median_usage"].items()))
    return "Evidence: " + ", ".join(parts) + "."
