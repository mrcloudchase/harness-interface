"""Stand-ins for GitHub and harness-interface, so Keeper's tests need no network, token or key. Each
records what it was asked, the way the real one would be changed by it."""
from __future__ import annotations

import itertools
import subprocess
from pathlib import Path


class FakeGitHub:
    def __init__(self, human: str = "owner"):
        self.human = human
        self._ids = itertools.count(1)
        self.items: dict[int, dict] = {}                 # issues and pull requests, by number
        self.comments_: dict[int, list[dict]] = {}
        self.statuses: dict[str, dict[str, str]] = {}    # sha → context → state
        self.reviews_: dict[int, list[dict]] = {}
        self.dispatched: list[tuple[str, str]] = []
        self.workflows: list[str] = []
        self.posts: list[tuple[str, str, str]] = []
        self.merged: list[dict] = []
        self.label_names: set[str] = set()
        self.sub_issues: list[tuple[int, int]] = []
        self.files_: dict[int, list[str]] = {}
        self.requested: list[str] = []

    # issues
    def _new(self, **fields) -> dict:
        n = next(self._ids)
        item = {"number": n, "id": 1000 + n, "node_id": f"N{n}", "state": "open", "labels": [], "body": "",
                "user": {"login": "github-actions[bot]"}, "html_url": f"https://github.test/{n}", **fields}
        self.items[n] = item
        self.comments_[n] = []
        return item

    def issue(self, n: int) -> dict:
        return self.items[int(n)]

    def issues(self, labels: str = "", state: str = "open", since: str = "", prs: bool = False) -> list[dict]:
        out = []
        for i in self.items.values():
            if state != "all" and i["state"] != state:
                continue
            if not prs and "pull_request" in i:
                continue
            if labels and labels not in {label["name"] for label in i["labels"]}:
                continue
            out.append(i)
        return out

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        return self._new(title=title, body=body, labels=[{"name": n} for n in labels])

    def edit_issue(self, n: int, **fields) -> dict:
        self.items[int(n)].update(fields)
        return self.items[int(n)]

    def comments(self, n: int) -> list[dict]:
        return list(self.comments_[int(n)])

    def comment(self, n: int, body: str, user: str = "github-actions[bot]") -> dict:
        c = {"id": next(self._ids) + 100000, "body": body, "user": {"login": user}}
        self.comments_[int(n)].append(c)
        return c

    def edit_comment(self, comment_id: int, body: str) -> dict:
        for cs in self.comments_.values():
            for c in cs:
                if c["id"] == comment_id:
                    c["body"] = body
                    return c
        raise KeyError(comment_id)

    def add_labels(self, n: int, labels: list[str]) -> None:
        have = {label["name"] for label in self.items[int(n)]["labels"]}
        self.items[int(n)]["labels"] += [{"name": x} for x in labels if x not in have]

    def remove_label(self, n: int, label: str) -> None:
        self.items[int(n)]["labels"] = [x for x in self.items[int(n)]["labels"] if x["name"] != label]

    def labels(self) -> list[dict]:
        return [{"name": n} for n in sorted(self.label_names)]

    def create_label(self, name: str, color: str, description: str) -> None:
        self.label_names.add(name)

    def add_sub_issue(self, parent: int, child_id: int) -> None:
        self.sub_issues.append((parent, child_id))

    def pin(self, node_id: str) -> None:
        pass

    def has_label(self, n: int, label: str) -> bool:
        return label in {x["name"] for x in self.items[int(n)]["labels"]}

    # pull requests
    def create_pull(self, title: str, head: str, base: str, body: str, sha: str = "", user: str = "github-actions[bot]") -> dict:
        return self._new(title=title, body=body, pull_request={}, user={"login": user},
                         head={"ref": head, "sha": sha or f"sha-{head}", "repo": {"full_name": "o/r"}},
                         base={"ref": base, "sha": f"base-{base}"}, merged_at=None, merge_commit_sha=None)

    def pull(self, n: int) -> dict:
        return self.items[int(n)]

    def pulls(self, state: str = "open") -> list[dict]:
        return [i for i in self.items.values() if "pull_request" in i and (state == "all" or i["state"] == state)]

    def pull_files(self, n: int) -> list[str]:
        return list(self.files_.get(int(n), []))

    def reviews(self, n: int) -> list[dict]:
        return list(self.reviews_.get(int(n), []))

    def review(self, n: int, login: str, state: str, sha: str) -> None:
        self.reviews_.setdefault(int(n), []).append({"user": {"login": login}, "state": state, "commit_id": sha})

    def request_review(self, n: int, login: str) -> None:
        self.requested.append(login)

    def merge(self, n: int, sha: str, title: str, message: str, method: str = "squash") -> dict:
        pr = self.items[int(n)]
        pr.update(state="closed", merged_at="2099-01-01T00:00:00Z", merge_commit_sha=f"merged-{n}")
        self.merged.append({"number": int(n), "title": title, "message": message, "method": method})
        return {"merged": True}

    # statuses, dispatches, posts
    def set_status(self, sha: str, state: str, description: str, context: str = "keeper/gate") -> None:
        self.statuses.setdefault(sha, {})[context] = state

    def status(self, sha: str, context: str = "keeper/gate") -> str:
        return self.statuses.get(sha, {}).get(context, "")

    def dispatch(self, task: str, item, ref: str, workflow: str = "keeper.yml") -> None:
        if workflow == "keeper.yml":
            self.dispatched.append((task, str(item)))
        else:
            self.workflows.append(workflow)

    def post(self, category: str, title: str, body: str) -> str:
        self.posts.append((category, title, body))
        return f"https://github.test/discussions/{len(self.posts)}"


class FakeRuntime:
    """Scripted turns. `script(turn, harness, text)` returns what the turn does:
    {"files": {path: str | None}, "result": {...}, "cost": usd}."""

    def __init__(self, script):
        self.script, self.turns = script, []
        self._results: dict[str, dict] = {}

    def turn(self, harness: str, instructions: str, text: str, files=None, previous=None) -> dict:
        n = len(self.turns)
        self.turns.append({"harness": harness, "instructions": instructions, "text": text,
                           "seeded": files is not None, "previous": previous})
        did = self.script(n, harness, text) or {}
        rid = f"resp_{n}"
        changed = {p: (v.encode() if isinstance(v, str) else v) for p, v in did.get("files", {}).items()}
        self._results[rid] = {"changes": changed, "result": did.get("result", {})}
        return {"id": rid, "output": [{"content": [{"text": did.get("answer", "")}]}],
                "harness": {"name": harness, "runtime": "docker", "cost_usd": did.get("cost", 0.1),
                            "files": [p for p, v in changed.items() if v is not None],
                            "deleted": [p for p, v in changed.items() if v is None]}}

    def changes(self, record: dict) -> dict:
        return self._results[record["id"]]["changes"]

    def result(self, record: dict) -> dict:
        return self._results[record["id"]]["result"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()
