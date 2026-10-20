# MiniMax Code — mcode 0.6.12 (pin: @minimax-ai/code@0.6.12)

**Verdict:** works. Headless `exec` stream-json and `acp` both run on DeepSeek's /anthropic. The only catch is the key: `provider add` writes it into `$HOME/.minimax/config.yaml`. Fix: keep the config in /tmp.
**Tier:** steered. Over `mcode acp`, the `mcode/session/steer` request (`{sessionId,text}`) landed mid-turn: the result was `{"mode":"steered"}`, counting stopped at 3 and done.txt read DONE.

## Inputs
- Headless: `mcode exec [prompt]`, or `--input -` (reads all of stdin once; `--input-format text|json`). Other flags: `--cwd <dir>`, `--model <provider/model>` (custom providers are `custom_provider:<name>/<model>`), `--effort`, `--session <id>` / `--continue`, `--config <file>`, `--timeout 30s|2m`, `--max-steps N`, `--output-format text|json|stream-json`, `-o/--output-last-message <file>`, `--output-schema`, `--append-system-prompt[-file]`, `--system-prompt[-file]`, `--file <path>` (repeatable).
- Permissions: `--permission smart|full|off` (default smart; `ask` is refused in exec). `off` means "Permission mode off allows local tool calls": no checks at all. In ACP the permission mode comes from `permissionMode` in config.yaml (`"off"` works). With no config, the default is `auto`, which never asked for permission in my tests.
- Instructions: reads `AGENTS.md` and `CLAUDE.md` from the workspace. Both were loaded and followed: the ZEBRA-42 suffix, and "answer in uppercase" from CLAUDE.md. In the first trivial run the model ignored AGENTS.md; it followed it when asked about it.

## Provider
- Speaks three shapes: `anthropic-messages`, `openai-completions`, `openai-responses` (`provider add --api-format`).
- Anthropic shape: it appends `/v1/messages` and strips a trailing `/v1` or `/messages`, so a base URL works with or without `/v1`. OpenAI shapes: it appends `/chat/completions` or `/responses`, so the base URL should end in `/v1`.
- No login is needed for a custom provider. With no provider selected, it demands a MiniMax login.
- The key goes into config.yaml as a literal `custom_provider.<name>.options.apiKey`. `provider add --api-key-env VAR` only reads VAR once, at add time (default VAR is `MCODE_PROVIDER_API_KEY`). There is no env reference at runtime.
- The model must be listed under `models:` in the config. Any other model fails with exit 4: "not available for the custom_provider route".
- A handwritten config works: `defaultModel`, `permissionMode`, `dataContribution.enabled:false`, `custom_provider.hi{kind:custom,enabled:true,api:anthropic-messages,options{baseURL,authMode:api-key,apiKey},models{deepseek-chat:{}}}`.
- To keep the key out of the workspace:
  - exec: `exec --config /tmp/x.yaml`. That config is used and HOME gets no config.yaml.
  - ACP (which has no `--config`): a symlink `$HOME/.minimax/config.yaml -> /tmp/x.yaml`. It is read and never rewritten (md5 unchanged).
- Honors `HTTPS_PROXY`/`https_proxy` (CONNECT; verified through a logging proxy).
- Startup also calls `agent.minimax.cn` (config, telemetry, error reports, skill hub) on every run, and once called `filecdn.minimax.chat` (models.dev catalog mirror). With only api.deepseek.com allowed, all of those were denied and runs still succeeded with no visible delay (PONG in 5.8s). I found no switch that turns them off. `dataContribution.enabled:false` did not stop the agent.minimax.cn calls.
- **Key leaks to tools:** the bash tool's environment contains `HI_PROVIDER_KEY` and `MCODE_PROVIDER_API_KEY` (printenv showed both names). So the key should be stripped from mcode's environment after the config is written.

## Artifacts it loads
- Data dir is `$HOME/.minimax` (override: `MINIMAX_DATA_DIR`).
- Skills, all four verified loaded: `~/.minimax/skills/<n>/SKILL.md`, `<ws>/.minimax/skills`, `<ws>/.claude/skills`, `<ws>/.agents/skills`. Also `~/.minimax/agents/<agent>/skills` (from source).
- MCP: project `<ws>/.mcp.json` (README) and `mcp.json` in the data dir (source). Not tested.
- Hooks only come through plugins (`hooks/hooks.json`, Claude/Codex plugin format, `mcode plugin add`). Not tested.
- Built-in skills and agents are unpacked into `~/.minimax/.builtin-skills` and `agents/.builtin` on first run (about 17 MB).

## Outputs
- `--output-format stream-json` writes NDJSON. Every event carries `schemaVersion, sequence, timestampMs, runId, sessionId, turnId, type`.
- Event types: `exec.started`, `session.started` or `session.resumed`, `turn.started`, `item.started|updated|completed`, `turn.completed` (usage) or `turn.failed` (`status: cancelled`, or `error`), and `exec.completed`.
  - `item.type` is `agent_message` (`contentDelta`, then `content`), `reasoning`, or `tool_call` (`toolCall{name,input,output,status}`).
  - `exec.completed.result` holds `{status: succeeded|failed|cancelled, output, error{category,message,retryable}, usage{inputTokens,outputTokens,cacheReadTokens,totalTokens}, usageIncomplete, durationMs, model}`.
- No cost in exec. In ACP, `usage_update` has `cost.amount: 0`.
- Resume id: `sessionId` (`mvs_…`) is on the very first line (`exec.started`), before any model call.
- Exit codes: 0 succeeded; 4 failed (bad model, or bad key after about 30 s of retries); 130 cancelled by SIGINT. Errors also go to stderr ("mcode exec failed: …").
- ACP:
  - Standard `session/update` kinds: `agent_message_chunk`, `agent_thought_chunk`, `tool_call`, `tool_call_update`, `usage_update{used,size,cost}`, `session_info_update`, `available_commands_update`.
  - `session/prompt` returns `{stopReason: end_turn|cancelled}`; `session/new` returns `sessionId`.

## State it keeps
- Everything lives under `$HOME/.minimax`:
  - sessions: `v2/sessions/YYYY/MM/DD/<time>-session_<b64>/{messages.jsonl,manifest.json,llm-call.json,…}`
  - SQLite: `v2/sqlite/runtime-state.sqlite`
  - logs: `v2/observability/{logs,events,mcode}`
  - background-task outputs: `background-tasks/`
  - other: `model-cache.json`, `shims/rm`, `bin/mavis-trash`
- No key found outside config.yaml.
- It wrote nothing into the workspace apart from the task's own files.

## Continue
`exec --session <id>` resumes; `--continue` resumes the latest session in `--cwd`. Run 1 "Remember the word ORCHID. Reply OK." got "OK". Run 2 with `--session mvs_e47d…` got "ORCHID." and a `session.resumed` event. Sessions cross modes: an ACP session resumed fine in exec ("ORCHID"), and exec sessions can be reopened with ACP `session/resume` or `session/load`. ACP `session/resume {sessionId,cwd,mcpServers}`, then a prompt, got "ORCHID".

## Mid-turn steering
- `mcode acp` is JSON-RPC over stdio, ACP protocolVersion 1. `initialize` advertises `_meta["minimax-code/extensions"].methods`, which include:
  - `mcode/session/steer`
  - `mcode/session/queue/{list,enqueue,update,delete,steer}`
  - `session/cancel` (a standard notification)
- Steer request: `{"method":"mcode/session/steer","params":{"sessionId":S,"text":T,"clientRequestId"?:K}}`. It returns `{turnId, mode:"steered"}`.
- It works only while a `session/prompt` turn is active and admitted. Otherwise it throws invalidParams ("Steering requires an admitted, active ACP prompt Turn"), and it never starts a new turn.
- Test: steer sent at count 3 (13.0 s). The reply came at once, the prompt ended `end_turn` at 17.5 s, count.txt stayed at 1–3, and done.txt read `DONE`.
- In exec mode there is no live input (`--input -` reads stdin once).

## Graceful stop
- ACP `session/cancel` (notification) at count 3: the prompt returned `{stopReason:"cancelled"}` in 0.04 s and counting stopped at 3. Resumed in exec, it named the counting, "1 and 2 succeeded, 3 aborted".
- ACP process, SIGINT to its process group: exits 0 in 0.21 s *without* answering the pending prompt. Closing stdin: exits 0 in 0.22 s. In both cases the session was saved, and resuming named counting and numbers 1–2 (3 uncertain).
- exec, SIGINT to its process group at count 3: exit 130 in 0.26 s. Last events: `turn.failed{status:cancelled}`, then `exec.completed{status:cancelled, usage, usageIncomplete:true}`. No further numbers were written. The resumed run said "numbers 1 and 2… the third… aborted… 4–30 never attempted". Pass.

## Worst case
Not needed. Every stop path saves the session, and resume works. If the session store were lost, `messages.jsonl` under `v2/sessions/…` is a full transcript that could be handed back.

## The folder we should ship
- **harness.json:**
  - provider `deepseek` (any Anthropic Messages endpoint; an OpenAI one would need `api: openai-completions|openai-responses` and a `/v1` base)
  - `files: {"AGENTS.md": "{instructions}"}`
  - `run.env.HOME={workspace}/.home`
  - `run.stdout: application/x-ndjson`
  - `run.interrupt: "steered"`
- **run.sh:**
  1. Install the artifacts.
  2. `umask 077`; write `/tmp/mcode-config.yaml` (handwritten yaml as above, with `defaultModel: custom_provider:hi/$model`, the `$model` entry under `models:`, `permissionMode: "off"`, `dataContribution.enabled: false`, apiKey from `HI_PROVIDER_KEY`).
  3. `ln -sf /tmp/mcode-config.yaml $HOME/.minimax/config.yaml`, and trap-remove the file on exit.
  4. Start `exec env -u HI_PROVIDER_KEY python3 adapter.py`, which runs `mcode acp` in cwd `$HI_WORKSPACE`.
- **adapter.py:**
  - Send `initialize`, then `session/resume{sessionId:$HI_RESUME,cwd,mcpServers:[]}` if `HI_RESUME` is set, else `session/new`.
  - Optionally `session/set_config_option{configId:"model",…}`.
  - Send `session/prompt` with stdin line 1's task.
  - Each later stdin line (a JSON string) becomes `mcode/session/steer`. If that errors (turn not yet admitted, or already over), queue the text and send it as the next `session/prompt` once the current one returns.
  - On SIGINT or stdin EOF, send `session/cancel`, wait for `stopReason`, then close stdin.
  - Translate `session/update` notifications into NDJSON on stdout, and answer `session/request_permission` with allow, as a safety net.
  - Fallback for the `continued` tier: `mcode exec --output-format stream-json --permission off --cwd "$HI_WORKSPACE" ${HI_RESUME:+--session "$HI_RESUME"} --config /tmp/mcode-config.yaml "$HI_TASK"`.
- **report.py:**
  - Pass lines through unchanged.
  - resume: the `sessionId` from `session/new`, or the first exec event. Write `HI_OUTPUT` early, as soon as it is known.
  - answer: concatenated `agent_message_chunk` text (exec: `exec.completed.result.output`).
  - status: `stopReason` end_turn → ok, cancelled → cancelled (exec: `result.status`).
  - usage: `usage_update` (exec: `result.usage`).
  - cost_usd: `usage_update.cost.amount` (0 for BYOK), else null.
- **artifacts:** skills → `.minimax/skills/<n>/SKILL.md`; MCP → `.minimax/mcp.json` (untested); plugins/hooks via `.minimax/plugins` (untested). Workspace `.mcp.json` and `.claude/skills` are also read.
- **Changes from today's folder:**
  - It runs `provider add --api-key-env HI_PROVIDER_KEY`, which **persists the key in `.home/.minimax/config.yaml` inside the workspace**, and it leaves `HI_PROVIDER_KEY` visible to the agent's shell.
  - It uses `HI_SESSION_ID` instead of `HI_RESUME`.
  - report.py writes `session_id` instead of `resume`, writes only at the end (not early), has no `cost_usd`, and treats cancelled as fail.
  - It has no `run.interrupt` or adapter: exec is only the `continued` tier, while ACP steering works.

## Evidence
- Runs went through a logging CONNECT proxy that allowed only api.deepseek.com. HOME was fresh each time; model `custom_provider:hi/deepseek-chat`.
- `provider add … --use`: exit 0, key found in config.yaml (only there).
- `exec … "Reply with the single word PONG."`: 8 events, PONG, exit 0, 5.8 s. minimax hosts denied without harm.
- `exec --config /tmp-ish/config.yaml`: works, and no config.yaml is created in HOME.
- ORCHID: run 1 "OK", run 2 `--session` "ORCHID." (`session.resumed`).
- exec counting + `killpg SIGINT` at count 3 (t=12.4 s): exit 130 after 0.26 s, count 3 three seconds later. Resume named counting, 1–2 done, 3 aborted.
- ACP counting + `mcode/session/steer` at count 3: reply `{"mode":"steered"}`, `stopReason end_turn` 4.5 s later, count 3, done.txt=DONE.
- ACP `session/cancel` at count 3: `stopReason cancelled` in 0.04 s, count 3. Exec resume of that ACP session named the counting and numbers.
- ACP SIGINT: exit 0 in 0.21 s, prompt never answered. ACP stdin EOF: exit 0 in 0.22 s. Sessions resumable afterwards.
- ACP `session/resume` of an ACP session (via the symlinked config): ORCHID.
- Bad model: exit 4 at once. Bad key: exit 4 after 32 s (401, retryable). Skills test: all 4 dirs listed; CLAUDE.md loaded. printenv in the tool showed `HI_PROVIDER_KEY` and `MCODE_PROVIDER_API_KEY`.
- Key-bearing files were deleted afterwards (all test HOMEs and /tmp-style configs under work/).
