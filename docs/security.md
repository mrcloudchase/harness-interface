# Security

What the platform promises, and the test that proves each promise. A change that breaks one
fails CI.

| # | Invariant | Proof |
|---|---|---|
| 1 | A provider's key is in the clear only inside the gateway process, for one upstream request at a time. Never on a command line, in a sandbox's environment, on a worker's disk, in a log, a trace, a capture or a response. | `test_docker.py::test_a_turn` (the sandbox's environment, token file and mounts hold the token, not the key), `test_gateway.py` (the capture never holds the key) |
| 2 | A sandbox reaches only its door; the door tunnels only to the package's egress hosts and forwards provider calls to the gateway. Private, loopback, link-local and multicast addresses are refused after resolution, and the connection is made to the address that was checked. | `test_door.py`, `test_docker.py::test_a_turn` (the cloud metadata address is refused) |
| 3 | A sandbox runs as a uid unique to its tenant, with every capability dropped, no new privileges, a read-only root, and the tenant's cpu, memory and pid ceilings; under a sandboxed runtime where the node has one. | `test_docker.py::test_a_turn` |
| 4 | The platform never writes through a path a sandbox can create. Every write into a workspace, home, run or tools directory goes through one helper that refuses links at every component, and every read of a sandbox's output refuses anything but a plain file. | `test_files.py`, `test_harness.py::test_copy_seed_is_safe` |
| 5 | A worker can see only the turns it was handed: its credential claims, reports and posts output; the blob URLs it receives name one object each for a short while. It holds no database, bucket or cloud credential. | `test_sessions.py` (another worker cannot end a turn), `test_blobs.py::test_dir_signed_urls` |
| 6 | Reach is tenant, then member: members see their own sessions, owners their tenant's, nobody another tenant's; every miss is a 404. | `test_sessions.py::test_continue_overrides_and_reach`, `test_api.py::test_deployer_and_tenants_apart` |
| 7 | Every number a tenant could influence has a deployer ceiling on the tenant record: cpus, memory, pids, timeouts, runs at once, disk, output, upload. | `test_store.py`, `test_api.py` |
| 8 | Harness packages are never served back; the archive is the workspace only. | `test_api.py` (no route returns a package) |
| 9 | The gateway relays only the API shape's own endpoints under the provider's path, and refuses a mixed or missing credential. | `test_gateway.py` |
| 10 | No cloud SDK is imported anywhere but the two backend modules, and a module imports only its layer or below. | `test_layers.py` |

## How a turn is contained

- **A fresh container per turn** from the platform's base image. Tenants choose neither the image
  nor the limits.
- **No capabilities, no privilege escalation, a read-only root** with a writable `/tmp`, and the
  tenant's own unprivileged uid, derived from the tenant name so it is the same on every node.
  The writable mounts are handed to that uid before the turn and nothing else on the host belongs
  to it.
- **One route out.** The sandbox has no DNS and no default route. Its only neighbour is a door on
  a private network. The door tunnels to the package's egress hosts, resolves names itself,
  refuses private answers, and connects to the address it checked. Provider calls go through the
  door's forwarder to the gateway.
- **A token, not a key.** The sandbox gets a per-turn session token in a file readable only by
  its uid. The gateway swaps it for the real key, which it decrypts in memory for that one call.
  The token expires two minutes after the turn's timeout.
- **The package's scripts run unprivileged**, including `install.sh`, with its own egress list.
- **Secrets never cross a command line.** Environment variables reach the container by name; the
  Docker client inherits only an allowlist of host variables.
- **Everything is torn down**: the container, the door, the network, and the token file, which is
  overwritten before it is deleted.

## What the deployer sees

Counts and sizes: tenants, workers, turns, seconds, calls, bytes, queued and running. Never a
tenant's prompts, output, packages or keys. The member routes refuse the deployer key, and the dashboard shows the same counts and nothing more.

## What a tenant should still do

- Give a package the least egress it needs. An agent that can reach a host can send what it read
  there.
- Mint a key per place a key is used, and revoke the one that leaks.
- Treat the trace and the captures as sensitive. They are the complete record of what the agent
  saw and said.
- Where tenants are strangers, the deployer puts a sandboxed runtime on worker machines
  (`HG_RUNTIME=runsc`).

## Reporting

Open a private security advisory on the repository, or write to the maintainers before opening
an issue. A fix to an invariant ships with its test.

Next: [Troubleshooting](troubleshooting.md).
