#!/usr/bin/env bash
# Runs once per package version, unprivileged, in the platform's base image (Debian, Python 3.12,
# Node 22, git, curl, ripgrep), with egress to install.egress only. Put the CLI under $HG_TOOLS;
# $HG_TOOLS/bin is on PATH at run time. Pin the version.
set -euo pipefail
mkdir -p "$HG_TOOLS/bin"
# npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "some-cli@1.2.3"
# python3 -m venv "$HG_TOOLS/venv" && "$HG_TOOLS/venv/bin/pip" install -q "some-cli==1.2.3" && ln -sf ../venv/bin/some-cli "$HG_TOOLS/bin/some-cli"
cat > "$HG_TOOLS/bin/echo-cli" <<'SH'
#!/bin/sh
printf 'echo-cli got: %s\n' "$*"
SH
chmod +x "$HG_TOOLS/bin/echo-cli"
