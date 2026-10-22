#!/usr/bin/env bash
set -euo pipefail
VERSION=2.0.0
case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai%2Fkimi-code%40$VERSION/kimi-code-linux-$arch.tar.gz" -o "$tmp/kimi.tgz"
mkdir "$tmp/x" && tar -xzf "$tmp/kimi.tgz" -C "$tmp/x"
bin=$(find "$tmp/x" -type f -name kimi -perm -u+x | head -n 1)
mkdir -p "$HI_TOOLS/bin" && install -m 755 "$bin" "$HI_TOOLS/bin/kimi"
"$HI_TOOLS/bin/kimi" --version
