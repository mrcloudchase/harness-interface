#!/usr/bin/env bash
# OpenCode, pinned. The opencode-ai wrapper's postinstall (offline) hard-links the platform binary, a
# self-contained Bun executable, from its optional package to bin/opencode.exe; the platform packages
# are then dead weight (355 MB -> 178 MB) and go. ripgrep is what OpenCode would otherwise fetch from
# github.com the first time its grep or glob tool runs (both fail without it): the PyPI wheel, pinned
# by hash (linux x86_64), installed by uv. Egress: registry.npmjs.org, pypi.org, files.pythonhosted.org.
set -euo pipefail
VERSION=1.19.3
RIPGREP="ripgrep==15.1.0 --hash=sha256:9b9bbd02a7f2c3e88882f9a9df416da8e272957071ba8ab59a7a7f06813643cf"
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "opencode-ai@$VERSION"
rm -rf "$HI_TOOLS/lib/node_modules/opencode-ai/node_modules"
got=$("$HI_TOOLS/bin/opencode" --version)
[[ "$got" == "$VERSION" ]] || { echo "install.sh: expected opencode $VERSION, got: $got" >&2; exit 1; }
echo "$RIPGREP" > /tmp/ripgrep.txt
uv pip install --no-cache --only-binary :all: --no-deps --require-hashes --target "$HI_TOOLS/ripgrep" -r /tmp/ripgrep.txt
ln -sf ../ripgrep/bin/rg "$HI_TOOLS/bin/rg"
"$HI_TOOLS/bin/rg" --version | grep -q '^ripgrep 15.1.0'
