"""Per-harness evidence from the run log: how often it succeeded, how fast. The sentence this
produces is appended to a harness's description when Jev chooses, so a card carries a track
record and not only a promise."""
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
        judged = verdicts
        successes = sum(1 for v in verdicts if v.success)
        latencies = [r.latency_s for r in rs if r.latency_s is not None]
        out[name] = {
            "runs": len(rs),
            "judged": len(judged),
            "success_rate": round(successes / len(judged), 3) if judged else None,
            "median_latency_s": round(median(latencies), 1) if latencies else None,
        }
    return out


def sentence(stats: dict | None) -> str:
    if not stats or not stats.get("runs"):
        return "Evidence: no runs yet."
    parts = [f"{stats['runs']} runs"]
    if stats.get("judged"):
        parts.append(f"{int(stats['success_rate'] * 100)}% successful of {stats['judged']} judged")
    if stats.get("median_latency_s") is not None:
        parts.append(f"median {stats['median_latency_s']}s")
    return "Evidence: " + ", ".join(parts) + "."
