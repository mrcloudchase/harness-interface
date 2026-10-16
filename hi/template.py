"""`{a.b.c}` placeholders over a context dict. The one templating mechanism, used for argv, env,
files and route state. Lists and dicts render as JSON; None renders as empty."""
from __future__ import annotations

import json
import re
from typing import Any

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")


class TemplateError(KeyError):
    pass


def lookup(path: str, ctx: dict[str, Any]) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif hasattr(cur, part):
            cur = getattr(cur, part)
        else:
            raise TemplateError(path)
    return cur


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return str(v)


def render(template: str, ctx: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: _text(lookup(m.group(1), ctx)), template)


def render_obj(obj: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(obj, str):
        return render(obj, ctx)
    if isinstance(obj, list):
        return [render_obj(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: render_obj(v, ctx) for k, v in obj.items()}
    return obj
