"""Pass aider's text through untouched. The answer is what it prints between its startup banner
and the `Tokens: 2.6k sent, 5 received. Cost: $0.0079 message, $0.0079 session.` line, minus its
own status lines; that line carries usage, and cost when litellm can price the model. No Tokens
line means the run failed. The session handle is a constant: the chat history file under $HOME
is the state."""
import json
import os
import re
import sys

NOISE = re.compile(r"^(Analytics |Aider v|Model: |Main model: |Weak model: |Editor model: |Git repo: |Repo-map: |"
                   r"https://aider\.chat|Restored previous|Added .* to the chat|Applied edit|Warning: |Note: |Commit )")
TOKENS = re.compile(r"^Tokens: ([\d.]+[kM]?) sent, (?:[\d.]+[kM]? cache (?:write|hit), )*([\d.]+[kM]?) received\."
                    r"(?: Cost: \$([\d.]+) message)?")
num = lambda s: int(float(s[:-1]) * {"k": 1e3, "M": 1e6}[s[-1]]) if s[-1] in "kM" else int(float(s))

out, lines = {"session_id": "chat-history", "status": "fail"}, []
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    s = line.rstrip("\n")
    m = TOKENS.match(s)
    if m:
        out.update(answer="\n".join(lines).strip(), status="ok",
                   usage={"sent_tokens": num(m.group(1)), "received_tokens": num(m.group(2))})
        if m.group(3):
            out["cost_usd"] = float(m.group(3))
        lines = []
    elif not NOISE.match(s):
        lines.append(s)
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
