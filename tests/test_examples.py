"""The examples still run: each is a real consumer of the library, and proof that it stands alone."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_running_a_harness_folder_from_python(tmp_path):
    env = {**os.environ, "ECHO_KEY": "k"}
    cmd = [sys.executable, str(ROOT / "examples/library/run_a_harness.py"), str(ROOT / "tests/echo"), "say hi",
           "--provider-url", "https://example.invalid/v1", "--key-env", "ECHO_KEY", "--local",
           "--workspace", str(tmp_path / "ws")]
    first = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == "echo: say hi" and "ok · exit 0 · session echo-1 · changed hello.txt" in first.stderr
    second = subprocess.run([*cmd, "--session", "echo-1"], capture_output=True, text=True, env=env, timeout=60)
    assert '"session_id_in":"echo-1"' in second.stderr and "changed nothing" in second.stderr
