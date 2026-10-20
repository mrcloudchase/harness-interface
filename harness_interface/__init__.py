"""harness-interface: run any coding harness in a locked-down sandbox.

The library's public API is layers 0 to 5, so Python callers need no server; the server (layer 6,
`harness_interface.api`) is built on it."""
from .errors import Conflict, Invalid, NotFound

__all__ = ["Conflict", "Invalid", "NotFound"]
