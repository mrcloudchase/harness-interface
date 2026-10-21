# Building on it

The server runs one turn and remembers it. Everything smarter is a program you write against the
API, in any language. The patterns below use the Python SDK; the HTTP calls are the same from
anywhere.

## An interactive session

A developer drives a harness on a repo for an afternoon. Each message is a request with the last
response's id; the workspace and the CLI's memory carry over. They can steer the running turn,
stop it, and download the workspace at any point.

```python
from openai import OpenAI
hi = OpenAI(api_key=KEY, base_url=f"{URL}/v1")
r = hi.responses.create(model="claude-code-devteam", input="Read the repo and propose a plan for issue 42.")
r = hi.responses.create(model="claude-code-devteam", input="Do step 1.", previous_response_id=r.id)
```

## An agent: many independent tasks

A service account runs tasks that share nothing: triage an issue, draft a summary, review a diff.
Each is `store: false` with its inputs as files; the answer is the output, and nothing accumulates.
Run them in parallel up to the org's `max_runs`.

```python
def triage(issue_text):
    r = hi.responses.create(model="triage", input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Label this issue and say why, as JSON."},
            {"type": "input_file", "filename": "issue.md", "file_data": issue_text}]}], store=False)
    return r.output_text
```

## A loop: until the checks pass

A loop is a session plus a stopping rule. A session runs one harness for its life, so a second
harness judges the work from the archive: here one harness implements in a stored session, and a
script harness runs the repository's own check statelessly on that session's workspace, until the
check passes or the budget runs out. The judge is a harness whose `request.sh` unpacks the tarball
it was given and runs `./check.sh`; see [the template](harness-template.md).

```python
import base64, httpx
http = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {KEY}"})

def judged(session_id):
    tar = http.get(f"/v1/sessions/{session_id}/archive").content
    return hi.responses.create(model="checks", store=False, input=[{"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": "workspace.tgz"},
        {"type": "input_file", "filename": "workspace.tgz",
         "file_data": "data:application/gzip;base64," + base64.b64encode(tar).decode()}]})

r = hi.responses.create(model="claude-code-devteam", input="Implement issue 42 so that ./check.sh passes.")
for attempt in range(5):
    verdict = judged(r.metadata["session_id"])
    if verdict.status == "completed":
        break
    r = hi.responses.create(model="claude-code-devteam", previous_response_id=r.id,
                            input=f"The check failed:\n{verdict.output_text[-4000:]}\nFix it.")
```

Simpler still: a `request.sh` that runs the check itself after the CLI and exits with its status,
so one session is the whole loop and the status is the verdict.

## A software factory

A repository carries its own loop definition. CI calls the API with a service key: a planning
harness in a stored session that a person steers, an implementing harness run statelessly from the
plan and the repository tarball, a review harness over the diff, and a push the sandbox makes with a
scoped deploy key the org put in `seeds/org`. Every artifact comes back as an archive or lands in
the repository. The trace of each session is the record of who asked what and what came back.

## Reading the output

The response carries exactly what the CLI printed. A harness that runs its CLI in a JSON mode gives
a program structure to work with: the final message, tool calls, token counts, whatever that CLI
reports. A harness that runs it in plain mode gives a person prose. Post-processing lives beside
the loop, not in the server, and it knows which CLI it is reading.
