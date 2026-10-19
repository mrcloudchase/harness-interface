"""Releasing: the version is written once, as the heading of CHANGELOG.md's newest section, so a
merge that adds a section releases it with its notes; everything reports that version."""
import re
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = re.findall(r"^## \[(.+?)\]", (ROOT / "CHANGELOG.md").read_text(), re.M)


def test_the_newest_section_is_a_semantic_version():
    assert SECTIONS and re.fullmatch(r"\d+\.\d+\.\d+", SECTIONS[0]), f"CHANGELOG.md opens with '## [{SECTIONS[0]}]'"


def test_the_package_and_the_server_report_it(client):
    assert version("harness-interface") == SECTIONS[0]
    assert client.get("/openapi.json").json()["info"]["version"] == SECTIONS[0]
