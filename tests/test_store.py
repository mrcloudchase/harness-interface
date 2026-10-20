"""Layer 4: what the server keeps. A record is one JSON file, written whole or not at all, and a private
store is readable by its owner only, from the first byte. A provider is a name, a URL its shape's SDK
takes and a key that is never shown; a harness is a folder sent as a map of files, stored only when
it loads, installed in the background, and installed again when it is replaced."""
import asyncio
import base64
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness_interface.errors import Invalid, NotFound
from harness_interface.harness.install import Installer
from harness_interface.harness.placement import Placement
from harness_interface.store import JsonStore, ProviderEntry, Registry, folder_map
from standin import OFFLINE_INSTALL, TEMPLATE

KEY = "sk-store-test-key-" + os.urandom(6).hex()


@dataclass
class Item:
    name: str
    n: int = 0


def test_a_record_is_written_whole_and_read_back(tmp_path):
    store = JsonStore(tmp_path / "items", lambda d: Item(**d))
    store.put("a", Item("a", 1))
    store.put("b", Item("b", 2))
    store.put("a", Item("a", 3))
    assert store.get("a") == Item("a", 3) and store.get("nope") is None
    assert [i.name for i in store.list()] == ["a", "b"]
    assert not list((tmp_path / "items").glob(".*"))                     # no half-written file is left
    assert store.delete("a") and not store.delete("a") and store.get("a") is None


def test_a_private_store_is_its_owners_alone_from_the_first_byte(tmp_path, monkeypatch):
    modes = []
    real = os.open

    def watch(path, flags, mode=0o777, *a, **kw):
        fd = real(path, flags, mode, *a, **kw)
        modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return fd
    store = JsonStore(tmp_path / "keys", lambda d: Item(**d), private=True)
    monkeypatch.setattr(os, "open", watch)
    store.put("a", Item("a"))
    monkeypatch.undo()
    assert modes and all(m == 0o600 for m in modes)
    assert stat.S_IMODE((tmp_path / "keys").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "keys" / "a.json").stat().st_mode) == 0o600


def test_a_key_that_could_name_another_file_is_refused(tmp_path):
    store = JsonStore(tmp_path / "items", lambda d: Item(**d))
    for key in ("", "../x", "a/b", ".hidden"):
        with pytest.raises(AssertionError):
            store.put(key, Item("x"))


# providers
@pytest.fixture
def registry(tmp_path):
    return Registry(tmp_path / "data", Installer(tmp_path / "data" / "tools", Placement()))


def test_a_provider_is_kept_privately_and_its_key_is_never_shown(registry, tmp_path):
    entry = registry.put_provider(ProviderEntry("deepseek", "https://api.deepseek.com/anthropic", "anthropic-messages",
                                                KEY))
    assert entry.public() == {"name": "deepseek", "url": "https://api.deepseek.com/anthropic",
                              "api": "anthropic-messages"}
    assert KEY not in repr(entry) and KEY not in json.dumps([p.public() for p in registry.providers()])
    assert registry.provider("deepseek").key == KEY
    stored = tmp_path / "data" / "providers" / "deepseek.json"
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    registry.delete_provider("deepseek")
    with pytest.raises(NotFound):
        registry.provider("deepseek")
    with pytest.raises(NotFound):
        registry.delete_provider("deepseek")


@pytest.mark.parametrize("url, api, key, name", [
    ("https://api.anthropic.com/v1", "anthropic-messages", KEY, "a"),        # the SDK adds /v1
    ("https://api.openai.com", "openai-responses", KEY, "a"),                # the SDK wants /v1
    ("http://api.openai.com/v1", "openai-chat", KEY, "a"),
    ("https://api.openai.com/v1", "openai-telepathy", KEY, "a"),
    ("https://api.openai.com/v1", "openai-chat", "", "a"),
    ("https://api.openai.com/v1", "openai-chat", "two\nlines", "a"),
    ("https://api.openai.com/v1", "openai-chat", KEY, "Not_A_Name"),
])
def test_a_provider_the_server_would_have_to_guess_about_is_refused(url, api, key, name):
    with pytest.raises(Invalid):
        ProviderEntry(name, url, api, key)


# harnesses
def template_map(change=None, **files) -> dict:
    """The template as a PUT body sends it, its install made offline."""
    body = folder_map(TEMPLATE)
    body["install.sh"] = OFFLINE_INSTALL
    spec = json.loads(body["harness.json"])
    if change:
        change(spec)
    body["harness.json"] = json.dumps(spec)
    return {**body, **files}


def test_a_folder_map_is_every_file_text_or_base64(tmp_path):
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "a.txt").write_text("text")
    (tmp_path / "blob").write_bytes(b"\xff\x00")
    assert folder_map(tmp_path) == {"blob": {"base64": base64.b64encode(b"\xff\x00").decode()}, "home/a.txt": "text"}


def test_a_harness_is_stored_as_its_folder_and_installed_in_the_background(registry, tmp_path):
    async def go():
        put = await registry.put_harness("template", template_map(**{"home/x.bin": {"base64": "AAE="}}))
        state = registry.install("template").state
        folder, installed = await registry.ready("template")
        return put, state, folder, installed
    put, state, folder, installed = asyncio.run(go())
    assert put.name == "template" and state == "installing"
    assert folder.path == tmp_path / "data" / "harnesses" / "template"
    assert (folder.path / "home" / "x.bin").read_bytes() == b"\x00\x01"
    assert (installed.path / "bin" / "standin").is_file()
    assert [f.name for f in registry.harnesses()] == ["template"]


def test_an_install_that_fails_is_failed_with_its_log(registry):
    async def go():
        await registry.put_harness("template", template_map(**{"install.sh": "echo no network here; exit 7\n"}))
        with pytest.raises(Invalid, match="failed to install"):
            await registry.ready("template")
        return registry.install("template")
    state = asyncio.run(go())
    assert state.state == "failed" and "no network here" in state.log and "exited 7" in state.error


def test_replacing_a_harness_installs_it_again(registry):
    async def go():
        await registry.put_harness("template", template_map())
        first = (await registry.ready("template"))[1]
        await registry.put_harness("template", template_map(**{"install.sh": OFFLINE_INSTALL + "echo v2\n"}))
        second = (await registry.ready("template"))[1]
        return first, second
    first, second = asyncio.run(go())
    assert first.path != second.path and second.path.is_dir()


def test_a_harness_that_doesnt_load_is_never_stored(registry, tmp_path):
    async def put(name, body):
        with pytest.raises(Invalid):
            await registry.put_harness(name, body)
    asyncio.run(put("template", template_map(lambda s: s.update(contract=2))))
    asyncio.run(put("other", template_map()))                            # harness.json names "template"
    asyncio.run(put("template", {**template_map(), "../escape": "x"}))
    asyncio.run(put("template", {**template_map(), "/abs": "x"}))
    asyncio.run(put("template", {**template_map(), "a.bin": {"base64": "not base64!"}}))
    asyncio.run(put("template", {**template_map(), "a.bin": {"hex": "00"}}))
    asyncio.run(put("Bad_Name", template_map()))
    assert registry.harnesses() == [] and not any(Path(tmp_path / "data" / "harnesses").glob("*"))


def test_a_stored_harness_can_be_deleted(registry):
    async def go():
        await registry.put_harness("template", template_map())
        await registry.ready("template")
        registry.delete_harness("template")
        with pytest.raises(NotFound):
            registry.harness("template")
        with pytest.raises(NotFound):
            registry.delete_harness("template")
    asyncio.run(go())


def test_after_a_restart_a_stored_harness_installs_when_it_is_asked_for(registry, tmp_path):
    async def put():
        await registry.put_harness("template", template_map())
        await registry.close()                       # a server stopping: its install is cut off
    asyncio.run(put())
    again = Registry(tmp_path / "data", Installer(tmp_path / "data" / "tools", Placement()))

    async def go():
        folder, installed = await again.ready("template")
        return again.install("template").state, installed
    state, installed = asyncio.run(go())
    assert state == "ready" and installed.path.is_dir()
