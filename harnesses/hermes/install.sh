#!/usr/bin/env bash
# Hermes Agent (NousResearch), pinned, with the Anthropic SDK, the ACP server and the MCP client
# (without the `mcp` extra hermes silently skips config.yaml's mcp_servers). Its venv lives in
# $HI_TOOLS/uv/hermes-agent on the base image's python3 (the base image id is part of the tools
# directory's hash); its dependencies are frozen by date, so a re-install resolves the same set; the
# bytecode is compiled now, since the tools directory is read-only at run time. Egress: PyPI.
set -euo pipefail
VERSION=0.19.0
mkdir -p "$HI_TOOLS/bin"
export UV_TOOL_DIR="$HI_TOOLS/uv" UV_TOOL_BIN_DIR="$HI_TOOLS/bin" UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 \
       UV_NO_CACHE=1
uv tool install --exclude-newer 2026-10-19T00:00:00Z "hermes-agent[anthropic,acp,mcp]==$VERSION"
got=$("$HI_TOOLS/bin/hermes" --version)
[[ "$got" == "Hermes Agent v$VERSION "* ]] || { echo "install.sh: expected $VERSION, got: ${got%%$'\n'*}" >&2; exit 1; }
"$HI_TOOLS/uv/hermes-agent/bin/python" -c 'import acp, anthropic, mcp'
