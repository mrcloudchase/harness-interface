#!/bin/sh
# Install harness-interface: the API server (`harness-interface`) and its command line (`hi`).
#
#   curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
#
# HI_REF picks what to install: a tag, a branch or a commit (default: main).
# It installs uv if it is missing, then the package from GitHub with `uv tool install`, which
# brings its own Python. Uninstall with `uv tool uninstall harness-interface`.
set -eu

REPO="https://github.com/mrcloudchase/harness-interface"
REF="${HI_REF:-main}"

say() { printf '%s\n' "$*"; }
fail() { say "install: $*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v git >/dev/null 2>&1 || fail "git is required: every workspace is a git repository.
Install it (apt install git, dnf install git, brew install git, or xcode-select --install), then run this again."

if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv, which installs and runs harness-interface..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv did not install; see https://docs.astral.sh/uv/"
fi

say "Installing harness-interface ($REF)..."
uv tool install --force --python 3.12 "harness-interface @ $REPO/archive/$REF.tar.gz"
uv tool update-shell >/dev/null 2>&1 || true

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  sandbox="Docker is running: every run gets its own sandbox."
else
  sandbox="Docker is not running. Start it for sandboxed runs, or run harnesses on this machine
directly with: HI_RUNTIME=local hi server start"
fi

say "
Installed: hi (the command line) and harness-interface (the API server).
$sandbox

Next:
  hi server start
  hi provider add anthropic --url https://api.anthropic.com --key-env ANTHROPIC_API_KEY
  hi harness add --builtin claude-code
  hi run claude-code \"What is 17 * 23?\"

If \`hi\` is not found, open a new terminal: uv put it in $(uv tool dir --bin 2>/dev/null || echo ~/.local/bin)."
