"""Layer 3: the catalog lists shipped packages and forks one into a tenant's harness."""
import pytest

from fakes import archive
from harness_interface.blobs import DirBlobs
from harness_interface.catalog import Catalog
from harness_interface.errors import NotFound
from harness_interface.harness import unpack
from harness_interface.records import SqliteRecords
from harness_interface.store import Store


def test_list_info_fork(tmp_path, vault):
    unpack(archive(description="shipped"), tmp_path / "cat" / "demo")
    (tmp_path / "cat" / "demo" / "catalog.json").write_text('{"verified": {"checks": 9}, "notes": ["n"]}')
    (tmp_path / "cat" / "junk").mkdir()
    c = Catalog(tmp_path / "cat")
    assert c.names() == ["demo"] and c.info("demo")["description"] == "shipped" and c.info("demo")["verified"] == {"checks": 9}
    with pytest.raises(NotFound):
        c.info("junk")
    store = Store(SqliteRecords(tmp_path / "r.db"), DirBlobs(tmp_path / "b", "http://api.test", b"s"), vault)
    store.create_tenant("acme")
    c.fork(store, "acme", "demo", "my-demo")
    assert store.harness("acme", "my-demo").config().description == "shipped"
