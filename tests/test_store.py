"""Layer 3: orgs, members and keys; providers sealed; sandboxes checked; harnesses by digest; and
one org never sees another's."""
import pytest

from fakes import archive
from harness_interface.errors import Conflict, Invalid, NotFound


def test_orgs_members_keys(store):
    org = store.create_org("acme")
    assert store.org("acme") == org and [o.name for o in store.orgs()] == ["acme"]
    with pytest.raises(Conflict):
        store.create_org("acme")
    with pytest.raises(Invalid):
        store.create_org("Bad Name")
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
    store.revoke_key("acme", key.id)
    assert store.resolve_key(secret) is None
    with pytest.raises(NotFound):
        store.revoke_key("acme", "zzz")


def test_providers_are_sealed(store, vault):
    store.create_org("acme")
    p = store.put_provider("acme", "anthropic", "https://api.anthropic.com/", "anthropic-messages", "sk-real")
    assert p.url == "https://api.anthropic.com" and "sk-real" not in p.key and "key" not in p.public()
    assert store.open_key(p) == "sk-real"
    assert [x.name for x in store.providers("acme")] == ["anthropic"]
    own = store.put_provider("acme", "mine", "https://proxy.acme.example", "none", "")
    assert store.open_key(own) == ""
    for args, says in [(("https://x", "bogus", "k"), "api is one of"), (("http://x", "openai-chat", "k"), "https://"),
                       (("https://x", "openai-chat", ""), "has a key"), (("https://x", "none", "k"), "has a key"),
                       (("https://x", "openai-chat", "two\nlines"), "one line")]:
        with pytest.raises(Invalid, match=says):
            store.put_provider("acme", "p", *args)
    store.delete_provider("acme", "anthropic")
    with pytest.raises(NotFound):
        store.provider("acme", "anthropic")


def test_sandboxes(store):
    store.create_org("acme")
    s = store.put_sandbox("acme", "py", image="python:3.12-slim", egress=["pypi.org"], memory="2g", pids=100)
    assert s.public() == {"name": "py", "image": "python:3.12-slim", "dockerfile": "", "egress": ["pypi.org"],
                          "memory": "2g", "pids": 100}
    assert store.put_sandbox("acme", "built", dockerfile="FROM alpine\n").dockerfile == "FROM alpine\n"
    with pytest.raises(Invalid, match="one of the two"):
        store.put_sandbox("acme", "both", image="a", dockerfile="b")
    with pytest.raises(Invalid, match="memory"):
        store.put_sandbox("acme", "x", image="a", memory="lots")
    store.delete_sandbox("acme", "py")
    assert [x.name for x in store.sandboxes("acme")] == ["built"]


def test_harness_versions(store):
    store.create_org("acme")
    h1 = store.put_harness("acme", "cc", archive())
    assert store.harness("acme", "cc").digest == h1.digest
    assert store.config(h1).model == "m1" and (store.folder(h1) / "request.sh").is_file()
    h2 = store.put_harness("acme", "cc", archive(description="v2"))
    assert h2.digest != h1.digest and store.harness("acme", "cc").digest == h2.digest
    assert store.harness("acme", "cc", h1.digest).digest == h1.digest   # an older version stays runnable
    assert store.put_harness("acme", "cc", archive()).digest == h1.digest  # the same bytes are the same version
    assert [h.name for h in store.harnesses("acme")] == ["cc"]
    with pytest.raises(Invalid, match="request.sh is missing"):
        store.put_harness("acme", "bad", archive({"request.sh": None}))
    with pytest.raises(NotFound):
        store.harness("acme", "bad")
    store.delete_harness("acme", "cc")
    assert store.harnesses("acme") == []


def test_orgs_are_separate(store):
    store.create_org("a")
    store.create_org("b")
    store.put_provider("a", "p", "https://x", "openai-chat", "k")
    store.put_harness("a", "h", archive())
    with pytest.raises(NotFound):
        store.provider("b", "p")
    with pytest.raises(NotFound):
        store.harness("b", "h")
    assert store.harnesses("b") == [] and store.providers("b") == []
