"""Pass Hermes's text through untouched. The answer is the last line that is not a warning or the
session line; `session_id: <id>` is the resume handle. It reports no usage in quiet mode."""
import json
import os
import sys

out, answer = {}, []
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    s = line.strip()
    if s.startswith("session_id:"):
        out["session_id"] = s.split(":", 1)[1].strip()
    elif s and not s.startswith(("⚠", "↻")):           # warnings and the "resumed session" banner are not the answer
        answer.append(s)
out["answer"] = "\n".join(answer)
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
