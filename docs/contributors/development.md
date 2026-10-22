# Development

```bash
uv sync --extra dev
uv run pytest                      # the suite without Docker: SQLite and a directory, plus Postgres and S3 when reachable
uv run pytest -m docker            # the Docker tests: a real sandbox, the door, the forwarder, the runner
uvx ruff check --select F,E9 --target-version py311 .
```

The Postgres tests use `HI_TEST_POSTGRES` (default a local socket cluster) and skip when it is not
there; the S3 tests start a moto server. CI runs both backends with a Postgres service.

`tests/fakes.py` holds the test package (a `request.sh` that echoes its variables, a `response.sh`
that shapes them) and a `FakeNode` that runs turns as local processes, so everything above the
runtime is exercised end to end over ASGI in `test_api.py` with a real `Worker`.

To run the platform from a checkout: `uv run harness-interface init --tenant acme --owner me`, then
`uv run harness-interface serve`. `scripts/live.py` proves a package against it.

To verify the catalog against real providers, register them under the names the packages expect
(`deepseek`, `deepseek-openai`, `openai`, `openai-responses`), fork every package, and run
`scripts/live.py` over each; `scripts/catalog_verify.py` writes the results into each package's
`catalog.json` and regenerates `docs/users/harnesses/`.
