"""What every agent is told: its role's prompt, then the project's AGENTS.md and VISION.md. A
harness writes these instructions where its CLI reads them, so no prompt repeats the project's."""
from __future__ import annotations

from pathlib import Path

RESULT = ("When you are done, write your structured result to keeper.json in the working directory, "
          "exactly in the shape your role asks for.")


def prompt(root: Path, role: str) -> str:
    """The role's prompt: `.keeper/prompts/checker-security.md`, else `checker.md`."""
    folder = Path(root) / ".keeper" / "prompts"
    for name in (role, role.split("-")[0]):
        p = folder / f"{name}.md"
        if p.is_file():
            return p.read_text().strip()
    raise FileNotFoundError(f"no prompt for role {role!r} in {folder}")


def instructions(root: Path, role: str) -> str:
    root = Path(root)
    parts = [prompt(root, role)]
    for name in ("AGENTS.md", "VISION.md"):
        if (root / name).is_file():
            parts.append(f"# The project's {name}\n\n{(root / name).read_text().strip()}")
    return "\n\n---\n\n".join(parts)
