"""The command line: `harness-interface init` sets a server up and `harness-interface serve` runs it.

    harness-interface init --org acme --owner chase [--data DIR]
        Writes a master key to <data>/master.key (unless one is there), creates the org with its
        owner, and prints the owner's API key once. A self-hosted box is one org; a hosted
        platform creates orgs through POST /v1/orgs with HI_ADMIN_KEY instead.
    harness-interface serve
        Serves the API as the environment configures it (HI_HOST, HI_PORT, HI_DATA_DIR,
        HI_MASTER_KEY or HI_MASTER_KEY_FILE, HI_ADMIN_KEY, HI_CA_FILE).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .api.config import Settings
from .secrets import Vault
from .store import Store


def init(args: argparse.Namespace) -> None:
    data = Path(args.data or Settings().data_dir)
    data.mkdir(parents=True, exist_ok=True)
    key_file = data / "master.key"
    if not key_file.exists():
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(Vault.generate() + "\n")
        print(f"master key written to {key_file}; serve with HI_MASTER_KEY_FILE={key_file}")
    store = Store(data, Vault(bytes.fromhex(key_file.read_text().strip())))
    org = store.create_org(args.org, args.max_runs)
    store.create_member(org.name, args.owner, "owner")
    _, secret = store.mint_key(org.name, args.owner, "first")
    print(f"org {org.name} created with owner {args.owner}")
    print(f"API key (shown once): {secret}")


def serve(_: argparse.Namespace) -> None:
    import uvicorn

    from .api.app import Service, create_app
    settings = Settings.from_env()
    if not (os.environ.get("HI_MASTER_KEY") or os.environ.get("HI_MASTER_KEY_FILE")):
        default = settings.data_dir / "master.key"
        if default.is_file():
            os.environ["HI_MASTER_KEY_FILE"] = str(default)
    uvicorn.run(create_app(Service(settings)), host=settings.host, port=settings.port, log_level="info")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="harness-interface", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="create the master key, an org and its owner's key")
    p.add_argument("--org", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--data", default=os.environ.get("HI_DATA_DIR"))
    p.add_argument("--max-runs", type=int, default=4)
    p.set_defaults(run=init)
    sub.add_parser("serve", help="serve the API").set_defaults(run=serve)
    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
