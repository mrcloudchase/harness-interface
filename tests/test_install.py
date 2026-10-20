"""Layer 3: a harness installs once per version. The tools directory is keyed by install.sh,
image.Dockerfile, the base image and the CPU architecture, and nothing else; it is complete only with
its marker; a failed, timed-out or cancelled install leaves nothing; the same install never runs twice
at once. Under Docker it runs hardened, in the harness's image, behind a door that reaches only
install.egress, with no provider or secret. On this machine, and against a fake docker."""
import asyncio
import json
import os
import subprocess

import pytest

from harness_interface.harness.install import BASE_DOCKERFILE, MARKER, InstallFailed, Installer
from harness_interface.harness.placement import Placement
from harness_interface.runtimes.docker import HARDENING, KEY_PATH, LABEL, Images, owner_of
from standin import OFFLINE_INSTALL, variant

COUNT = 'echo x >> "$HI_HARNESS_DIR/../installs"\n'      # each install, counted beside the folder


def folder_with(tmp_path, install=OFFLINE_INSTALL + COUNT, change=None, **files):
    return variant(tmp_path / "folder", change, install__sh=install, **files)


def installs(tmp_path) -> int:
    p = tmp_path / "installs"
    return len(p.read_text().split()) if p.exists() else 0


def ensure(installer, folder):
    return asyncio.run(installer.ensure(folder))


def values(call, flag):
    return [call[i + 1] for i, a in enumerate(call) if a == flag]


def test_a_first_install_fills_the_tools_and_the_next_is_a_hit(tmp_path):
    installer, folder = Installer(tmp_path / "tools", Placement()), folder_with(tmp_path)
    first = ensure(installer, folder)
    assert not first.cached and first.image is None and (first.path / "bin" / "standin").is_file()
    assert json.loads((first.path / MARKER).read_text())["harness"] == "template"
    second = ensure(installer, folder)
    assert second.cached and second.path == first.path and installs(tmp_path) == 1


def test_the_key_moves_with_install_sh_the_image_and_the_architecture_only(tmp_path, monkeypatch):
    installer = Installer(tmp_path / "tools", Placement())
    base = ensure(installer, folder_with(tmp_path)).path
    assert ensure(installer, folder_with(tmp_path, run__sh="# changed\n", adapter__py="# changed\n")).path == base
    assert ensure(installer, folder_with(tmp_path, install=OFFLINE_INSTALL + COUNT + "# changed\n")).path != base
    assert ensure(installer, folder_with(tmp_path, image__Dockerfile="FROM hi-base\nRUN true\n")).path != base
    monkeypatch.setattr("harness_interface.harness.install.platform.machine", lambda: "aarch64")
    assert ensure(installer, folder_with(tmp_path)).path != base
    assert installs(tmp_path) == 4


def test_a_failed_install_leaves_no_tools_and_says_why(tmp_path):
    installer = Installer(tmp_path / "tools", Placement())
    folder = folder_with(tmp_path, install='mkdir -p "$HI_TOOLS/bin"; echo "registry said no"; exit 3\n')
    with pytest.raises(InstallFailed) as e:
        ensure(installer, folder)
    assert "exited 3" in str(e.value) and "registry said no" in str(e.value)
    assert "registry said no" in e.value.log.read_text()
    assert [p.name for p in (tmp_path / "tools").iterdir() if not p.name.startswith(".")] == [e.value.log.name]


def test_an_install_out_of_time_leaves_nothing(tmp_path):
    installer = Installer(tmp_path / "tools", Placement())
    folder = folder_with(tmp_path, install='touch "$HI_TOOLS/half"; sleep 30\n',
                         change=lambda s: s["install"].update(timeout_s=0.5))
    with pytest.raises(InstallFailed, match="ran out of time"):
        ensure(installer, folder)
    assert not any(p.is_dir() and not p.name.startswith(".") for p in (tmp_path / "tools").iterdir())


def test_the_same_install_never_runs_twice_at_once(tmp_path):
    installer = Installer(tmp_path / "tools", Placement())
    folder = folder_with(tmp_path, OFFLINE_INSTALL + COUNT + "sleep 0.5\n")

    async def both():
        return await asyncio.gather(installer.ensure(folder), Installer(tmp_path / "tools", Placement()).ensure(folder))
    a, b = asyncio.run(both())
    assert a.path == b.path and sorted([a.cached, b.cached]) == [False, True] and installs(tmp_path) == 1


def test_a_cancelled_install_leaves_nothing_running_and_no_tools(tmp_path):
    installer = Installer(tmp_path / "tools", Placement())
    folder = folder_with(tmp_path, install=f'echo started; sleep 30 # {tmp_path}\n')

    async def go():
        task = asyncio.ensure_future(installer.ensure(folder))
        logs = tmp_path / "tools"
        while not any("started" in p.read_text() for p in logs.glob("*.log")):
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert not any(p.is_dir() and not p.name.startswith(".") for p in (tmp_path / "tools").iterdir())
    assert subprocess.run(["pgrep", "-f", str(tmp_path)], capture_output=True).stdout == b""


def test_an_install_gets_no_provider_and_no_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("EXT_ANTHROPIC_API_KEY", "sk-from-the-host")
    dump = OFFLINE_INSTALL + 'python3 -c "import os, json; print(json.dumps(dict(os.environ)))" > "$HI_TOOLS/env.json"\n'
    installed = ensure(Installer(tmp_path / "tools", Placement()), folder_with(tmp_path, dump))
    env = json.loads((installed.path / "env.json").read_text())
    assert not any(k.startswith("HI_PROVIDER") or "KEY" in k for k in env)
    assert env["HI_TOOLS"] == str(installed.path) and env["PATH"].startswith(f"{installed.path}/bin:")
    assert not os.path.exists(env["HOME"])                               # a scratch home, gone with the install


# ── under Docker, against a fake ─────────────────────────────────────────────────────────────────
@pytest.fixture
def docker_installer(fake_docker, tmp_path):
    return Installer(tmp_path / "tools", Placement(Images(tmp_path / "logs")))


def test_a_placements_runtimes_and_its_recovery_are_its_owners_alone(fake_docker, tmp_path):
    mine, theirs = owner_of(tmp_path / "mine"), owner_of(tmp_path / "theirs")
    for owner in (mine, theirs):
        (fake_docker / f"container-hi-run-{owner}.labels").write_text(json.dumps([f"{LABEL}={owner}"]))
    placement = Placement(Images(tmp_path / "logs"), owner=mine)
    assert placement.runtime("hi-x:0").owner == mine and Placement(owner=mine).runtime(None).owner == mine
    asyncio.run(placement.recover())
    assert [p.name for p in fake_docker.state.glob("container-*")] == [f"container-hi-run-{theirs}.labels"]
    assert Placement().owner != Placement().owner                       # none given: shared with no other


def test_under_docker_the_install_runs_hardened_behind_a_door_for_its_hosts_only(fake_docker, docker_installer,
                                                                               tmp_path):
    folder = folder_with(tmp_path)
    installed = ensure(docker_installer, folder)
    base = Images.tag("base", BASE_DOCKERFILE.read_text())
    the_run, door = fake_docker.run(), fake_docker.door()
    assert installed.image == base and the_run[the_run.index(base) + 1:] == ["bash", str(folder.path / "install.sh")]
    assert " ".join(HARDENING) in " ".join(the_run) and "--init" in the_run
    tools = str(installed.path)
    assert {f"{tools}:{tools}", f"{folder.path}:{folder.path}:ro"} <= set(values(the_run, "-v"))
    assert values(the_run, "-w") == [tools] and not any(str(KEY_PATH) in v for v in values(the_run, "-v"))
    assert "HOME=/tmp" in values(the_run, "-e") and not any("PROVIDER" in e for e in values(the_run, "-e"))
    assert door[door.index("/door/door.py") + 2:] == ["registry.npmjs.org:443"]   # and no gateway
    assert (installed.path / "bin" / "standin").is_file() and (installed.path / MARKER).is_file()
    assert fake_docker.torn_down() and ensure(docker_installer, folder).cached


def test_an_image_dockerfile_is_built_from_the_base_and_the_install_runs_in_it(fake_docker, docker_installer,
                                                                             tmp_path):
    folder = folder_with(tmp_path, image__Dockerfile="# git for its tools\nFROM hi-base\nUSER root\nRUN true\n")
    installed = ensure(docker_installer, folder)
    base = Images.tag("base", BASE_DOCKERFILE.read_text())
    built = (fake_docker / f"build-{installed.image.replace(':', '-')}").read_text()
    assert installed.image.startswith("hi-harness-template:") and built.splitlines()[:2] == ["# git for its tools",
                                                                                          f"FROM {base}"]
    assert installed.image in fake_docker.run()


def test_the_base_image_and_architecture_are_in_the_key(fake_docker, docker_installer, tmp_path):
    folder = folder_with(tmp_path)
    amd64 = ensure(docker_installer, folder).path
    (fake_docker / "arch").write_text("arm64")
    assert ensure(docker_installer, folder).path != amd64
    assert ensure(Installer(tmp_path / "tools", Placement()), folder).path != amd64     # nor is this machine


def test_an_image_that_fails_to_build_is_an_install_failure(fake_docker, docker_installer, tmp_path):
    (fake_docker / "fail-build").write_text("")
    with pytest.raises(InstallFailed, match="image"):
        ensure(docker_installer, folder_with(tmp_path))
