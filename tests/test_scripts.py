"""The repository's scripts: latest_versions reads every pin in the default sandbox's Dockerfile."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from latest_versions import AS_OF, BY_URL, DOCKERFILE, pins  # noqa: E402


def test_every_pin_in_the_default_dockerfile_is_read():
    found = {(index, package) for index, package, _ in pins(DOCKERFILE.read_text())}
    assert {("npm", "@anthropic-ai/claude-code"), ("npm", "@openai/codex"), ("npm", "bun"),
            ("pypi", "aider-chat"), ("pypi", "hermes-agent")} <= found
    assert all(version[0].isdigit() for _, _, version in pins(DOCKERFILE.read_text()))
    assert [name for name, _ in BY_URL.findall(DOCKERFILE.read_text())] == ["opensquilla"]
    assert AS_OF.search(DOCKERFILE.read_text())                                  # dependencies resolve as of a date


def test_pins_are_read_from_install_steps_only():
    text = "RUN npm install -g a@1.0 \\\n      @s/b@2.0\n# npm install -g c@3.0\nRUN echo d@4.0\nRUN pip install \"e[x]==5.0\"\n"
    assert pins(text) == [("npm", "a", "1.0"), ("npm", "@s/b", "2.0"), ("pypi", "e", "5.0")]
