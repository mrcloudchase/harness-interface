#!/usr/bin/env bash
set -euo pipefail
VERSION=1.50.0
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/aaif-goose/goose/releases/download/v$VERSION/goose-$arch-unknown-linux-gnu.tar.gz" -o "$tmp/goose.tgz"
tar -xzf "$tmp/goose.tgz" -C "$tmp"
mkdir -p "$HI_TOOLS/bin" && install -m 755 "$tmp/goose" "$HI_TOOLS/bin/goose"
"$HI_TOOLS/bin/goose" --version
