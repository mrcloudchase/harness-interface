# The built-in sandbox: the CLI of every harness in harnesses/, pinned to the version each was
# tested with, run as an unprivileged user named after the harness, whose home is inside the
# workspace so the harness's own state survives between turns. `{harness}` is filled in by the
# server, so each harness gets its own image from this file, differing only in that last layer.
# What locks it down is not in here but on every `docker run`: all capabilities dropped, no
# privilege escalation, read-only root, tmpfs /tmp, pid and memory caps, an internal network
# whose only exit is the egress door, gVisor when the host has it.
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git python3 python3-pip python3-venv ca-certificates curl bzip2 xz-utils unzip \
 && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# CLIs published on npm
RUN npm install -g \
      @anthropic-ai/claude-code@2.1.42 @openai/codex@0.163.0 @deepseek-ai/dsh@0.2.0-rc.2 \
      @earendil-works/pi-coding-agent@1.3.0 @oh-my-pi/pi-coding-agent@18.12.0 gajae-code@0.18.12 \
      opencode-ai@1.19.3 @kilocode/cli@7.8.12 cline@3.0.73 @qwen-code/qwen-code@0.25.2 \
      @google/gemini-cli@0.64.0 @mimo-ai/cli@0.1.15 @minimax-ai/code@0.6.12 @qoder-ai/qodercli@1.1.73 \
 && npm cache clean --force

# CLIs published on PyPI, each in its own environment, on PATH for every user
ENV UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin UV_PYTHON_INSTALL_DIR=/opt/uv/python
RUN for t in "aider-chat==0.86.2" "hermes-agent[anthropic]==0.19.0" "openhands==1.16.0" \
             "nanobot-ai==0.3.5" "cheetahclaws==3.5.89" \
             "opensquilla[recommended] @ https://github.com/TokenRhythm/opensquilla/releases/download/v0.5.6/opensquilla-0.5.6-py3-none-any.whl"; do \
      uv tool install --python 3.12 "$t" || exit 1; done \
 && pip3 install --no-cache-dir --break-system-packages anthropic \
 && chmod -R a+rX /opt/uv

# CLIs with their own installers. Each lands somewhere under root's home; `found` stops the build
# if one is not where its installer said, and the binary is moved to where every user can run it.
RUN found() { p="$(command -v "$1" || find "$HOME" -name "$1" -type f -perm -u+x | head -1)" && [ -n "$p" ] && readlink -f "$p"; } \
 && export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH" \
 && curl -fsSL https://github.com/aaif-goose/goose/releases/download/stable/download_cli.sh \
      | CONFIGURE=false GOOSE_BIN_DIR=/usr/local/bin bash \
 && curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash \
 && k="$(found kimi)" && install -m755 "$k" /usr/local/bin/kimi \
 && curl -fsSL https://x.ai/cli/install.sh | bash \
 && g="$(found grok)" && install -m755 "$g" /usr/local/bin/grok \
 && curl -fsSL https://jcode.sh/install | bash \
 && j="$(found jcode)" && cp -r "$(dirname "$j")" /opt/jcode && ln -sf /opt/jcode/jcode /usr/local/bin/jcode \
 && chmod -R a+rX /opt/jcode \
 && for b in goose kimi grok jcode; do "$b" --version >/dev/null 2>&1 || { echo "$b does not run"; exit 1; }; done

# Bun, the runtime Gajae and OMP run on.
RUN npm install -g bun@1.4.2 && npm cache clean --force

# Last, on its own layer, so every harness's image shares the layers above and differs only here.
# The node image already has a `node` user at uid 1000; it makes way for the harness's.
RUN userdel -r node 2>/dev/null; useradd --create-home --uid 1000 --user-group {harness}
USER {harness}
ENV HOME=/workspace/.home
WORKDIR /workspace
