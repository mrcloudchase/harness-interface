"""Routers decide which harness runs a request in `route` mode; the judge labels every run; the
referee settles a fan-out contest. One interface each, Jev behind all three."""
from __future__ import annotations

from ..models import Route
from ..storage import SecretStore
from .base import Router
from .jev import JevClient, JevJudge, JevReferee, JevRouter
from .static import StaticRouter


def make_router(route: Route, secrets: SecretStore, jev_base_url: str, jev_secret_name: str) -> Router:
    if route.engine == "static":
        return StaticRouter(route.default)
    return JevRouter(route, _client(secrets, jev_base_url, jev_secret_name, "route engine 'jev'"))


def make_judge(route: Route | None, secrets: SecretStore, jev_base_url: str, jev_secret_name: str) -> JevJudge | None:
    """None when there is no route, no judge on it, or no key: a run then simply has no verdict."""
    if not route or not route.judge or not secrets.get(jev_secret_name):
        return None
    return JevJudge(route.judge, _client(secrets, jev_base_url, jev_secret_name, "the judge"))


def make_referee(route: Route | None, secrets: SecretStore, jev_base_url: str, jev_secret_name: str) -> JevReferee:
    """A contest needs the judge, to know what was delivered, and the key, to pick among it."""
    if not route or not route.judge:
        raise LookupError("fan-out needs a Route with a judge (PUT /route)")
    return JevReferee(route.arena, _client(secrets, jev_base_url, jev_secret_name, "fan-out"))


def _client(secrets: SecretStore, base_url: str, secret_name: str, who: str) -> JevClient:
    key = secrets.get(secret_name)
    if not key:
        raise LookupError(f"{who} needs secret '{secret_name}'")
    return JevClient(base_url, key)


__all__ = ["Router", "StaticRouter", "JevRouter", "JevJudge", "JevReferee", "JevClient",
           "make_router", "make_judge", "make_referee"]
