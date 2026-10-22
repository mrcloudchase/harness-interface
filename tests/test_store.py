"""Layer 3: tenants, members and keys; providers sealed; packages by digest in blobs; limits set by
the deployer; workers and tokens; and one tenant never sees another's."""
import os

import pytest

from fakes import archive
from harness_interface.blobs import DirBlobs
from harness_interface.errors import Conflict, Invalid, NotFound
from harness_interface.records import SqliteRecords
from harness_interface.store import Store


@pytest.fixture
def store(tmp_path, vault):
    return Store(SqliteRecords(tmp_path / "r.db"), DirBlobs(tmp_path / "b", "http://api.test", b"s"), vault)


def test_tenants_members_keys(store):
    t = store.create_tenant("acme")
    assert store.tenant("acme") == t and [x.name for x in store.tenants()] == ["acme"] and t.ceilings.max_runs == 4
    with pytest.raises(Conflict):
        store.create_tenant("acme")
    with pytest.raises(Invalid):
        store.create_tenant("Bad Name")
    with pytest.raises(Invalid, match="limits"):
        store.create_tenant("x", {"cpus": -1})
    owner = store.create_member("acme", "chase", "owner")
    store.create_member("acme", "dev", "member")
    with pytest.raises(Invalid):
        store.create_member("acme", "x", "god")
    with pytest.raises(NotFound):
        store.create_member("other", "x", "member")
    key, secret = store.mint_key("acme", "chase", "laptop")
    assert secret.startswith("hi_") and store.resolve_key(secret) == owner
    assert store.resolve_key("hi_nope") is None and store.resolve_key("") is None
    assert [k.id for k in store.keys("acme")] == [key.id]
    store.update_tenant("acme", status="suspended")
    assert store.resolve_key(secret) is None               # a suspended tenant's keys do not log in
    store.update_tenant("acme", status="active", limits={"max_runs": 9})
    assert store.resolve_key(secret) == owner and store.tenant("acme").ceilings.max_runs == 9
    store.revoke_key("acme", key.id)
    assert store.resolve_key(secret) is None
    with pytest.raises(NotFound):
        store.revoke_key("acme", "zzz")


def test_providers_are_sealed_and_public(store, vault):
    store.create_tenant("acme")
    p = store.put_provider("acme", "anthropic", "https://api.anthropic.com/", "anthropic-messages", "sk-real")
    assert p.url == "https://api.anthropic.com" and p.path == "" and "sk-real" not in p.key and "key" not in p.public()
    assert store.open_key(p) == "sk-real"
    assert store.put_provider("acme", "ds", "https://api.deepseek.com/anthropic", "anthropic-messages", "k").path == "/anthropic"
    own = store.put_provider("acme", "mine", "https://proxy.acme.example", "none", "")
    assert store.open_key(own) == ""
    for args, says in [(("https://x.example", "bogus", "k"), "api is one of"), (("http://x.example", "openai-chat", "k"), "https://"),
                       (("https://x.example", "openai-chat", ""), "has a key"), (("https://x.example", "none", "k"), "has a key"),
                       (("https://x.example", "openai-chat", "two\nlines"), "one line"),
                       (("https://10.0.0.1", "openai-chat", "k"), "public"), (("https://localhost", "openai-chat", "k"), "host name")]:
        with pytest.raises(Invalid, match=says):
            store.put_provider("acme", "p", *args)
    store.delete_provider("acme", "anthropic")
    with pytest.raises(NotFound):
        store.provider("acme", "anthropic")


def test_harness_versions_in_blobs(store):
    store.create_tenant("acme")
    h1 = store.put_harness("acme", "cc", archive())
    assert store.harness("acme", "cc").current == h1.current and h1.config().model == "m1"
    assert store.blobs.exists(store.harness_blob("acme", "cc", h1.current))
    h2 = store.put_harness("acme", "cc", archive(description="v2"))
    assert h2.current != h1.current and set(h2.versions) == {h1.current, h2.current}
    assert h2.config(h1.current).description == "a test harness"   # an older version stays runnable
    assert store.put_harness("acme", "cc", archive()).current == h1.current   # the same bytes are the same version
    assert store.harness("acme", "cc").public()["versions"][0] == h1.current
    with pytest.raises(Invalid, match="request.sh is missing"):
        store.put_harness("acme", "bad", archive({"request.sh": None}))
    with pytest.raises(Invalid, match="egress"):
        store.put_harness("acme", "bad", archive(run='{"egress": ["169.254.169.254"]}'))
    store.update_tenant("acme", limits={"upload_mb": 1})
    with pytest.raises(Invalid, match="upload limit"):
        store.put_harness("acme", "big", archive({"blob.bin": os.urandom(2 * 1024 * 1024)}))
    store.delete_harness("acme", "cc")
    assert store.harnesses("acme") == [] and store.blobs.list("tenants/acme/harnesses") == []


def test_workers_tokens_deployer(store):
    store.create_tenant("acme")
    w, secret = store.register_worker("node-1", slots=4, version="4.0.0")
    assert store.worker_by_secret(secret).id == w.id and store.worker_by_secret("hw_nope") is None
    store.touch_worker(w, running=2)
    assert store.workers()[0].running == 2
    store.forget_worker(w.id)
    assert store.workers() == []
    tok = store.issue_token("acme", "prov", "resp_1", "openai-chat", ttl_s=60)
    assert tok.startswith("sk-hi-") and store.resolve_token(tok)["provider"] == "prov"
    assert store.issue_token("acme", "p", "r", "anthropic-messages", 60).startswith("sk-ant-api03-hi-")
    assert store.resolve_token(store.issue_token("acme", "p", "r", "openai-chat", ttl_s=-1)) is None
    store.revoke_token(tok)
    assert store.resolve_token(tok) is None
    dk = store.set_deployer_key()
    assert dk.startswith("hd_") and store.is_deployer(dk) and not store.is_deployer("hd_other")


def test_tenants_are_separate_and_deletable(store):
    store.create_tenant("a")
    store.create_tenant("b")
    store.create_member("a", "m", "owner")
    _, secret = store.mint_key("a", "m")
    store.put_provider("a", "p", "https://x.example", "openai-chat", "k")
    store.put_harness("a", "h", archive())
    with pytest.raises(NotFound):
        store.provider("b", "p")
    with pytest.raises(NotFound):
        store.harness("b", "h")
    assert store.harnesses("b") == [] and store.providers("b") == []
    store.delete_tenant("a")
    assert [t.name for t in store.tenants()] == ["b"] and store.resolve_key(secret) is None
    assert store.blobs.list("tenants/a") == []
