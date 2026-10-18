"""`{name}` placeholders over a context of strings: the one templating mechanism, for a harness's
argv, env and files. Only `{identifier}` is a placeholder, so other braces pass through."""
from __future__ import annotations

import re
from typing import Any

from .errors import ClientError

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class TemplateError(ClientError):
    pass


def render(template: str, ctx: dict[str, str]) -> str:
    def value(m: re.Match) -> str:
        if m.group(1) not in ctx:
            raise TemplateError(f"unknown placeholder {m.group(0)}")
        return ctx[m.group(1)]
    return _PLACEHOLDER.sub(value, template)


def render_obj(obj: Any, ctx: dict[str, str]) -> Any:
    """Render every string in a list or dict's values; anything else is returned as it is."""
    if isinstance(obj, str):
        return render(obj, ctx)
    if isinstance(obj, list):
        return [render_obj(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: render_obj(v, ctx) for k, v in obj.items()}
    return obj
