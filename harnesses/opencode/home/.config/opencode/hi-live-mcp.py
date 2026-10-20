"""An example MCP server from the harness folder: stdio, one tool, `hi-live-mcp`, that returns a word."""
import json
import sys

TOOL = {"name": "hi-live-mcp", "description": "Returns the MCP word.",
        "inputSchema": {"type": "object", "properties": {}}}

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:                          # a notification: nothing to answer
        continue
    method, params = message.get("method"), message.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "hi-live", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "The MCP word is OTTER."}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
