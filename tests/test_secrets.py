"""Layer 0: the vault seals and opens; a value is bound to its record; the key comes from the environment."""
import pytest

from harness_interface.secrets import Vault


def test_seal_and_open_round_trip(vault):
    sealed = vault.seal("sk-live-123", "acme/providers/anthropic")
    assert sealed.startswith("v1:") and "sk-live-123" not in sealed
    assert vault.open(sealed, "acme/providers/anthropic") == "sk-live-123"


def test_a_sealed_value_cannot_move_to_another_record(vault):
    sealed = vault.seal("k", "acme/providers/a")
    with pytest.raises(Exception):
        vault.open(sealed, "acme/providers/b")


def test_another_master_key_cannot_open_it(vault):
    sealed = vault.seal("k", "x")
    with pytest.raises(Exception):
        Vault(bytes.fromhex(Vault.generate())).open(sealed, "x")


def test_from_env(tmp_path):
    key = Vault.generate()
    assert Vault.from_env({"HI_MASTER_KEY": key}).open(Vault.from_env({"HI_MASTER_KEY": key}).seal("v", "a"), "a") == "v"
    (tmp_path / "k").write_text(key + "\n")
    assert Vault.from_env({"HI_MASTER_KEY_FILE": str(tmp_path / "k")})
    with pytest.raises(RuntimeError):
        Vault.from_env({})
    with pytest.raises(ValueError):
        Vault(b"short")
