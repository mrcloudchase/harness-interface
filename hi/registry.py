"""Harness and route resources: validate, probe, version, store, list."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .models import Harness, HarnessSpec, Route, RouteSpec
from .storage import JsonStore

ROUTE_KEY = "route"


class Registry:
    def __init__(self, harnesses: JsonStore[Harness], routes: JsonStore[Route], check_timeout_s: int = 60):
        self.harnesses, self.routes, self.check_timeout_s = harnesses, routes, check_timeout_s

    # harnesses
    def apply(self, spec: HarnessSpec) -> Harness:
        prior = self.harnesses.get(spec.name)
        h = Harness(**spec.model_dump(), version=(prior.version + 1) if prior else 1)
        if spec.check:
            h.check_ok, h.check_output = self._probe(spec.check, spec.dir)
        return self.harnesses.put(h.name, h)

    def get(self, name: str) -> Harness | None:
        return self.harnesses.get(name)

    def list(self) -> list[Harness]:
        return self.harnesses.list()

    def delete(self, name: str) -> bool:
        return self.harnesses.delete(name)

    def cards(self) -> list[dict]:
        return [h.card() for h in self.list()]

    def _probe(self, argv: list[str], cwd: str | None) -> tuple[bool, str]:
        try:
            done = subprocess.run(argv, cwd=cwd or None, capture_output=True, text=True,
                                  timeout=self.check_timeout_s)
            return done.returncode == 0, (done.stdout + done.stderr).strip()[-2000:]
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)

    # route
    def apply_route(self, spec: RouteSpec) -> Route:
        if spec.default and not self.get(spec.default):
            raise LookupError(f"route default '{spec.default}' is not a registered harness")
        prior = self.routes.get(ROUTE_KEY)
        r = Route(**spec.model_dump(), version=(prior.version + 1) if prior else 1)
        return self.routes.put(ROUTE_KEY, r)

    def route(self) -> Route | None:
        return self.routes.get(ROUTE_KEY)


def load_spec(path: Path) -> HarnessSpec | RouteSpec:
    """A YAML file on disk. A harness remembers its directory so {harness_dir} resolves."""
    import yaml
    doc = yaml.safe_load(path.read_text())
    kind = doc.get("kind")
    if kind == "Harness":
        return HarnessSpec(**{**doc, "dir": str(path.parent.resolve())})
    if kind == "Route":
        return RouteSpec(**doc)
    raise ValueError(f"{path}: unknown kind {kind!r} (Harness or Route)")
