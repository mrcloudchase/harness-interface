#!/usr/bin/env bash
# Hermes Agent (NousResearch), pinned, with the Anthropic SDK and the ACP server, into $HI_TOOLS.
# The venv lives in $HI_TOOLS/uv/hermes-agent and runs on the base image's python3.12 (the base
# image id is part of the tools-dir hash); a Python uv would download goes in $HI_TOOLS/python.
# Transitive deps are frozen by date (--exclude-newer), so a re-install resolves the same set.
# Bytecode is compiled now: the tools dir is read-only at run time.
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
export UV_TOOL_DIR="$HI_TOOLS/uv" UV_TOOL_BIN_DIR="$HI_TOOLS/bin" UV_PYTHON_INSTALL_DIR="$HI_TOOLS/python" \
       UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1
uv tool install --exclude-newer 2026-10-19T00:00:00Z 'hermes-agent[anthropic,acp]==0.19.0'
"$HI_TOOLS/bin/hermes" --version
"$HI_TOOLS/uv/hermes-agent/bin/python" -c 'import acp, anthropic'
