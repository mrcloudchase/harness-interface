#!/bin/sh
# Install harness-interface: the server (`harness-interface`) and the Python library it is built on.
#
#   curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
#
# It installs the latest release; HI_REF picks another: a tag, a branch or a commit. It installs uv
# if it is missing, then the package from GitHub with `uv tool install`, which brings its own Python.
# Uninstall with `uv tool uninstall harness-interface`.
set -eu

REPO="https://github.com/mrcloudchase/harness-interface"
API="https://api.github.com/repos/mrcloudchase/harness-interface"

say() { printf '%s\n' "$*"; }
fail() { say "install: $*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v git >/dev/null 2>&1 || fail "git is required: every workspace is a git repository.
Install it (apt install git, dnf install git, brew install git, or xcode-select --install), then run this again."

REF="${HI_REF:-$(curl -fsSL "$API/releases/latest" 2>/dev/null | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)}"
REF="${REF:-main}"

if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv, which installs and runs harness-interface..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv did not install; see https://docs.astral.sh/uv/"
fi

say "Installing harness-interface ($REF)..."
uv tool install --force --python 3.13 "harness-interface[server] @ $REPO/archive/$REF.tar.gz"
uv tool update-shell >/dev/null 2>&1 || true

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  sandbox="Docker is running: every response gets its own sandbox."
else
  sandbox="Docker is not running. Start it for sandboxed sessions, or run harnesses on this machine
directly, with no sandbox: HI_RUNTIME=local harness-interface"
fi

say "
Installed: harness-interface, the server.
$sandbox

Next: run \`harness-interface\`, then follow
  https://github.com/mrcloudchase/harness-interface/blob/main/docs/users/getting-started.md

If \`harness-interface\` is not found, open a new terminal: uv put it in $(uv tool dir --bin 2>/dev/null || echo ~/.local/bin)."
