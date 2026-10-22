# Security

The platform's promises, each with the test that proves it. A change that breaks one fails CI.

| # | Invariant | Proof |
|---|---|---|
| 1 | A provider's key is in the clear only inside the gateway process, for one upstream request at a time. Never on a command line, in a sandbox's environment, on a worker's disk, in a log, a trace, a capture or a response. | `test_docker.py::test_a_turn` (the sandbox's environment, token file and mounts hold the token, not the key), `test_gateway.py` (the capture never holds the key) |
| 2 | A sandbox reaches only its door; the door tunnels only to the package's egress hosts and forwards provider calls to the gateway. Private, loopback, link-local and multicast addresses are refused after resolution, and the connection is made to the address that was checked. | `test_door.py`, `test_docker.py::test_a_turn` (the metadata address is refused) |
| 3 | A sandbox runs as a uid unique to its tenant, with every capability dropped, no new privileges, a read-only root, and the tenant's cpu, memory and pid ceilings; under a sandboxed runtime where the node has one. | `test_docker.py::test_a_turn` |
| 4 | The platform never writes through a path a sandbox can create. Every write into a workspace, home, run or tools directory goes through one helper that refuses links at every component, and every read of a sandbox's output refuses anything but a plain file. | `test_files.py`, `test_harness.py::test_copy_seed_is_safe` |
| 5 | A worker can see only the turns it was handed: its credential claims, reports and posts output; the blob URLs it receives name one object each for a short while. It holds no database, bucket or cloud credential. | `test_sessions.py` (another worker cannot end a turn), `test_blobs.py::test_dir_signed_urls` |
| 6 | Reach is tenant, then member: members see their own sessions, owners their tenant's, nobody another tenant's; every miss is a 404. | `test_sessions.py::test_continue_overrides_and_reach`, `test_api.py::test_deployer_and_tenants_apart` |
| 7 | Every number a tenant could influence has a deployer ceiling on the tenant record: cpus, memory, pids, timeouts, runs at once, disk, output, upload. | `test_store.py`, `test_api.py` |
| 8 | Harness packages are never served back; the archive is the workspace only. | `test_api.py` (no route returns a package) |
| 9 | The gateway relays only the API shape's own endpoints under the provider's path, and refuses a mixed or missing credential. | `test_gateway.py` |
| 10 | No cloud SDK is imported anywhere but the two backend modules, and a module imports only its layer or below. | `test_layers.py` |

## What the deployer sees

Counts and sizes: tenants, workers, turns, seconds, calls, bytes, queued and running. Never a
tenant's prompts, output, packages or keys. The console says so on the deployer's pages.

## What a tenant should still do

- Give a package the least egress it needs; an agent that can reach a host can send what it read
  there.
- Mint a key per place a key is used, and revoke the one that leaks.
- Treat the trace and the captures as sensitive: they are the complete record of what the agent saw
  and said.
- Put a sandboxed runtime on worker machines (`HI_RUNTIME=runsc`) wherever tenants are strangers.
