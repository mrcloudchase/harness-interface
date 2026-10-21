"""Layer 1: the door's host rule and the gateway's credential rule, keyless included."""
import pytest

from harness_interface.runtimes.door import Gateway, normalize


def test_normalize():
    assert normalize("api.x.com") == "api.x.com:443"
    assert normalize("https://api.x.com/v1/") == "api.x.com:443"
    assert normalize("http://x:8080") == "x:8080"
    assert normalize("Host:9") == "host:9"


def test_gateway_admits_only_the_token():
    g = Gateway("https://api.x.com", "anthropic-messages", "tok", "key")
    assert g.admits([("x-api-key", "tok")]) and g.admits([("Authorization", "Bearer tok")])
    assert not g.admits([("x-api-key", "key")]) and not g.admits([("accept", "*/*")])
    assert not g.admits([("x-api-key", "tok"), ("authorization", "Bearer other")])
    assert g._auth == "x-api-key: key"
    assert Gateway("https://x", "openai-chat", "t", "k")._auth == "Authorization: Bearer k"
    assert Gateway("https://x", "none", "t", "")._auth == ""
    with pytest.raises(ValueError):
        Gateway("http://x", "openai-chat", "t", "k")
    with pytest.raises(ValueError):
        Gateway("https://x", "bogus", "t", "k")
