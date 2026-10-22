#!/usr/bin/env bash
set -euo pipefail
VERSION=0.90.0
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/1jehuang/jcode/releases/download/v$VERSION/jcode-linux-$arch.tar.gz" -o "$tmp/jcode.tgz"
tar -xzf "$tmp/jcode.tgz" -C "$tmp"
rm -rf "$HI_TOOLS/jcode" && mkdir -p "$HI_TOOLS/jcode" "$HI_TOOLS/bin"
if [ -f "$tmp/jcode-linux-$arch.bin" ]; then
  install -m 755 "$tmp/jcode-linux-$arch" "$tmp/jcode-linux-$arch.bin" "$HI_TOOLS/jcode/"
  ln -sf "$HI_TOOLS/jcode/jcode-linux-$arch" "$HI_TOOLS/bin/jcode"
else
  install -m 755 "$tmp/jcode-linux-$arch" "$HI_TOOLS/bin/jcode"
fi
"$HI_TOOLS/bin/jcode" --version
