"""A harness folder as the body its PUT takes: harness.json, plus every other file in the folder
as a script. And the folders that ship with the CLI."""
from __future__ import annotations

import json
from pathlib import Path

# Installed, the shipped folders are package data; from a checkout, they are the repo's harnesses/.
_PACKAGED = Path(__file__).with_name("harnesses")
BUILTIN = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[3] / "harnesses"


def pack(folder: Path) -> dict:
    spec_file = folder / "harness.json"
    if not spec_file.is_file():
        raise ValueError(f"{folder} has no harness.json")
    spec = json.loads(spec_file.read_text())
    spec["scripts"] = {p.name: p.read_text() for p in sorted(folder.iterdir())
                       if p.is_file() and p.name != "harness.json"}
    return spec


def builtin(names: list[str]) -> list[Path]:
    """The shipped harness folders by name; every one when no names are given."""
    available = {p.name: p for p in sorted(BUILTIN.iterdir()) if (p / "harness.json").is_file()}
    unknown = [n for n in names if n not in available]
    if unknown:
        raise ValueError(f"no built-in harness {', '.join(unknown)}; there are: {', '.join(available)}")
    return [available[n] for n in names] if names else list(available.values())
