"""Probe adapter: reports where the run container can go, as its answer (JSON)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import Output, read_request  # noqa: E402
import egress_probe  # noqa: E402

req = read_request()
out = Output()
if req["task"] == "stream":
    result = egress_probe.stream(req["model"])
else:
    result = egress_probe.main(["api.anthropic.com", "registry.npmjs.org", "pypi.org", "github.com", "api.openai.com"])
print(json.dumps({"type": "probe", **result}), flush=True)
out.write(status="ok", answer=json.dumps(result))
