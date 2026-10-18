"""The harness-interface API as Python calls: one method per endpoint, and the response stream.
Nothing here knows more than the HTTP surface does."""
from __future__ import annotations

import json
import os
from typing import Any, Iterator

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


class Api:
    def __init__(self, url: str | None = None):
        self.url = (url or os.environ.get("HI_URL") or DEFAULT_URL).rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=httpx.Timeout(30, read=None))

    def _send(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            r = self.http.request(method, path, **kw)
        except httpx.ConnectError:
            raise ApiError(0, f"no server at {self.url}; start one with `hi server start`") from None
        if r.status_code >= 400:
            raise ApiError(r.status_code, _detail(r))
        return r

    # the three resources share one shape: PUT, GET (one or all), DELETE
    def put(self, kind: str, name: str, body: dict) -> dict:
        return self._send("PUT", f"/{kind}/{name}", json=body).json()

    def get(self, kind: str, name: str | None = None) -> Any:
        return self._send("GET", f"/{kind}/{name}" if name else f"/{kind}").json()

    def delete(self, kind: str, name: str) -> bool:
        return self._send("DELETE", f"/{kind}/{name}").json()["deleted"]

    # responses
    def respond(self, body: dict) -> Iterator[tuple[str, dict]]:
        """POST /responses, streamed: (event, data) for each server-sent event as it arrives."""
        try:
            with self.http.stream("POST", "/responses", json={**body, "stream": True}) as r:
                if r.status_code >= 400:
                    r.read()
                    raise ApiError(r.status_code, _detail(r))
                event = None
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: ") and event:
                        yield event, json.loads(line[6:])
                        event = None
        except httpx.ConnectError:
            raise ApiError(0, f"no server at {self.url}; start one with `hi server start`") from None

    def responses(self) -> list[dict]:
        return self._send("GET", "/responses").json()

    def response(self, response_id: str) -> dict:
        return self._send("GET", f"/responses/{response_id}").json()

    def cancel(self, response_id: str) -> bool:
        return self._send("POST", f"/responses/{response_id}/cancel").json()["cancelled"]

    def output(self, response_id: str) -> bytes:
        return self._send("GET", f"/responses/{response_id}/output").content

    def log(self, response_id: str) -> bytes:
        return self._send("GET", f"/responses/{response_id}/log").content

    def file(self, response_id: str, path: str) -> bytes:
        return self._send("GET", f"/responses/{response_id}/files/{path}").content


def _detail(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail")
    except ValueError:
        return r.text or f"HTTP {r.status_code}"
    return detail if isinstance(detail, str) else json.dumps(detail)
