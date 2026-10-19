"""GitHub, as Keeper uses it: the repository's issues, pull requests, statuses, labels, Discussions and
workflow dispatches, through the REST and GraphQL APIs with the job's GITHUB_TOKEN. Nothing else
in the engine talks to GitHub."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

API = "https://api.github.com"
WORKFLOW = "keeper.yml"                      # the entry workflow every dispatch goes to


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


class GitHub:
    def __init__(self, repo: str, token: str, api: str = API):
        self.repo, self._token, self.api = repo, token, api
        self.owner, self.name = repo.split("/", 1)

    def __repr__(self) -> str:
        return f"GitHub({self.repo})"        # never the token

    # ── transport ──────────────────────────────────────────────────────────────────────────────
    def call(self, method: str, path: str, body: Any = None) -> Any:
        url = path if path.startswith("http") else f"{self.api}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise GitHubError(e.code, e.read().decode(errors="replace")[:500]) from None
        return json.loads(raw) if raw else None

    def _repo(self, path: str) -> str:
        return f"/repos/{self.repo}{path}"

    def _pages(self, path: str, limit: int = 5) -> list[dict]:
        out, sep = [], "&" if "?" in path else "?"
        for page in range(1, limit + 1):
            batch = self.call("GET", self._repo(f"{path}{sep}per_page=100&page={page}"))
            out += batch
            if len(batch) < 100:
                break
        return out

    def graphql(self, query: str, **variables: Any) -> dict:
        r = self.call("POST", "/graphql", {"query": query, "variables": variables})
        if r.get("errors"):
            raise GitHubError(200, json.dumps(r["errors"])[:500])
        return r["data"]

    # ── issues ─────────────────────────────────────────────────────────────────────────────────
    def issue(self, n: int) -> dict:
        return self.call("GET", self._repo(f"/issues/{n}"))

    def issues(self, labels: str = "", state: str = "open", since: str = "", prs: bool = False) -> list[dict]:
        """Issues; with `prs`, pull requests too, as the issues API lists them."""
        q = f"/issues?state={state}" + (f"&labels={labels}" if labels else "") + (f"&since={since}" if since else "")
        return [i for i in self._pages(q) if prs or "pull_request" not in i]

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        return self.call("POST", self._repo("/issues"), {"title": title, "body": body, "labels": labels})

    def edit_issue(self, n: int, **fields: Any) -> dict:
        return self.call("PATCH", self._repo(f"/issues/{n}"), fields)

    def comments(self, n: int) -> list[dict]:
        return self._pages(f"/issues/{n}/comments")

    def comment(self, n: int, body: str) -> dict:
        return self.call("POST", self._repo(f"/issues/{n}/comments"), {"body": body})

    def edit_comment(self, comment_id: int, body: str) -> dict:
        return self.call("PATCH", self._repo(f"/issues/comments/{comment_id}"), {"body": body})

    def add_labels(self, n: int, labels: list[str]) -> None:
        self.call("POST", self._repo(f"/issues/{n}/labels"), {"labels": labels})

    def remove_label(self, n: int, label: str) -> None:
        try:
            self.call("DELETE", self._repo(f"/issues/{n}/labels/{label}"))
        except GitHubError as e:
            if e.status != 404:
                raise

    def labels(self) -> list[dict]:
        return self._pages("/labels")

    def create_label(self, name: str, color: str, description: str) -> None:
        self.call("POST", self._repo("/labels"), {"name": name, "color": color, "description": description})

    def add_sub_issue(self, parent: int, child_id: int) -> None:
        self.call("POST", self._repo(f"/issues/{parent}/sub_issues"), {"sub_issue_id": child_id})

    def pin(self, node_id: str) -> None:
        self.graphql("mutation($id: ID!) { pinIssue(input: {issueId: $id}) { issue { id } } }", id=node_id)

    # ── pull requests ──────────────────────────────────────────────────────────────────────────
    def pull(self, n: int) -> dict:
        return self.call("GET", self._repo(f"/pulls/{n}"))

    def pulls(self, state: str = "open") -> list[dict]:
        return self._pages(f"/pulls?state={state}")

    def pull_files(self, n: int) -> list[str]:
        return [f["filename"] for f in self._pages(f"/pulls/{n}/files")]

    def create_pull(self, title: str, head: str, base: str, body: str) -> dict:
        return self.call("POST", self._repo("/pulls"), {"title": title, "head": head, "base": base, "body": body})

    def reviews(self, n: int) -> list[dict]:
        return self._pages(f"/pulls/{n}/reviews")

    def request_review(self, n: int, login: str) -> None:
        self.call("POST", self._repo(f"/pulls/{n}/requested_reviewers"), {"reviewers": [login]})

    def merge(self, n: int, sha: str, title: str, message: str, method: str = "squash") -> dict:
        return self.call("PUT", self._repo(f"/pulls/{n}/merge"), {
            "sha": sha, "commit_title": title, "commit_message": message, "merge_method": method})

    # ── statuses, dispatches, releases ─────────────────────────────────────────────────────────
    def set_status(self, sha: str, state: str, description: str, context: str = "keeper/gate") -> None:
        self.call("POST", self._repo(f"/statuses/{sha}"),
                  {"state": state, "description": description[:140], "context": context})

    def status(self, sha: str, context: str = "keeper/gate") -> str:
        for s in self.call("GET", self._repo(f"/commits/{sha}/status"))["statuses"]:
            if s["context"] == context:
                return s["state"]
        return ""

    def dispatch(self, task: str, item: str | int, ref: str, workflow: str = WORKFLOW) -> None:
        inputs = {"task": task, "item": str(item)} if workflow == WORKFLOW else {}
        self.call("POST", self._repo(f"/actions/workflows/{workflow}/dispatches"), {"ref": ref, "inputs": inputs})

    def branch_exists(self, name: str) -> bool:
        try:
            self.call("GET", self._repo(f"/branches/{name}"))
            return True
        except GitHubError as e:
            if e.status == 404:
                return False
            raise

    # ── Discussions, with issues when they are off ─────────────────────────────────────────────
    def post(self, category: str, title: str, body: str) -> str:
        """A post in a Discussions category; an issue labelled with the category if Discussions are
        off or the category doesn't exist. Returns its URL."""
        try:
            r = self.graphql("""query($o: String!, $n: String!) { repository(owner: $o, name: $n) {
                id discussionCategories(first: 50) { nodes { id name } } } }""", o=self.owner, n=self.name)
            repo = r["repository"]
            cat = next((c["id"] for c in repo["discussionCategories"]["nodes"] if c["name"].lower() == category.lower()), None)
            if cat:
                d = self.graphql("""mutation($r: ID!, $c: ID!, $t: String!, $b: String!) {
                    createDiscussion(input: {repositoryId: $r, categoryId: $c, title: $t, body: $b}) {
                    discussion { url } } }""", r=repo["id"], c=cat, t=title, b=body)
                return d["createDiscussion"]["discussion"]["url"]
        except GitHubError:
            pass
        return self.create_issue(title, body, [category.lower(), "keeper"])["html_url"]
