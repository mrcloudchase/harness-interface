"""Routers decide which harness runs a request that names none. One interface, pluggable engines."""
from __future__ import annotations

from ..models import Route
from ..storage import SecretStore
from .base import Router
from .jev import JevClient, JevJudge, JevRouter
from .static import StaticRouter


def make_router(route: Route, secrets: SecretStore, jev_base_url: str, jev_secret_name: str) -> Router:
    if route.engine == "static":
        return StaticRouter(route.default)
    key = secrets.get(jev_secret_name)
    if not key:
        raise LookupError(f"route engine 'jev' needs secret '{jev_secret_name}'")
    return JevRouter(route, JevClient(jev_base_url, key))


def make_judge(route: Route, secrets: SecretStore, jev_base_url: str, jev_secret_name: str) -> JevJudge | None:
    """None when the route has no judge or the key is missing: a run then simply has no verdict."""
    key = secrets.get(jev_secret_name)
    if not route.judge or not key:
        return None
    return JevJudge(route.judge, JevClient(jev_base_url, key))


__all__ = ["Router", "StaticRouter", "JevRouter", "JevJudge", "JevClient", "make_router", "make_judge"]
