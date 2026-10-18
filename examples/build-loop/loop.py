"""A build loop around harness-interface: give it a spec and an acceptance test suite, and it
builds the project task by task, unattended, until every test passes or it runs out of time or
budget. You stop prompting the harness; the loop does, and the tests decide when it's done.

    plan ─► for each task: build ─► verify ─► review ─► checkpoint
                             ▲        │ fail: feed the failures back; after N tries, roll back
                             └────────┘ and escalate to the next harness

- **The tests decide.** They run in a throwaway container, outside every harness. A harness
  that edits them has its edits thrown away.
- **The loop owns the truth.** The project lives in a local git repository. Harnesses are
  workers: each task starts a fresh conversation seeded with the repository's files. Accepted
  work is committed; failed work is rolled back.
- **Different harnesses check each other.** A second harness reviews every change that passes;
  its objections get a round of revision, but it advises, and the tests still decide; an
  objection a change is accepted over is in the report. A stuck task escalates to the next
  harness in line.
- **Everything is visible.** Each harness's own output streams to the terminal as it works, and
  each turn's diff is shown after it. Every turn is in .loop/log.jsonl, and `hi show <id>` or
  `hi diff <id>` replays any of them.
- **It stops cleanly.** At its deadline or budget it cancels the run in flight, rolls back
  unaccepted work, and reports. State is saved after every task, so it can resume.

    python loop.py --project switchboard --repo ./out --minutes 20 --budget 10
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

# ── the terminal ────────────────────────────────────────────────────────────────────────────────
WIDTH = shutil.get_terminal_size((120, 40)).columns
BOLD, DIM, RED, GREEN, YELLOW, CYAN, MAGENTA, OFF = (f"\033[{c}m" for c in (1, 2, 31, 32, 33, 36, 35, 0))


def say(text: str = "", color: str = "") -> None:
    print(f"{color}{text}{OFF}" if color else text, flush=True)


def banner(title: str, status: str) -> None:
    left = f"━━ {title} "
    say(f"\n{BOLD}{CYAN}{left}{'━' * max(3, WIDTH - len(left) - len(status) - 2)} {status}{OFF}")


def clip(text: str, width: int = WIDTH - 6) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def show_diff(diff: str) -> None:
    for line in diff.splitlines():
        color = (BOLD if line.startswith(("diff --git", "+++", "---")) else GREEN if line.startswith("+")
                 else RED if line.startswith("-") else CYAN if line.startswith("@@") else DIM)
        say(f"  {line}"[:WIDTH], color)


def render(kind: str, line: str) -> str | None:
    """One line of a harness's own stream, as a person watching would want it: the text it
    writes and the tools it calls, from the CLIs' JSON events; anything else as printed."""
    if kind == "log":
        return f"{DIM}  ! {clip(line)}{OFF}" if line.strip() else None
    try:
        ev = json.loads(line)
    except ValueError:
        return f"  {clip(line)}" if line.strip() else None
    if not isinstance(ev, dict):
        return None
    parts = []
    for c in (ev.get("message") or {}).get("content") or []:              # Claude Code and kin
        if c.get("type") == "text" and c.get("text", "").strip():
            parts.append(f"  {clip(c['text'])}")
        elif c.get("type") == "tool_use":
            arg = c.get("input", {})
            detail = arg.get("command") or arg.get("file_path") or arg.get("pattern") or arg.get("description") or ""
            parts.append(f"{YELLOW}  ⚙ {c.get('name')}{OFF} {clip(detail, WIDTH - 20)}")
        elif c.get("type") == "tool_result":
            body = c.get("content")
            body = body if isinstance(body, str) else " ".join(b.get("text", "") for b in body or [] if isinstance(b, dict))
            parts.append(f"{DIM}    ↳ {clip(body, WIDTH - 12)}{OFF}")
    item = ev.get("item") or {}                                            # Codex
    if item.get("type") == "agent_message" and ev.get("type") == "item.completed":
        parts.append(f"  {clip(item.get('text', ''))}")
    elif item.get("type") == "command_execution" and ev.get("type") == "item.started":
        parts.append(f"{YELLOW}  ⚙ shell{OFF} {clip(item.get('command', ''), WIDTH - 20)}")
    elif item.get("type") == "file_change" and ev.get("type") == "item.completed":
        parts.append(f"{YELLOW}  ⚙ edit{OFF} " + ", ".join(f"{c.get('kind')} {c.get('path')}" for c in item.get("changes", [])))
    return "\n".join(parts) or f"{DIM}  {clip(line)}{OFF}"          # anything else, as printed


# ── the API ─────────────────────────────────────────────────────────────────────────────────────
class Api:
    """The calls the loop makes to harness-interface; nothing else knows its URLs."""

    def __init__(self, url: str):
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=httpx.Timeout(60, read=None))
        self.current: str | None = None                                    # the response in flight

    def turn(self, model: str, text: str, files: dict[str, str] | None = None, previous: str | None = None) -> dict:
        """One harness turn, streamed to the terminal as it happens. Returns the finished record."""
        body: dict = {"model": model, "stream": True,
                      "input": [{"type": "input_text", "text": text},
                                *({"type": "input_file", "filename": k, "file_data": v} for k, v in (files or {}).items())]}
        if previous:
            body["previous_response_id"] = previous
        record, event = None, None
        with self.http.stream("POST", "/responses", json=body) as r:
            if r.status_code >= 400:
                r.read()
                raise RuntimeError(f"{model}: HTTP {r.status_code}: {r.text}")
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    if event == "response.created":
                        self.current = data["response"]["id"]
                        say(f"{DIM}  {self.current} · {model} · streaming{OFF}")
                    elif event in ("harness.output", "harness.log"):
                        shown = render(event.split(".")[1], data["line"])
                        if shown:
                            say(shown)
                    elif event == "response.completed":
                        record = data["response"]
        self.current = None
        if record is None:
            raise RuntimeError(f"{model}: the stream ended without a record")
        return record

    def file(self, rid: str, path: str) -> bytes:
        return self.http.get(f"/responses/{rid}/files/{path}").raise_for_status().content

    def diff(self, rid: str) -> str:
        r = self.http.get(f"/responses/{rid}/diff")
        return r.text if r.status_code == 200 else ""

    def cancel(self) -> None:
        if self.current:
            self.http.post(f"/responses/{self.current}/cancel")


# ── the repository the loop owns ────────────────────────────────────────────────────────────────
class Repo:
    """The project as the loop knows it: a git repository. Accepted work is committed, and
    anything else can be rolled back to the last commit."""

    def __init__(self, path: Path, tests: dict[str, str]):
        self.path, self.tests = path, tests                                # tests: the acceptance suite, by path

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.path, capture_output=True, text=True, check=True).stdout.strip()

    def create(self, spec: str) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        if (self.path / ".git").exists():
            return
        self.git("init", "-q")
        (self.path / ".gitignore").write_text(".loop/\n__pycache__/\n.pytest_cache/\n")
        (self.path / "SPEC.md").write_text(spec)
        self.restore_tests()
        self.commit("the spec and the acceptance tests")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("-c", "user.name=build-loop", "-c", "user.email=loop@localhost", "commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "--short", "HEAD")

    def rollback(self) -> None:
        self.git("reset", "-q", "--hard", "HEAD")
        self.git("clean", "-qfd")

    def files(self) -> dict[str, str]:
        """Every text file in the project, to seed a harness's workspace."""
        out = {}
        for rel in self.git("ls-files", "--cached", "--others", "--exclude-standard").splitlines():
            try:
                out[rel] = (self.path / rel).read_text()
            except (UnicodeDecodeError, FileNotFoundError):
                pass
        return out

    def apply(self, api: Api, record: dict) -> list[str]:
        """Bring a turn's changes into the repository. Returns the test files it tried to change,
        which are restored."""
        h, tampered = record["harness"], []
        for rel in h.get("files", []):
            if rel in self.tests:
                tampered.append(rel)
                continue
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(api.file(record["id"], rel))
        for rel in h.get("deleted", []):
            if rel in self.tests:
                tampered.append(rel)
            else:
                (self.path / rel).unlink(missing_ok=True)
        self.restore_tests()
        return tampered

    def restore_tests(self) -> None:
        for rel, content in self.tests.items():
            (self.path / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.path / rel).write_text(content)


# ── the verdict ─────────────────────────────────────────────────────────────────────────────────
@dataclass
class Verdict:
    passed: set[str]
    failed: set[str]
    output: str

    def feedback(self, limit: int = 4000) -> str:
        """The failures, as the next turn will read them."""
        names = ", ".join(sorted(self.failed)) or "none"
        return f"These acceptance tests fail: {names}\n\npytest says:\n{self.output[-limit:]}"


def verify(repo: Repo, image: str, names: set[str]) -> Verdict:
    """Run the acceptance suite in a throwaway container: no network, a read-only copy of the
    repository. Its result is the only thing the loop believes."""
    proc = subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
                           "-e", "PYTHONDONTWRITEBYTECODE=1", "-v", f"{repo.path.resolve()}:/w:ro", "-w", "/w",
                           image, "python3", "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "tests"],
                          capture_output=True, text=True, timeout=300)
    out = proc.stdout + proc.stderr
    passed = {m for m in re.findall(r"^PASSED \S+::(\w+)", out, re.M)} & names
    return Verdict(passed, names - passed, out)


# ── the loop ────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Task:
    id: int
    title: str
    detail: str = ""
    tests: list[str] = field(default_factory=list)
    status: str = "todo"                                                   # todo, done, failed
    harness: str = ""
    turns: int = 0
    revisions: int = 0                                                     # turns spent on a reviewer's notes
    objection: str = ""                                                    # the review it was accepted over


class Loop:
    def __init__(self, args: argparse.Namespace):
        self.args, self.api = args, Api(args.url)
        project = Path(args.project)
        tests = {str(p.relative_to(project)): p.read_text() for p in sorted((project / "tests").rglob("*.py"))}
        self.names = set(re.findall(r"^def (test_\w+)", "".join(tests.values()), re.M))
        self.repo = Repo(Path(args.repo), tests)
        self.repo.create((project / "SPEC.md").read_text())
        self.home = self.repo.path / ".loop"
        self.home.mkdir(exist_ok=True)
        self.tasks: list[Task] = []
        self.spent, self.turns, self.unpriced = 0.0, 0, 0                   # unpriced: turns that reported no cost
        self.started, self.best = time.time(), 0
        self.deadline = self.started + args.minutes * 60
        self.timer = threading.Timer(args.minutes * 60, self.api.cancel)  # at the deadline, stop the run in flight
        self.timer.daemon = True
        self.load()

    # guards
    def out_of_time(self) -> bool:
        return time.time() >= self.deadline

    def out_of_money(self) -> bool:
        return self.spent >= self.args.budget

    def stopped(self) -> str | None:
        return "time" if self.out_of_time() else "budget" if self.out_of_money() else None

    def status(self) -> str:
        m, s = divmod(int(time.time() - self.started), 60)
        return f"{m:02d}:{s:02d}/{int(self.args.minutes):02d}:00 · ${self.spent:.2f} · {self.best}/{len(self.names)} tests"

    # state
    def load(self) -> None:
        state = self.home / "state.json"
        if state.exists():
            data = json.loads(state.read_text())
            self.tasks, self.spent = [Task(**t) for t in data["tasks"]], data["spent"]
            say(f"{YELLOW}resuming: {sum(t.status != 'todo' for t in self.tasks)}/{len(self.tasks)} tasks settled{OFF}")

    def save(self) -> None:
        (self.home / "state.json").write_text(json.dumps({"tasks": [asdict(t) for t in self.tasks], "spent": self.spent}, indent=2))

    def log(self, phase: str, record: dict, **extra) -> None:
        h = record["harness"]
        cost = h.get("cost_usd") or 0.0
        self.spent += cost
        self.turns += 1
        self.unpriced += h.get("cost_usd") is None
        entry = {"time": round(time.time() - self.started, 1), "phase": phase, "harness": h["name"],
                 "response": record["id"], "status": record["status"], "cost_usd": cost,
                 "files": h.get("files", []), "deleted": h.get("deleted", []), **extra}
        with open(self.home / "log.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    def answer(self, record: dict) -> str:
        return "".join(c.get("text", "") for m in record.get("output", []) for c in m.get("content", []))

    # phases
    def plan(self) -> None:
        if self.tasks:
            return
        banner(f"PLAN · {self.args.planner}", self.status())
        record = self.api.turn(self.args.planner, textwrap.dedent(f"""
            You are planning the build of the project described in SPEC.md. Its acceptance tests are in tests/.
            Do not write any code. Write one file, PLAN.json: a JSON list of 3 to 6 tasks, in build order,
            each {{"title": str, "detail": str, "tests": [names of the test functions it makes pass]}}.
            Together the tasks must cover every test in tests/. The test names are: {", ".join(sorted(self.names))}.
            """).strip(), files=self.repo.files())
        self.log("plan", record)
        try:
            plan = json.loads(self.api.file(record["id"], "PLAN.json"))
            self.tasks = [Task(i + 1, t["title"], t.get("detail", ""), [n for n in t.get("tests", []) if n in self.names])
                          for i, t in enumerate(plan)]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            say(f"{YELLOW}  no usable PLAN.json ({e}); one task for everything{OFF}")
            self.tasks = [Task(1, "Build the project to the spec", "", sorted(self.names))]
        for t in self.tasks:
            say(f"  {BOLD}{t.id}. {t.title}{OFF} {DIM}({len(t.tests)} tests){OFF}")
        self.save()

    def build(self, task: Task, baseline: Verdict) -> bool:
        """Work one task until its tests pass without breaking others, with retries and
        escalation. True if it was accepted."""
        for worker in self.args.workers:
            previous, prompt, reviews, revising = None, self.brief(task), 0, False
            for attempt in range(1, self.args.tries + 1):
                if self.stopped():
                    return False
                task.turns += 1
                task.revisions += revising
                step = f"revision {reviews}" if revising else f"try {attempt}"
                banner(f"TASK {task.id}/{len(self.tasks)} · {task.title} · {worker} · {step}", self.status())
                record = self.api.turn(worker, prompt, files=None if previous else self.repo.files(), previous=previous)
                previous = record["id"]
                tampered = self.repo.apply(self.api, record)
                self.show_changes(record, tampered)
                if record["status"] == "cancelled":
                    return False
                verdict = verify(self.repo, self.args.check_image, self.names)
                broke = baseline.passed - verdict.passed
                missing = set(task.tests) - verdict.passed
                self.best = max(self.best, len(verdict.passed))
                say(f"{BOLD}  verify:{OFF} {len(verdict.passed)}/{len(self.names)} passing · task {len(task.tests) - len(missing)}/{len(task.tests)}"
                    + (f" · {RED}broke {', '.join(sorted(broke))}{OFF}" if broke else ""))
                self.log("revise" if revising else "build", record, task=task.id, attempt=attempt,
                         passing=len(verdict.passed), tampered=tampered)
                revising = False
                if missing or broke:
                    prompt = verdict.feedback() + ("\n\nThese passed before your change and must pass again: " + ", ".join(sorted(broke)) if broke else "")
                    continue
                approved, notes = self.review(task, worker)
                if approved or reviews >= self.args.review_rounds or attempt == self.args.tries:
                    # the tests passed: a review that still objects is noted, and never undoes passing work
                    task.status, task.harness = "done", worker
                    task.objection = "" if approved else notes
                    over = "" if approved else " over the reviewer's objections"
                    say(f"{GREEN}{BOLD}  ✓ accepted{over} · checkpoint {self.repo.commit(f'task {task.id}: {task.title}')}{OFF}")
                    return True
                reviews, revising = reviews + 1, True
                prompt = f"A reviewer asked for changes:\n{notes}\n\nAddress them. The tests must keep passing."
            say(f"{YELLOW}  {worker} did not finish task {task.id}; rolling back" +
                (f" and escalating to {self.args.workers[self.args.workers.index(worker) + 1]}" if worker != self.args.workers[-1] else "") + OFF)
            self.repo.rollback()
        task.status = "failed"
        return False

    def brief(self, task: Task) -> str:
        return textwrap.dedent(f"""
            You are building the project described in SPEC.md, one task at a time. Its acceptance tests are in tests/.
            Task {task.id} of {len(self.tasks)}: {task.title}
            {task.detail}
            When you are done, these tests must pass: {", ".join(task.tests) or "(none of their own; keep the rest passing)"}.
            Do not change anything in tests/. Run them yourself with: python3 -m pytest -q tests
            Keep the code small and clear.
            """).strip()

    def review(self, task: Task, worker: str) -> tuple[bool, str]:
        reviewer = next((r for r in self.args.reviewers if r != worker), None)
        diff = self.repo.git("diff", "HEAD") + "\n" + "\n".join(
            f"new file {p}:\n{(self.repo.path / p).read_text()}" for p in self.repo.git("ls-files", "--others", "--exclude-standard").splitlines())
        if not reviewer or self.stopped():
            return True, ""
        banner(f"REVIEW · task {task.id} · {reviewer}", self.status())
        record = self.api.turn(reviewer, textwrap.dedent(f"""
            Review this change for task "{task.title}" of the project in SPEC.md. The tests already pass; judge
            correctness against the spec, and clarity. Do not change any files. Answer with one line that starts
            with APPROVE, or with REJECT: followed by the specific problems to fix.
            """).strip(), files={"SPEC.md": (self.repo.path / "SPEC.md").read_text(), "change.diff": diff})
        verdict = self.answer(record).strip()
        self.log("review", record, task=task.id, verdict=verdict)
        approved = not verdict.upper().startswith("REJECT")
        say(f"  {(GREEN + 'APPROVE') if approved else (RED + 'REJECT')}{OFF} {clip(verdict.split(':', 1)[-1] if not approved else '', WIDTH - 20)}")
        return approved, verdict

    def show_changes(self, record: dict, tampered: list[str]) -> None:
        h = record["harness"]
        say(f"{BOLD}  {record['status']}{OFF} · {h.get('latency_s')}s"
            + (f" · ${h['cost_usd']:.3f}" if h.get("cost_usd") else "")
            + (f" · changed {', '.join(h['files'])}" if h.get("files") else "")
            + (f" · deleted {', '.join(h['deleted'])}" if h.get("deleted") else ""))
        if tampered:
            say(f"{RED}  ✗ tried to change the acceptance tests ({', '.join(tampered)}); those edits were discarded{OFF}")
        diff = self.api.diff(record["id"])
        if diff.strip():
            show_diff(diff)

    def run(self) -> None:
        self.timer.start()
        banner("BUILD LOOP", f"{self.args.project} · workers {' → '.join(self.args.workers)} · reviewers {', '.join(self.args.reviewers)}")
        try:
            self.plan()
            baseline = verify(self.repo, self.args.check_image, self.names)
            for task in self.tasks:
                if task.status != "todo":
                    continue
                if self.stopped():
                    break
                if not baseline.failed or (task.tests and set(task.tests) <= baseline.passed):
                    task.status = "done"                                           # an earlier task did its work
                    say(f"{DIM}  task {task.id}: its tests already pass{OFF}")
                    continue
                self.build(task, baseline)
                baseline = verify(self.repo, self.args.check_image, self.names)
                self.save()
            # whatever the plan missed or a task gave up on: one more task, for the tests still failing
            if baseline.failed and not self.stopped():
                finish = Task(len(self.tasks) + 1, "Make the remaining tests pass", "", sorted(baseline.failed))
                self.tasks.append(finish)
                self.build(finish, baseline)
        except KeyboardInterrupt:
            self.api.cancel()
        finally:
            self.timer.cancel()
            self.repo.rollback()                                           # nothing unaccepted is kept
            self.save()
            self.report()

    def report(self) -> None:
        final = verify(self.repo, self.args.check_image, self.names)
        why = self.stopped()
        banner("RESULT", self.status())
        for t in self.tasks:
            mark = {"done": f"{GREEN}✓", "failed": f"{RED}✗"}.get(t.status, f"{DIM}·")
            work = (f"{t.turns} turn{'s' if t.turns != 1 else ''}" + (f", {t.revisions} on review notes" if t.revisions else "")
                    if t.turns else "already passing" if t.status == "done" else "")
            say(f"  {mark} {t.id}. {t.title}{OFF} {DIM}{t.status}{' by ' + t.harness if t.harness else ''}{', ' + work if work else ''}{OFF}")
            if t.objection:
                say(f"    {YELLOW}accepted over: {clip(t.objection, WIDTH - 20)}{OFF}")
        say(f"\n  {BOLD}{len(final.passed)}/{len(self.names)} acceptance tests pass{OFF} on the last checkpoint"
            + (f" · stopped: out of {why}" if why else ""))
        say(f"  {self.turns} harness turns · ${self.spent:.2f} reported"
            + (f" ({self.unpriced} turns reported no cost)" if self.unpriced else "") + f" · repository {self.repo.path} · log {self.home / 'log.jsonl'}")
        say(f"  {DIM}replay any turn: hi show <id> · hi diff <id> · hi output <id>{OFF}")


def main() -> None:
    p = argparse.ArgumentParser(description="Build a project from a spec and acceptance tests, with harnesses in a loop.")
    p.add_argument("--project", required=True, help="a folder with SPEC.md and tests/")
    p.add_argument("--repo", required=True, help="where the loop keeps the project it builds (a git repository)")
    p.add_argument("--url", default="http://127.0.0.1:8000", help="the harness-interface server")
    p.add_argument("--planner", default="claude-code")
    p.add_argument("--workers", default="claude-code,codex", type=lambda s: s.split(","), help="in escalation order")
    p.add_argument("--reviewers", default="codex,claude-code", type=lambda s: s.split(","), help="the first that isn't the worker reviews")
    p.add_argument("--tries", type=int, default=3, help="turns per task, per worker, revisions included")
    p.add_argument("--review-rounds", type=int, default=1, help="revisions a reviewer can ask for before the tests alone decide")
    p.add_argument("--minutes", type=float, default=20)
    p.add_argument("--budget", type=float, default=10.0, help="dollars, as the harnesses report them; a turn that reports none counts as 0")
    p.add_argument("--check-image", required=True, help="an image with the project's toolchain, for running the tests")
    Loop(p.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
