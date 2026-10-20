# hi-base: the one image every install and session container starts from.
# No CLI, no secret, no network config: only what installs and adapters need.
#   python3 (adapters, uv tools), node + npm (npm-installed CLIs), uv (python CLIs), git, bash,
#   ca-certificates; user `hi` uid/gid 1000. tini is not here: `docker run --init` supplies it.
# Every input is pinned, so the image id (part of every tools-dir hash) only moves on purpose.
# No https fetch at build time: binaries come from pinned images, packages from the Debian mirror.
FROM node:22.23.3-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.12.15-slim-trixie
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /var/log/apt /var/log/dpkg.log \
 && groupadd -g 1000 hi && useradd -u 1000 -g 1000 -M -d /nonexistent -s /bin/bash hi
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=uv /uv /uvx /usr/local/bin/
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version && npm --version && uv --version && python3 --version && git --version
ENV LANG=C.UTF-8 UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 NPM_CONFIG_UPDATE_NOTIFIER=false NPM_CONFIG_FUND=false
USER 1000:1000
