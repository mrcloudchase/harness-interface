# Conventions

- **Keep it simple.** The smallest code that does the job. No option nobody asked for.
- **Say each thing once.** One place knows each fact: the wire format is `wire.py`, the folder is
  `harness.py`, the layout is `store.py`.
- **One job per module, objects for state.** A module's docstring says its job in a paragraph; a
  class holds what changes.
- **Layers import downward only.** Nothing in `sessions.py` imports `api`; nothing in `harness.py`
  imports `store`.
- **Make what must never happen impossible.** The key is opened only in `_run`; a path is checked
  before it is a path; another org's thing is a 404, never a 403.
- **Tests first, fakes at the Docker line.** Every layer has a test; the Docker layer has the one
  that needs a daemon.
- **Docstrings say what and why, comments say why.** A comment that repeats the code is removed.
- **No em-dashes, no model identifiers, no keys** in anything committed.
