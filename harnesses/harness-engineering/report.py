"""Pass the harness's text through untouched. Its words come after `> ` with continuation lines
indented two spaces; the last such block is the answer. The turn is added to the transcript in
$HOME, in the harness's own `< ` and `> ` marks, and the session is that transcript. It reports
no usage."""
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
answer = "\n".join(blocks[-1]) if blocks else ""
os.makedirs(os.environ["HOME"], exist_ok=True)
with open(os.path.join(os.environ["HOME"], "conversation.txt"), "a") as t:
    t.write(f"< {os.environ['HI_TASK']}\n> {answer}\n\n")
json.dump({"answer": answer, "session_id": "conversation"}, open(os.environ["HI_OUTPUT"], "w"))
