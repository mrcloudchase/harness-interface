"""Layer 3: a harness folder loads only when it is exactly what contract 1 says: a closed harness.json,
the files a folder must have, a provider URL the shape's SDK takes, paths that stay inside, and the
very hi_adapter.py the server ships. Every problem is named at once."""
import json
import shutil
from pathlib import Path

import pytest

from harness_interface.errors import Invalid
from harness_interface.harness.folder import CANONICAL_ADAPTER, HarnessFolder, check_provider_url

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "harnesses" / "template"


def variant(tmp_path: Path, change=None, **files) -> Path:
    """A copy of the template with harness.json changed by `change` and `files` written (None deletes)."""
    d = tmp_path / "folder"
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(TEMPLATE, d)
    spec = json.loads((d / "harness.json").read_text())
    if change:
        change(spec)
    (d / "harness.json").write_text(json.dumps(spec))
    for name, content in files.items():
        name = name.replace("__", ".")
        if content is None:
            (shutil.rmtree if (d / name).is_dir() else Path.unlink)(d / name)
        else:
            (d / name).write_text(content)
    return d


def refused(tmp_path, change=None, **files) -> str:
    with pytest.raises(Invalid) as e:
        HarnessFolder.load(variant(tmp_path, change, **files))
    return str(e.value)


def test_the_template_loads_with_every_field():
    f = HarnessFolder.load(TEMPLATE)
    assert (f.name, f.contract, f.run.interrupt, f.run.credential, f.run.egress) == \
        ("template", 1, "steered", "gateway", ())
    assert f.provider.url == "https://api.anthropic.com" and f.provider.api in f.apis
    assert f.files == {".home/.standin/AGENTS.md": "{instructions}"} and f.report == (".standin/memory/**",)
    assert f.home == TEMPLATE / "home" and f.workspace == TEMPLATE / "workspace" and f.dockerfile is None
    assert f.install.egress == ("registry.npmjs.org",) and f.install_sh == (TEMPLATE / "install.sh").read_bytes()


def test_the_templates_hi_adapter_is_the_one_the_server_ships():
    assert (TEMPLATE / "hi_adapter.py").read_bytes() == CANONICAL_ADAPTER.read_bytes()


def test_every_folder_in_the_repository_loads():
    for path in (ROOT / "harnesses").glob("*/harness.json"):
        HarnessFolder.load(path.parent)


def test_optional_fields_take_their_defaults(tmp_path):
    def drop(spec):
        del spec["report"], spec["run"]["credential"], spec["run"]["egress"]
    f = HarnessFolder.load(variant(tmp_path, drop))
    assert (f.report, f.run.credential, f.run.egress) == ((), "gateway", ())


@pytest.mark.parametrize("change, says", [
    (lambda s: s.update(sandbox="default"), "unknown field sandbox"),
    (lambda s: s.pop("install"), "missing install"),
    (lambda s: s["run"].update(argv=["x"]), "unknown field run.argv"),
    (lambda s: s["run"].pop("stop_timeout_s"), "missing run.stop_timeout_s"),
    (lambda s: s["install"].update(env={}), "unknown field install.env"),
    (lambda s: s["provider"].update(key="sk"), "unknown field provider.key"),
    (lambda s: s.update(contract=2), "contract"),
    (lambda s: s.update(contract=True), "contract"),
    (lambda s: s.pop("contract"), "missing contract"),
    (lambda s: s.update(name="Claude Code"), "name"),
    (lambda s: s.update(description="two\nlines"), "description"),
    (lambda s: s.update(apis=["anthropic-messages", "gemini"]), "apis"),
    (lambda s: s.update(apis=[]), "apis"),
    (lambda s: s.update(apis=["openai-chat"]), "provider.api"),
    (lambda s: s["run"].update(interrupt="maybe"), "run.interrupt"),
    (lambda s: s["run"].update(credential="env"), "run.credential"),
    (lambda s: s["run"].update(timeout_s=0), "run.timeout_s"),
    (lambda s: s["run"].update(stop_timeout_s="15"), "run.stop_timeout_s"),
    (lambda s: s["run"].update(stdout="ndjson"), "run.stdout"),
    (lambda s: s["run"].update(egress=["https://example.com/path"]), "run.egress"),
    (lambda s: s["install"].update(timeout_s=-1), "install.timeout_s"),
    (lambda s: s["install"].update(egress="registry.npmjs.org"), "install.egress"),
    (lambda s: s.update(files={"../AGENTS.md": "{instructions}"}), "files"),
    (lambda s: s.update(files={"/etc/motd": "{instructions}"}), "files"),
    (lambda s: s.update(files={".git/config": "x"}), "files"),
    (lambda s: s.update(files={"AGENTS.md": 3}), "files"),
    (lambda s: s.update(report=["../../etc/**"]), "report"),
    (lambda s: s.update(report=["/root/**"]), "report"),
    (lambda s: s.update(report=".claude/**"), "report"),
])
def test_a_harness_json_that_isnt_contract_1_is_refused(tmp_path, change, says):
    assert says in refused(tmp_path, change)


def test_every_problem_is_named_at_once(tmp_path):
    def two(spec):
        spec["sandbox"] = "default"
        spec["run"]["interrupt"] = "maybe"
    message = refused(tmp_path, two)
    assert "unknown field sandbox" in message and "run.interrupt" in message


def test_harness_json_must_be_an_object_of_json(tmp_path):
    assert "harness.json" in refused(tmp_path, harness__json="{not json")
    assert "harness.json" in refused(tmp_path, harness__json="[]")


@pytest.mark.parametrize("missing", ["install.sh", "run.sh", "adapter.py", "hi_adapter.py", "harness.json"])
def test_a_folder_missing_a_file_is_refused(tmp_path, missing):
    assert missing in refused(tmp_path, **{missing.replace(".", "__"): None})


def test_a_drifted_hi_adapter_is_refused(tmp_path):
    drifted = (TEMPLATE / "hi_adapter.py").read_text() + "\n# a local fix\n"
    assert "hi_adapter.py differs" in refused(tmp_path, hi_adapter__py=drifted)


def test_home_and_workspace_are_optional_directories(tmp_path):
    f = HarnessFolder.load(variant(tmp_path, home=None, workspace=None))
    assert f.home is None and f.workspace is None
    (f.path / "home").write_text("a file, not a directory")
    with pytest.raises(Invalid, match="home"):
        HarnessFolder.load(f.path)


def test_a_link_in_home_or_workspace_is_refused(tmp_path):
    d = variant(tmp_path)
    (d / "home" / "link").symlink_to("/etc/passwd")
    with pytest.raises(Invalid, match="link"):
        HarnessFolder.load(d)


def test_an_image_dockerfile_must_build_from_the_base(tmp_path):
    good = "# OS packages\nFROM hi-base\nUSER root\nRUN apt-get update\nUSER 1000:1000\n"
    f = HarnessFolder.load(variant(tmp_path, image__Dockerfile=good))
    assert f.dockerfile == good
    for bad in ("FROM ubuntu:24.04\n", "RUN true\nFROM hi-base\n", ""):
        assert "image.Dockerfile" in refused(tmp_path, image__Dockerfile=bad)


@pytest.mark.parametrize("url, api", [
    ("https://api.anthropic.com", "anthropic-messages"), ("https://api.deepseek.com/anthropic", "anthropic-messages"),
    ("https://api.openai.com/v1", "openai-responses"), ("https://api.deepseek.com/v1", "openai-chat"),
    ("https://openrouter.ai/api/v1/", "openai-chat"), ("https://127.0.0.1:8443", "anthropic-messages"),
    ("https://generativelanguage.googleapis.com/v1beta/openai", "openai-chat")])
def test_the_provider_url_rule_takes_what_the_shapes_sdk_takes(url, api):
    check_provider_url(url, api)


@pytest.mark.parametrize("url, api", [
    ("https://api.anthropic.com/v1", "anthropic-messages"), ("https://api.openai.com", "openai-responses"),
    ("https://api.deepseek.com", "openai-chat"), ("http://api.openai.com/v1", "openai-chat"),
    ("https://user:sk-secret@api.openai.com/v1", "openai-chat"), ("https://api.openai.com/v1?key=x", "openai-chat"),
    ("https:///v1", "openai-chat"), ("api.openai.com/v1", "openai-chat"), ("https://api.openai.com/v1", "gemini")])
def test_the_provider_url_rule_refuses_what_an_adapter_would_have_to_guess_at(url, api):
    with pytest.raises(Invalid):
        check_provider_url(url, api)


def test_a_folder_default_provider_must_follow_the_rule(tmp_path):
    assert "provider.url" in refused(tmp_path, lambda s: s["provider"].update(url="https://api.anthropic.com/v1"))
