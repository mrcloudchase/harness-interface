#!/usr/bin/env bash
set -euo pipefail
VERSION=0.90.0
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/1jehuang/jcode/releases/download/v$VERSION/jcode-linux-$arch.tar.gz" -o "$tmp/jcode.tgz"
tar -xzf "$tmp/jcode.tgz" -C "$tmp"
rm -rf "$HG_TOOLS/jcode" && mkdir -p "$HG_TOOLS/jcode" "$HG_TOOLS/bin"
if [ -f "$tmp/jcode-linux-$arch.bin" ]; then
  install -m 755 "$tmp/jcode-linux-$arch" "$tmp/jcode-linux-$arch.bin" "$HG_TOOLS/jcode/"
  ln -sf "$HG_TOOLS/jcode/jcode-linux-$arch" "$HG_TOOLS/bin/jcode"
else
  install -m 755 "$tmp/jcode-linux-$arch" "$HG_TOOLS/bin/jcode"
fi
"$HG_TOOLS/bin/jcode" --version
