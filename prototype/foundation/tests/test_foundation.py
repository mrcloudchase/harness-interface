"""Fast checks of the foundation (no Docker): python3 -m unittest discover -s tests -v
End-to-end proofs with Docker are in prove.py."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "template"))
import hirun  # noqa: E402
import hi_adapter  # noqa: E402

CANON = (ROOT / "template" / "hi_adapter.py").read_bytes()


def folders():
    """Every harness folder this rebuild has: the template, the probe and stage 2's harnesses."""
    return [p.parent for p in (*ROOT.glob("*/harness.json"), *(ROOT.parent / "harnesses").glob("*/harness.json"))]


class SharedAdapter(unittest.TestCase):
    def test_every_copy_is_identical(self):
        for f in folders():
            with self.subTest(folder=f.name):
                self.assertEqual((f / "hi_adapter.py").read_bytes(), CANON,
                                 f"cp {ROOT}/template/hi_adapter.py {f}/")

    def test_every_folder_is_valid(self):
        for f in folders():
            with self.subTest(folder=f.name):
                hirun.Folder(f)


class FolderValidation(unittest.TestCase):
    def variant(self, **changes):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        for n in ("install.sh", "run.sh", "adapter.py", "hi_adapter.py"):
            (d / n).write_bytes((ROOT / "template" / n).read_bytes())
        spec = json.loads((ROOT / "template" / "harness.json").read_text())
        for k, v in changes.items():
            if v is None:
                spec.pop(k)
            else:
                spec[k] = v
        (d / "harness.json").write_text(json.dumps(spec))
        return d

    def test_rejects(self):
        cases = {"unknown field": {"sandbox": "default"}, "missing": {"install": None},
                 "api not spoken": {"provider": {"url": "https://x", "api": "openai-chat"}, "apis": ["anthropic-messages"]},
                 "http provider": {"provider": {"url": "http://x", "api": "anthropic-messages"}},
                 "bad interrupt": {"run": {"interrupt": "maybe", "stdout": "x", "timeout_s": 1, "stop_timeout_s": 1}},
                 "run.argv cut": {"run": {"argv": ["x"], "interrupt": "steered", "stdout": "x", "timeout_s": 1,
                                          "stop_timeout_s": 1}},
                 "escaping file": {"files": {"../x": "{instructions}"}}}
        for name, change in cases.items():
            with self.subTest(case=name), self.assertRaises(SystemExit):
                hirun.Folder(self.variant(**change))

    def test_tools_hash_covers_install_sh_only(self):
        a = hirun.Tools(hirun.Folder(self.variant()), local=True).dir
        d = self.variant()
        (d / "run.sh").write_text("# changed\n")
        self.assertEqual(hirun.Tools(hirun.Folder(d), local=True).dir, a)
        (d / "install.sh").write_text("# changed\n")
        self.assertNotEqual(hirun.Tools(hirun.Folder(d), local=True).dir, a)


class Plumbing(unittest.TestCase):
    def test_output_is_atomic_and_closed(self):
        with tempfile.TemporaryDirectory() as t:
            out = hi_adapter.Output(os.path.join(t, "o.json"))
            out.write(resume="abc")
            self.assertEqual(json.loads(Path(t, "o.json").read_text())["status"], "running")
            out.write(status="ok", answer="hi")
            self.assertEqual(json.loads(Path(t, "o.json").read_text())["resume"], "abc")
            self.assertEqual(os.listdir(t), ["o.json"])
            with self.assertRaises(AssertionError):
                out.write(status="interrupted")
            with self.assertRaises(AssertionError):
                out.write(session_id="x")

    def test_request_line_tolerates_pretty_json(self):
        req = hi_adapter.read_request(io.StringIO('{\n  "task": "t",\n  "model": "m"\n}\n"steer"\n'))
        self.assertEqual((req["task"], req["model"], req["instructions"], req["metadata"]), ("t", "m", "", {}))


class LocalRun(unittest.TestCase):
    """The template end to end on the host (installs its local tools once)."""

    def test_steered_local_run(self):
        r = subprocess.run([sys.executable, str(ROOT / "hirun.py"), "run", str(ROOT / "template"), "--local", "--quiet",
                            "--task", "count to 4", "--steer-after-lines", "3", "count to 5"],
                           capture_output=True, text=True, timeout=120)
        res = json.loads(r.stdout)
        self.assertEqual((res["status"], res["answer"], res["steers"]), ("ok", "Counted to 5.", 1))


if __name__ == "__main__":
    unittest.main()
