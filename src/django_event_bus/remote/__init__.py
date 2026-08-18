"""Récupération de données inter-services (``RemoteForeignKey``).

Inter-service data retrieval (``RemoteForeignKey``).
"""

from ..exceptions import RemoteServiceMisconfiguredError, RemoteServiceUnavailableError
from .fields import RemoteForeignKey
from .objects import RemoteObject

__all__ = [
    "RemoteForeignKey",
    "RemoteObject",
    "RemoteServiceMisconfiguredError",
    "RemoteServiceUnavailableError",
]
