#!/usr/bin/env bash
# Installs OpenCode (sst), pinned, into $HI_TOOLS.
# 1. The opencode-ai npm package. Its postinstall hard-links the platform binary (optional dependency
#    opencode-linux-x64[-baseline]) to bin/opencode.exe, a self-contained executable; the two 178 MB
#    platform packages are then dead weight and are removed (355 MB -> 178 MB).
# 2. ripgrep 15.1.0, the version OpenCode would otherwise download from github.com at run time (its
#    grep and glob tools fail without it): the PyPI wheel, pinned by hash (linux x86_64 only).
# Egress: registry.npmjs.org, pypi.org, files.pythonhosted.org.
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund opencode-ai@1.19.3
rm -rf "$HI_TOOLS/lib/node_modules/opencode-ai/node_modules"
test "$("$HI_TOOLS/bin/opencode" --version)" = 1.19.3
echo "ripgrep==15.1.0 --hash=sha256:9b9bbd02a7f2c3e88882f9a9df416da8e272957071ba8ab59a7a7f06813643cf" > /tmp/rg.txt
python3 -m pip install --no-cache-dir --disable-pip-version-check --only-binary :all: --no-deps --require-hashes \
  ${REQUESTS_CA_BUNDLE:+--cert "$REQUESTS_CA_BUNDLE"} --target "$HI_TOOLS/ripgrep" -r /tmp/rg.txt
ln -sf ../ripgrep/bin/rg "$HI_TOOLS/bin/rg"
"$HI_TOOLS/bin/rg" --version | grep -q '^ripgrep 15.1.0'
