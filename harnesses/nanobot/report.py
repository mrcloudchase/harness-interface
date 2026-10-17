"""Pass nanobot's text through untouched. The answer is everything after the `🐈 nanobot` banner
(stripped of ANSI codes) except the `  ↳ $ cmd` tool hints; the session id is the one run.sh minted, given as argv[1]. nanobot
reports no usage in this mode."""
import json
import os
import re
import sys

ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
answer, started = [], False
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    s = ansi.sub("", line).rstrip("\n")
    if not started:
        started = "nanobot" in s and "🐈" in s
        continue
    if s.lstrip().startswith("↳"):        # tool-call hint, not the answer
        continue
    answer.append(s)
out = {"session_id": sys.argv[1], "answer": "\n".join(answer).strip()}
out["status"] = "ok" if out["answer"] else "fail"
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
