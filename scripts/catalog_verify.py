"""Record the live suite's results into the catalog and write one docs page per package.

    python scripts/catalog_verify.py <logs dir>    # <name>.log files from scripts/live.py, one per package

Each package's catalog.json gets `verified` (the checks, how many passed, the provider and model),
and docs/catalog/<name>.md is written from the folder, the notes and the results, with the index
table in docs/catalog/index.md.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG, DOCS = ROOT / "catalog", ROOT / "docs" / "catalog"
CHECKS = ["make", "recall", "archive", "stream", "interrupt accepted", "steer", "cancel", "trace", "stateless"]
NOT_VERIFIED = [("Gemini CLI", "speaks only Google's Gemini API; neither OpenAI nor DeepSeek serves it"),
                ("Qoder CLI", "runs on Qoder's cloud and needs a Qoder account; the provider is not yours to choose"),
                ("SystemOne", "needs a TypeSafe decision-model provider beside the coding model"),
                ("Agent Zero", "has no command line; the reference drives it in-process with a Python driver, which is a harness of its own")]


def results(log: Path) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for line in log.read_text(errors="replace").splitlines() if log.is_file() else []:
        if m := re.match(r"(PASS|FAIL) ([a-z ]+?): ", line):
            out[m.group(2)] = m.group(1) == "PASS"
    return out


def page(name: str, meta: dict, folder: Path) -> str:
    cfg = json.loads((folder / "harness.json").read_text())
    v = meta["verified"]
    passed = [c for c in CHECKS if v["checks"].get(c)]
    failed = [c for c in CHECKS if not v["checks"].get(c)]
    lines = [f"# {meta['title']}", "", meta["intro"], "", "## Verified", "",
             f"`scripts/live.py` against a running platform, provider `{v['provider']}`, model `{v['model']}`: "
             f"**{len(passed)} of {len(CHECKS)}** checks passed ({', '.join(passed)})."]
    if failed:
        lines += ["", f"Not passing: {', '.join(failed)}. {meta.get('caveat', '')}".rstrip()]
    elif meta.get("caveat"):
        lines += ["", meta["caveat"]]
    lines += ["", "## Use it", "", "```bash",
              f"curl -s -X PUT $HI/v1/providers/{cfg['defaults']['provider']} -H \"Authorization: Bearer $KEY\" -H 'content-type: application/json' -d '{{\"url\": \"…\", \"api\": \"…\", \"key\": \"…\"}}'",
              f"curl -s -X PUT $HI/v1/harnesses/{name} -H \"Authorization: Bearer $KEY\" -H 'content-type: application/json' -d '{{\"catalog\": \"{name}\"}}'",
              f"curl -s $HI/v1/responses -H \"Authorization: Bearer $KEY\" -H 'content-type: application/json' -d '{{\"model\": \"{name}\", \"input\": \"Create hello.txt containing hello, then say done.\"}}'",
              "```", "", f"The package's default provider is `{cfg['defaults']['provider']}` and its default model `{cfg['defaults']['model'] or '(the provider decides)'}`; "
              f"name another with `{name}/<provider>/<model>`. The folder is `catalog/{name}/` in the repository.", ""]
    lines += ["## The folder", "", "`harness.json`:", "", "```json", (folder / "harness.json").read_text().rstrip(), "```", "",
              "`install.sh`:", "", "```bash", (folder / "install.sh").read_text().rstrip(), "```", "",
              "`request.sh`:", "", "```bash", (folder / "request.sh").read_text().rstrip(), "```"]
    for p in sorted(folder.glob("seeds/**/*")):
        if p.is_file():
            lines += ["", f"`{p.relative_to(folder).as_posix()}`:", "", "```", p.read_text().rstrip(), "```"]
    lines += ["", "## Notes", ""] + [f"- {n}" for n in meta["notes"]]
    return "\n".join(lines) + "\n"


def main(logs: Path) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    rows = []
    for folder in sorted(p for p in CATALOG.iterdir() if (p / "catalog.json").is_file() and p.name != "template"):
        meta = json.loads((folder / "catalog.json").read_text())
        res = results(logs / f"{folder.name}.log")
        if res:
            cfg = json.loads((folder / "harness.json").read_text())
            meta["verified"] = {"contract": 4, "checks": {c: res.get(c, False) for c in CHECKS}, "passed": sum(res.get(c, False) for c in CHECKS),
                                "provider": cfg["defaults"]["provider"], "model": cfg["defaults"]["model"]}
            (folder / "catalog.json").write_text(json.dumps(meta, indent=1) + "\n")
        (DOCS / f"{folder.name}.md").write_text(page(folder.name, meta, folder))
        v = meta["verified"]
        rows.append(f"| [{meta['title']}]({folder.name}.md) | `{v['provider']}` | {v['passed']}/{len(CHECKS)} | {meta.get('caveat', '')} |")
    index = ["# The catalog", "", "Every package below ships with the platform and was run through the nine checks of `scripts/live.py` "
             "against a running platform on the provider named (DeepSeek or OpenAI): make a file and say done, recall it "
             "on the next turn, the archive holds it, a turn streams, a steer is accepted and answered, a running turn "
             "cancels, the trace records all of it, and a `store: false` request leaves nothing behind. Fork one with "
             "`PUT /v1/harnesses/<name>` and `{\"catalog\": \"<name>\"}`; its page shows the whole folder. "
             "[Demos](../demos.md) shows six of them running.", "",
             "| Package | Default provider | Checks | Note |", "|---|---|---|---|", *rows, "",
             "Not in the catalog, and why:", "", *(f"- **{n}**: {why}." for n, why in NOT_VERIFIED), ""]
    (DOCS / "index.md").write_text("\n".join(index))
    print("\n".join(rows))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
