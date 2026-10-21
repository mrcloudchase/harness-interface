# Development

```bash
uv sync --extra dev
uv run pytest                      # the suite without Docker: 48 tests in a few seconds
uv run pytest -m docker            # a real sandbox image: the tools layer, the variables, a steer, a cancel
uvx ruff check --select F,E9 .
```

The unit suite runs every layer with `tests/fakes.py`: a runtime that runs `request.sh` as a
process here, and `FakeRuntimes` that installs tools by running `install.sh` here. Nothing above
layer 4 can tell. `tests/test_api.py` drives every route, including the official OpenAI SDK as a
client.

The Docker tests need a daemon and pull `python:3.12-slim` and `python:3.12-alpine` once. Behind a
proxy that re-signs TLS, give them its CA bundle with `HI_CA_FILE`.

## The live script

`scripts/live.py` proves a registered harness against a running server, with real model calls:

```bash
uv run python scripts/live.py --url http://127.0.0.1:8000 --key hi_… --harness claude-code
```

It makes a file in a stored session, continues and checks recall, downloads the archive, streams a
turn, steers a long one, cancels one, reads the trace, and runs a stateless turn. The prompts are
plain English so any coding harness should pass. Run it before publishing a harness template and
after any change to layers 4 to 6.

## Where a change goes

| Change | Where |
|---|---|
| a new field in the wire format | `api/wire.py`, and its test |
| a new route | `api/app.py`, and `test_api.py` |
| what a turn is given or how it ends | `sessions.py`, `test_sessions.py`, and the user docs' template page |
| a new key in `harness.json` | `harness.py` (`load_config`, `Config.as_json`), `test_harness.py`, the template page |
| what a sandbox record holds | `store.py`, `sandboxes.py`, `test_store.py` |
| how a container is run | `runtimes/docker.py`, `test_docker.py` |
