"""The command line.

    harnessgateway init [--tenant NAME --owner NAME]
        Writes a master key to <data>/master.key unless one is there, sets the deployer key and prints
        it once, and, with --tenant, creates that tenant with its owner and prints the owner's key once.
    harnessgateway serve [--role api,gateway,worker | all]
        Runs the roles named in one process, as the environment configures them (HG_*).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

from .api.config import Settings
from .secrets import Vault


def master_key(settings: Settings) -> None:
    """HG_MASTER_KEY or HG_MASTER_KEY_FILE from the environment, else the file under the data directory."""
    if os.environ.get("HG_MASTER_KEY") or os.environ.get("HG_MASTER_KEY_FILE"):
        return
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key_file = settings.data_dir / "master.key"
    if not key_file.exists():
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(Vault.generate() + "\n")
        print(f"master key written to {key_file}", file=sys.stderr)
    os.environ["HG_MASTER_KEY_FILE"] = str(key_file)


def init(args: argparse.Namespace) -> None:
    from .api.app import Service
    settings = Settings.from_env()
    master_key(settings)
    service = Service(settings)
    print(f"deployer key (shown once): {service.store.set_deployer_key()}")
    if args.tenant:
        t = service.store.create_tenant(args.tenant)
        service.store.create_member(t.name, args.owner, "owner")
        _, secret = service.store.mint_key(t.name, args.owner, "first")
        print(f"tenant {t.name} created with owner {args.owner}")
        print(f"owner's API key (shown once): {secret}")


async def run(settings: Settings) -> None:
    from .api.app import Service, create_app
    service = Service(settings)
    tasks = []
    if "api" in settings.roles:
        import uvicorn
        server = uvicorn.Server(uvicorn.Config(create_app(service), host=settings.host, port=settings.port, log_level="info"))
        tasks.append(asyncio.create_task(server.serve()))
    if "gateway" in settings.roles:
        from .gateway import Gateway, serve as serve_gateway
        tasks.append(asyncio.create_task(serve_gateway(Gateway(service.store, service.blobs), settings.gateway_host, settings.gateway_port)))
    if "worker" in settings.roles:
        from .runtimes.docker import owner_of
        from .sandboxes import Node
        from .worker import Worker
        node = Node(settings.base_image, owner_of(settings.data_dir), settings.runtime, settings.ca_file, settings.allow_private,
                    root=settings.data_dir / "worker", gateway_port=settings.gateway_port if "gateway" in settings.roles else 0)
        worker = Worker(settings.control_url, node, settings.data_dir / "worker", name=settings.worker_name,
                        slots=settings.worker_slots, version=service_version(), join_token=service.join_token, ca_file=settings.ca_file,
                        gateway_url=os.environ.get("HG_GATEWAY_URL", "").rstrip("/"))
        tasks.append(asyncio.create_task(worker.run()))
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    done, _ = await asyncio.wait([*tasks, asyncio.create_task(stop.wait())], return_when=asyncio.FIRST_COMPLETED)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for t in done:
        if t.exception() and not isinstance(t.exception(), asyncio.CancelledError):
            raise t.exception()


def service_version() -> str:
    from importlib.metadata import version
    return version("harnessgateway")


def serve(args: argparse.Namespace) -> None:
    settings = Settings.from_env(args.role)
    master_key(settings)
    asyncio.run(run(settings))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="harnessgateway", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="the master key, the deployer key, and optionally a first tenant")
    p.add_argument("--tenant")
    p.add_argument("--owner", default="owner")
    p.set_defaults(run=init)
    p = sub.add_parser("serve", help="run one or more roles")
    p.add_argument("--role", default="all", help="api,gateway,worker or all")
    p.set_defaults(run=serve)
    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
