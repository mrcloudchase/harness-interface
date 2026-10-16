"""The `decide` table: ordered rules over flattened answers. No eval; one comparison per rule."""
from __future__ import annotations

import re
from typing import Any

from ..models import Rule
from ..template import TemplateError, lookup

_WHEN = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")
_OPS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def _value(raw: str) -> Any:
    raw = raw.strip().strip("'\"")
    try:
        return float(raw)
    except ValueError:
        return raw


def holds(when: str | None, answers: dict[str, Any]) -> bool:
    if not when:
        return True
    m = _WHEN.match(when)
    if not m:
        raise ValueError(f"bad rule: {when!r}")
    path, op, raw = m.groups()
    try:
        left = lookup(path, answers)
    except TemplateError:
        return False
    if left is None:
        return False
    return _OPS[op](left, _value(raw))


def decide(rules: list[Rule], answers: dict[str, Any], default: str) -> tuple[str, str]:
    """-> (target, reason). target is a harness name or 'reject:<message>'."""
    for rule in rules:
        if not holds(rule.when, answers):
            continue
        verb, _, rest = rule.then.strip().partition(" ")
        if verb == "reject":
            return f"reject:{rest or 'rejected by route'}", rule.then
        if verb == "use":
            target = rest.strip()
            if target == "default":
                return default, rule.then
            if "." in target:
                return str(lookup(target, answers)), rule.then
            return target, rule.then
        raise ValueError(f"bad rule action: {rule.then!r}")
    return default, "default"
