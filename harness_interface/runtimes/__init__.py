"""Layer 1: the places things run. Each implements execution.Runtime and documents its own
guarantees; none is assumed to have another's."""
from .docker import ContainerExecution, DockerRuntime, Images, Provider, owner_of, signal

__all__ = ["ContainerExecution", "DockerRuntime", "Images", "Provider", "owner_of", "signal"]
