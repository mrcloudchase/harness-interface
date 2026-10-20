#!/usr/bin/env bash
# Installs the CLI, pinned, into $HI_TOOLS; executables end up in $HI_TOOLS/bin.
# Runs once per (this file + base image) in an install container: uid 1000, read-only root,
# writable $HI_TOOLS and /tmp ($HOME is a scratch dir in /tmp), egress only to install.egress
# through $HTTPS_PROXY, no secrets. The folder is mounted read-only at $HI_HARNESS_DIR.
# Any change to this file is a new tools dir; run.sh/adapter.py changes are not.
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
# 1. a pinned package from a declared install host (here npm; uv/pip/curl work the same way)
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund semver@7.6.3
# 2. the stand-in CLI itself, pinned by checksum like any download: editing standin.py fails the
#    install until this line changes, which is a new tools dir (the hash covers only this file)
echo "2c138be9b257894d92494cb0f57756bdfd7372d70250bba3c36d621ed658d618  $HI_HARNESS_DIR/standin.py" | sha256sum -c --quiet
install -m 0755 "$HI_HARNESS_DIR/standin.py" "$HI_TOOLS/bin/standin"
"$HI_TOOLS/bin/semver" --help >/dev/null
