#!/usr/bin/env bash
set -euo pipefail
VERSION=1.0.41
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
mkdir -p "$HG_TOOLS/bin"
curl -fsSL "https://x.ai/cli/grok-$VERSION-linux-$arch" -o "$HG_TOOLS/bin/grok" \
  || curl -fsSL "https://storage.googleapis.com/grok-build-public-artifacts/cli/grok-$VERSION-linux-$arch" -o "$HG_TOOLS/bin/grok"
chmod 755 "$HG_TOOLS/bin/grok"
"$HG_TOOLS/bin/grok" --version
