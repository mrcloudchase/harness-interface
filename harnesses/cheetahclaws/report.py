"""Pass CheetahClaws's text through untouched. The answer is the body of the last
"╭─ CheetahClaws ●" box, after the spinner frames (the text after the last carriage return of
each line, with ANSI codes stripped). "(id: <id>)" on the "Session saved" lines is the resume
handle. No usage in quiet mode."""
import json
import os
import re
import sys

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
boxes, cur, out = [], None, {}
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    s = ANSI.sub("", line.rstrip("\n")).split("\r")[-1].strip()
    if s.startswith("╭─ CheetahClaws"):
        cur = []; boxes.append(cur)
    elif s.startswith("╰─"):
        cur = None
    elif cur is not None and s:
        cur.append(s)
    m = re.search(r"\(id: ([0-9a-f]+)\)", s)
    if m:
        out["session_id"] = m.group(1)
if boxes:
    out["answer"] = "\n".join(boxes[-1])
    out["status"] = "ok" if boxes[-1] else "fail"
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
