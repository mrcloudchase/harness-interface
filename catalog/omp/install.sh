#!/usr/bin/env bash
set -euo pipefail
VERSION=18.1.13
case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
mkdir -p "$HI_TOOLS/bin"
curl -fsSL "https://github.com/can1357/oh-my-pi/releases/download/v$VERSION/omp-linux-$arch" -o "$HI_TOOLS/bin/omp"
chmod 755 "$HI_TOOLS/bin/omp"
"$HI_TOOLS/bin/omp" --version
