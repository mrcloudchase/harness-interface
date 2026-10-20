"""Layer 1: the places things run. Each implements execution.Runtime and documents its own
guarantees; none is assumed to have another's."""
from .docker import DockerRuntime, Images, Provider, owner_of
from .local import LocalRuntime

__all__ = ["DockerRuntime", "Images", "LocalRuntime", "Provider", "owner_of"]
