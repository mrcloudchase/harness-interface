#!/usr/bin/env bash
set -euo pipefail
printf '{"type":"text","text":%s}\n' "$(python3 -c 'import json,os;print(json.dumps("echo: "+os.environ["HI_TASK"]))')"
printf '{"type":"env","session_id_in":"%s","model":"%s","provider_url":"%s","where":"%s"}\n' "${HI_SESSION_ID:-}" "${HI_MODEL:-}" "${HI_PROVIDER_URL:-}" "${WHERE:-}"
echo "hello from echo" > hello.txt
printf '{"status":"ok","session_id":"echo-1","usage":{"input_tokens":1,"output_tokens":1},"answer":"echo: %s"}' "$HI_TASK" > "$HI_OUTPUT"
