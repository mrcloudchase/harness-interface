# The built-in sandbox. Node and Python with the common harness CLIs, run as an unprivileged
# user named after the harness, whose home is inside the workspace so the harness's own state
# survives between turns. `{harness}` is filled in by the server, so each harness gets its own
# image from this file, differing only in that user.
# What locks it down is not in here but on every `docker run`: all capabilities dropped, no
# privilege escalation, read-only root, tmpfs /tmp, pid and memory caps, an internal network
# whose only exit is the egress door, gVisor when the host has it.
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git python3 python3-venv ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @anthropic-ai/claude-code @openai/codex @deepseek-ai/dsh \
 && npm cache clean --force \
 && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Last, on its own layer, so every harness's image shares the layers above and differs only here.
RUN useradd --create-home --uid 1000 --user-group {harness}
USER {harness}
ENV HOME=/workspace/.home
WORKDIR /workspace
