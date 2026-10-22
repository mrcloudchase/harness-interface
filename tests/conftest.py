import os
import threading

import pytest

from harness_interface.blobs import DirBlobs, S3Blobs
from harness_interface.records import PostgresRecords, SqliteRecords
from harness_interface.secrets import Vault

POSTGRES = os.environ.get("HI_TEST_POSTGRES", "postgresql://postgres@/postgres?host=/var/lib/postgresql/hi&port=54329")


@pytest.fixture
def vault():
    return Vault(bytes.fromhex(Vault.generate()))


@pytest.fixture(params=["sqlite", "postgres"])
def records(request, tmp_path):
    if request.param == "sqlite":
        r = SqliteRecords(tmp_path / "records.db")
    else:
        try:
            r = PostgresRecords(POSTGRES)
        except Exception as e:                       # no Postgres here: the SQLite run still proves the statements
            pytest.skip(f"no Postgres at {POSTGRES}: {e}")
        r._run("DELETE FROM records")
    yield r
    r.close()


@pytest.fixture(scope="session")
def s3_endpoint():
    """A moto S3 server for the S3 backend's tests."""
    try:
        from moto.server import ThreadedMotoServer
    except ImportError:
        pytest.skip("moto[server] is not installed")
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server._server.server_address[:2]
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture(params=["dir", "s3"])
def blobs(request, tmp_path):
    if request.param == "dir":
        return DirBlobs(tmp_path / "blobs", "http://api.test", b"secret")
    endpoint = request.getfixturevalue("s3_endpoint")
    import boto3
    boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1").create_bucket(Bucket="hi-test")
    b = S3Blobs("hi-test", endpoint, "us-east-1")
    b.delete("tenants")
    return b
