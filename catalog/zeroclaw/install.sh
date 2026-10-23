#!/usr/bin/env bash
set -euo pipefail
VERSION=0.8.5
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/zeroclaw-labs/zeroclaw/releases/download/v$VERSION/zeroclaw-$arch-unknown-linux-gnu.tar.gz" -o "$tmp/zc.tgz"
tar -xzf "$tmp/zc.tgz" -C "$tmp" zeroclaw
mkdir -p "$HG_TOOLS/bin" && install -m 755 "$tmp/zeroclaw" "$HG_TOOLS/bin/zeroclaw"
"$HG_TOOLS/bin/zeroclaw" --version
