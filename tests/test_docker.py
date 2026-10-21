"""Layer 4 and 5 under Docker: a real sandbox image, nothing of ours in it; the tools layer built by
install.sh and cached; the turn's variables; the provider's key never in the container; a steer
delivered as the file and the signal; a cancel; a file produced and archived."""
import asyncio
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from fakes import archive
from harness_interface.runtimes.docker import owner_of
from harness_interface.sandboxes import Runtimes
from harness_interface.sessions import Ask, Sessions

pytestmark = pytest.mark.docker
IMAGE = "python:3.12-slim"
CA = Path(os.environ["HI_CA_FILE"]) if os.environ.get("HI_CA_FILE") else None
REQUEST = """#!/usr/bin/env bash
set -u
prompt=$(cat)
echo "prompt=$prompt turn=$HI_TURN model=$HI_MODEL pwd=$PWD home=$HOME"
echo "tool=$(tool)"
echo "keyenv=${FAKE_KEY:-}"
echo "url=${FAKE_URL:-}"
echo "keyfile=$(cat "$HI_PROVIDER_KEY_FILE")"
echo "env_has_real_key=$(env | grep -c sk-real-secret)"
echo "whoami=$(id -u)"
echo "$prompt" > produced.txt
echo "a warning" >&2
trap 'echo "steer=$(cat "$HI_DIR/interrupt")"; exit 0' USR1
if [ "$prompt" = "wait" ]; then sleep 60 & wait $!; fi
exit 0
"""


@pytest.fixture
def sessions(store, tmp_path):
    store.create_org("acme")
    store.create_member("acme", "dev", "member")
    store.put_provider("acme", "prov", "https://api.example", "openai-chat", "sk-real-secret")
    store.put_sandbox("acme", "box", image=IMAGE, memory="1g", pids=128)
    store.put_harness("acme", "cc", archive({"request.sh": REQUEST}, install='{"egress": [], "timeout_s": 120}'))
    return Sessions(store, Runtimes(tmp_path / "logs", CA, owner_of(tmp_path)))


def test_a_turn_in_a_sandbox(sessions, store):
    dev = store.member("acme", "dev")

    async def go():
        r = await sessions.wait((await sessions.create(Ask("acme", "dev", "cc", "hello", model="m9"))).id)
        r2 = await sessions.wait((await sessions.create(Ask("acme", "dev", "cc", "again", previous=r.id))).id)
        return r, r2, await sessions.archive(dev, r.session)
    r, r2, data = asyncio.run(go())
    assert r.status == "completed", (r.stdout, r.stderr, r.error)
    lines = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    assert lines["prompt"].startswith("hello turn=1 model=m9")
    assert lines["tool"] == "tool-ran"                         # install.sh's work, on PATH
    assert lines["keyenv"].startswith("sk-hi-") and lines["keyenv"] == lines["keyfile"]
    assert lines["url"] == "http://hi-provider:8080" and lines["env_has_real_key"] == "0"
    assert lines["whoami"] == ("1000" if os.geteuid() == 0 else str(os.getuid()))
    assert r.stderr == "a warning\n"
    assert "turn=2" in r2.stdout and r2.session == r.session
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert tar.extractfile("./produced.txt").read() == b"again\n"
    assert sessions.session(dev, r.session).responses == [r.id, r2.id]
    installed = list(store.tools_root(store.harness("acme", "cc")).glob("box-*/.hi-installed"))
    assert len(installed) == 1 and json.loads(installed[0].read_text())["arch"]


def test_interrupt_and_cancel(sessions, store):
    dev = store.member("acme", "dev")

    async def go():
        r = await sessions.create(Ask("acme", "dev", "cc", "wait"))
        for _ in range(600):
            if sessions._live[r.id].execution is not None and "whoami" in sessions._live[r.id].feed.text("stdout"):
                break
            await asyncio.sleep(0.1)
        await sessions.interrupt(dev, r.session, "turn left")
        steered = await sessions.wait(r.id)
        r = await sessions.create(Ask("acme", "dev", "cc", "wait", previous=steered.id))
        for _ in range(600):
            if sessions._live[r.id].execution is not None and "whoami" in sessions._live[r.id].feed.text("stdout"):
                break
            await asyncio.sleep(0.1)
        return steered, await sessions.cancel(dev, r.id)
    steered, cancelled = asyncio.run(go())
    assert steered.status == "completed" and "steer=turn left" in steered.stdout, steered.stdout
    assert cancelled.status == "cancelled" and "whoami" in cancelled.stdout
    trace = [t["kind"] for t in sessions.trace(dev, steered.session)]
    assert trace == ["request", "interrupt", "response", "request", "cancel", "response"]
