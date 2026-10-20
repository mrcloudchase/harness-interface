"""Layer 1: the places things run. Each implements execution.Runtime and documents its own
guarantees; none is assumed to have another's."""
from .local import LocalRuntime

__all__ = ["LocalRuntime"]
