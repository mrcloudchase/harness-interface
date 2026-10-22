# The platform image: every role in one image, chosen at run time with `--role`. Python, the package,
# the console and the catalog; the Docker CLI for the worker role (it talks to the host's daemon
# through the socket you mount). Nothing of any harness is in it: packages install their CLI into
# the tools layer, under the tenant's terms, at first use.
FROM python:3.12-slim-bookworm AS build
RUN pip install --no-cache-dir uv
WORKDIR /src
COPY pyproject.toml uv.lock README.md CHANGELOG.md ./
COPY harness_interface ./harness_interface
COPY catalog ./catalog
COPY console ./console
RUN uv build --wheel --out-dir /dist

FROM python:3.12-slim-bookworm
ARG DOCKER_VERSION=27.5.1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && arch="$(uname -m)" && curl -fsSL "https://download.docker.com/linux/static/stable/${arch}/docker-${DOCKER_VERSION}.tgz" \
       | tar -xz --strip-components=1 -C /usr/local/bin docker/docker
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
ENV HI_HOST=0.0.0.0 HI_PORT=8000 HI_DATA_DIR=/data
VOLUME /data
EXPOSE 8000 8081
HEALTHCHECK --interval=15s --timeout=5s CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
ENTRYPOINT ["harness-interface"]
CMD ["serve", "--role", "all"]
