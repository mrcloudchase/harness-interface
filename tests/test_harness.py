"""Layer 2: a folder is contract 3 or it is refused by name; an archive is unpacked safely; a digest
names a version; seeds copy as they should."""
import io
import json
import tarfile

import pytest

from fakes import HARNESS_JSON, archive
from harness_interface.errors import Invalid
from harness_interface.harness import Config, copy_seed, digest, load_config, unpack, validate


def test_config_defaults_and_values():
    c = load_config(json.dumps({"contract": 3}))
    assert c == Config()
    c = load_config(json.dumps(HARNESS_JSON))
    assert (c.sandbox, c.provider, c.model, c.key_env, c.url_env) == ("box", "prov", "m1", "FAKE_KEY", "FAKE_URL")
    assert c.install_egress == ("registry.example",) and c.timeout_s == 60 and c.stop_timeout_s == 2
    assert c.as_json()["defaults"] == {"sandbox": "box", "provider": "prov", "model": "m1"}


@pytest.mark.parametrize("bad, says", [
    ("not json", "not JSON"), ('{"contract": 1}', '"contract": 3'), ('{"contract": 3, "extra": 1}', "unknown keys"),
    ('{"contract": 3, "defaults": {"x": 1}}', "defaults is an object"),
    ('{"contract": 3, "interrupt": "SIGKILL"}', "interrupt is one of"),
    ('{"contract": 3, "run": {"timeout_s": -1}}', "positive number"),
    ('{"contract": 3, "provider_env": {"key": "has space"}}', "environment variable names"),
    ('{"contract": 3, "install": {"egress": "host"}}', "list of hosts"),
])
def test_config_refusals(bad, says):
    with pytest.raises(Invalid, match=says):
        load_config(bad)


def test_unpack_validate_and_digest(tmp_path):
    unpack(archive(), tmp_path / "a")
    config = validate(tmp_path / "a")
    assert config.model == "m1" and (tmp_path / "a" / "request.sh").stat().st_mode & 0o100
    unpack(archive(root="my-harness"), tmp_path / "b")   # one wrapping directory is stripped
    assert (tmp_path / "b" / "harness.json").is_file()
    assert digest(tmp_path / "a") == digest(tmp_path / "b")
    unpack(archive(description="other"), tmp_path / "c")
    assert digest(tmp_path / "c") != digest(tmp_path / "a")


@pytest.mark.parametrize("files, says", [
    ({"request.sh": None}, "request.sh is missing"), ({"install.sh": None}, "install.sh is missing"),
    ({"request.sh": "if then fi"}, "not valid bash"), ({"seeds/global/x": "y"}, "seeds holds only"),
])
def test_validate_refusals(tmp_path, files, says):
    unpack(archive(files), tmp_path / "a")
    with pytest.raises(Invalid, match=says):
        validate(tmp_path / "a")


def test_unpack_refuses_escapes_and_links(tmp_path):
    with pytest.raises(Invalid, match="tar archive"):
        unpack(b"not a tar", tmp_path / "x")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("../escape")
        info.size = 0
        tar.addfile(info, io.BytesIO(b""))
    with pytest.raises(Invalid, match="outside"):
        unpack(buf.getvalue(), tmp_path / "y")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(Invalid, match="not a file or directory"):
        unpack(buf.getvalue(), tmp_path / "z")


def test_copy_seed(tmp_path):
    src = tmp_path / "src"
    (src / "d").mkdir(parents=True)
    (src / "d" / "f").write_text("new")
    dest = tmp_path / "dest"
    (dest / "d").mkdir(parents=True)
    (dest / "d" / "f").write_text("old")
    copy_seed(src, dest, overwrite=False)
    assert (dest / "d" / "f").read_text() == "old"
    copy_seed(src, dest, overwrite=True)
    assert (dest / "d" / "f").read_text() == "new"
