#!/usr/bin/env bash
# Runs once per package version, unprivileged, in the platform's base image (Debian, Python 3.12,
# Node 22, git, curl, ripgrep), with egress to install.egress only. Put the CLI under $HI_TOOLS;
# $HI_TOOLS/bin is on PATH at run time. Pin the version.
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
# npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "some-cli@1.2.3"
# python3 -m venv "$HI_TOOLS/venv" && "$HI_TOOLS/venv/bin/pip" install -q "some-cli==1.2.3" && ln -sf ../venv/bin/some-cli "$HI_TOOLS/bin/some-cli"
cat > "$HI_TOOLS/bin/echo-cli" <<'SH'
#!/bin/sh
printf 'echo-cli got: %s\n' "$*"
SH
chmod +x "$HI_TOOLS/bin/echo-cli"
