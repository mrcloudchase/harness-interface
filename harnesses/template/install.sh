#!/usr/bin/env bash
# Installs the CLI, pinned, into $HI_TOOLS; executables end up in $HI_TOOLS/bin.
# Runs once per (this file, image.Dockerfile, base image, CPU architecture) in an install container:
# uid 1000, read-only root, writable $HI_TOOLS (at its final path) and /tmp ($HOME is /tmp), egress
# only to install.egress through $HTTPS_PROXY, no secrets. The folder is mounted read-only at
# $HI_HARNESS_DIR. Any change to this file is a new tools directory; run.sh or adapter.py changes are not.
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
# 1. a pinned package from a declared install host (here npm; uv, pip and curl work the same way)
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund semver@7.6.3
"$HI_TOOLS/bin/semver" --help >/dev/null
# 2. the stand-in CLI itself, pinned by checksum like any download: editing standin.py fails the
#    install until this line changes, which is a new tools directory (only this file is hashed)
echo "4fd11b93945e5918951e01769ac8882b7f19be87e722462e275336766e302c4f  $HI_HARNESS_DIR/standin.py" | sha256sum -c --quiet
install -m 0755 "$HI_HARNESS_DIR/standin.py" "$HI_TOOLS/bin/standin"
