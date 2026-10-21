import pytest

from harness_interface.secrets import Vault
from harness_interface.store import Store


@pytest.fixture
def vault():
    return Vault(bytes.fromhex(Vault.generate()))


@pytest.fixture
def store(tmp_path, vault):
    return Store(tmp_path / "data", vault)
