"""Routers decide which harness runs a request that names none. One interface, pluggable engines."""
from __future__ import annotations

from ..models import Route
from ..storage import SecretStore
from .base import Router
from .jev import JevClient, JevRouter
from .static import StaticRouter


def make_router(route: Route, secrets: SecretStore, jev_base_url: str, jev_secret_name: str) -> Router:
    if route.engine == "static":
        return StaticRouter(route.default)
    key = secrets.get(jev_secret_name)
    if not key:
        raise LookupError(f"route engine 'jev' needs secret '{jev_secret_name}'")
    return JevRouter(route, JevClient(jev_base_url, key))


__all__ = ["Router", "StaticRouter", "JevRouter", "JevClient", "make_router"]
