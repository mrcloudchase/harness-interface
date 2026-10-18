"""Layer 4: names follow the rule, keys are stored privately, writes are whole, `default` is
reserved, and resolving a harness names whatever it is missing."""
import stat

import pytest

from harness_interface.errors import Invalid, NotFound
from harness_interface.harness import Harness, Provider
from harness_interface.resources import DEFAULT_SANDBOX, Registry
from harness_interface.runtimes import Sandbox

KEY = "sk-very-secret"


@pytest.fixture
def reg(tmp_path):
    return Registry(tmp_path / "data")


def test_names_follow_the_rule(reg):
    for bad in ("Upper", "-dash", "has_underscore", "", "a/b"):
        with pytest.raises(Invalid):
            reg.put("providers", Provider(bad, "https://x", KEY))
    reg.put("providers", Provider("ok-1", "https://x", KEY))
    with pytest.raises(NotFound):
        reg.get("providers", "../ok-1")


def test_keys_are_stored_for_their_owner_only(reg, tmp_path):
    reg.put("providers", Provider("anthropic", "https://api.anthropic.com", KEY))
    root = tmp_path / "data" / "providers"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "anthropic.json").stat().st_mode) == 0o600
    assert reg.get("providers", "anthropic").key == KEY


def test_writes_are_whole_and_listings_sorted(reg, tmp_path):
    for name in ("zeta", "alpha"):
        reg.put("providers", Provider(name, "https://x", KEY))
    assert [p.name for p in reg.list("providers")] == ["alpha", "zeta"]
    assert not list((tmp_path / "data" / "providers").glob(".*.tmp"))
    assert reg.delete("providers", "zeta") and not reg.delete("providers", "zeta")


def test_default_is_built_in_and_reserved(reg):
    assert reg.list("sandboxes") == [DEFAULT_SANDBOX] and reg.get("sandboxes", "default") == DEFAULT_SANDBOX
    with pytest.raises(Invalid):
        reg.put("sandboxes", Sandbox("default", "FROM x"))
    with pytest.raises(Invalid):
        reg.delete("sandboxes", "default")
    reg.put("sandboxes", Sandbox("py", "FROM python:3.12", egress=("pypi.org",)))
    assert [s.name for s in reg.list("sandboxes")] == ["default", "py"]
    assert reg.get("sandboxes", "py").egress == ("pypi.org",)


def test_a_harness_and_its_scripts(reg):
    h = Harness("echo", "none", scripts={"run.sh": "echo hi\n", "report.py": "pass\n"})
    reg.put("harnesses", h)
    d = reg.scripts_of("echo")
    assert sorted(p.name for p in d.iterdir()) == ["report.py", "run.sh"]
    reg.put("harnesses", Harness("echo", "none", scripts={"run.sh": "echo v2\n"}))    # replaced, not merged
    assert [p.name for p in d.iterdir()] == ["run.sh"] and (d / "run.sh").read_text() == "echo v2\n"
    assert reg.get("harnesses", "echo").scripts == {"run.sh": "echo v2\n"}
    assert reg.delete("harnesses", "echo") and not d.exists()


def test_resolving_names_what_is_missing(reg):
    with pytest.raises(Invalid, match="no harness 'echo'"):
        reg.resolve("echo")
    reg.put("harnesses", Harness("echo", "none", sandbox="py"))
    with pytest.raises(Invalid, match="provider 'none'"):
        reg.resolve("echo")
    reg.put("providers", Provider("none", "https://x", KEY))
    with pytest.raises(Invalid, match="sandbox 'py'"):
        reg.resolve("echo")
    reg.put("sandboxes", Sandbox("py", "FROM python:3.12"))
    r = reg.resolve("echo")
    assert (r.harness.name, r.provider.key, r.sandbox.name, r.scripts) == ("echo", KEY, "py", reg.scripts_of("echo"))
