"""Releasing: the version is written once, in pyproject.toml, and has its notes in CHANGELOG.md, so
the release workflow can't fail after a merge for want of them; everything reports that version."""
import re
import tomllib
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_the_version_is_semantic():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)


def test_the_version_has_its_notes():
    sections = re.findall(r"^## \[(.+?)\]", (ROOT / "CHANGELOG.md").read_text(), re.M)
    assert VERSION in sections, f"CHANGELOG.md needs a '## [{VERSION}]' section"


def test_the_server_reports_the_installed_version(client):
    assert version("harness-interface") == VERSION
    assert client.get("/openapi.json").json()["info"]["version"] == VERSION
