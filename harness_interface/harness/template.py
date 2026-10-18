"""Layer 3: `{name}` placeholders over a context of strings, the one templating mechanism, for a
harness's argv, env and files. Only `{identifier}` is a placeholder, so other braces, in JSON or
code, pass through."""
from __future__ import annotations

import re
from typing import Any

from ..errors import Invalid

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render(template: str, ctx: dict[str, str]) -> str:
    def value(m: re.Match) -> str:
        if m.group(1) not in ctx:
            raise Invalid(f"unknown placeholder {m.group(0)}")
        return ctx[m.group(1)]
    return _PLACEHOLDER.sub(value, template)


def render_all(obj: Any, ctx: dict[str, str]) -> Any:
    """Every string in a list, or in a dict's values, rendered; anything else as it is."""
    if isinstance(obj, str):
        return render(obj, ctx)
    if isinstance(obj, (list, tuple)):
        return [render_all(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: render_all(v, ctx) for k, v in obj.items()}
    return obj
