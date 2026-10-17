"""Pass the harness's text through untouched. Its words come after `> ` with continuation lines
indented two spaces; the last such block is the answer. It reports no usage and no session."""
import json
import os
import sys

blocks, cur = [], None
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    if line.startswith("> "):
        cur = [line[2:].rstrip("\n")]; blocks.append(cur)
    elif cur is not None and line.startswith("  ") and not line.startswith("  └"):
        cur.append(line[2:].rstrip("\n"))
    else:
        cur = None
json.dump({"answer": "\n".join(blocks[-1]) if blocks else ""}, open(os.environ["HI_OUTPUT"], "w"))
