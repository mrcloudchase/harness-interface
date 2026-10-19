"""The pinned versions in the default sandbox's Dockerfile, beside the latest release of each, from
npm and PyPI. Keeper's Upgrade loop is given this, because its agent's sandbox can reach only its
model provider, not a package index.

    python scripts/latest_versions.py              every pin, and whether it is current
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "harness_interface" / "resources" / "default.Dockerfile"
NPM = re.compile(r"(?<![\w/.-])((?:@[\w.-]+/)?[\w.-]+)@(\d[\w.+-]*)")      # name@1.2.3, @scope/name@1.2.3
PYPI = re.compile(r'"([\w.-]+)(?:\[[\w,]+\])?==([\w.+-]+)"')               # "name==1.2.3", "name[extra]==1.2.3"
BY_URL = re.compile(r'"([\w.-]+)(?:\[[\w,]+\])? @ (https://[^"]+)"')        # "name @ https://…/name-1.2.3.whl"


def pins(dockerfile: str) -> list[tuple[str, str, str]]:
    """(index, package, pinned version) for every pin, in the order the Dockerfile has them."""
    steps = re.sub(r"\\\n", " ", re.sub(r"(?m)^#.*\n", "", dockerfile)).splitlines()   # one line per instruction
    npm = [("npm", name, version) for step in steps if "npm install" in step for name, version in NPM.findall(step)]
    return npm + [("pypi", name, version) for name, version in PYPI.findall(dockerfile)]


def latest(index: str, package: str) -> str:
    url = (f"https://registry.npmjs.org/{package.replace('/', '%2F')}/latest" if index == "npm"
           else f"https://pypi.org/pypi/{package}/json")
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    return data["version"] if index == "npm" else data["info"]["version"]


def main() -> int:
    dockerfile, rows = DOCKERFILE.read_text(), []
    for index, package, pinned in pins(dockerfile):
        try:
            newest = latest(index, package)
        except OSError as e:
            newest = f"unknown ({e})"
        rows.append(f"{index}  {package:<36} pinned {pinned:<16} latest {newest}"
                    + ("" if newest == pinned else "   ← behind"))
    print("\n".join(rows))
    for package, url in BY_URL.findall(dockerfile):
        print(f"url  {package:<36} pinned by {url}: check its releases by hand")
    print("\nCLIs installed by their vendors' own scripts (curl … | bash) take the latest at build time; nothing pins them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
