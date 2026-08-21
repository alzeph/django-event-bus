"""Bus d'événements et récupération de données inter-services pour Django.

Inter-service event bus and data retrieval for Django.
"""

from .envelope import EventEnvelope
from .signals import RemoteSignal, receiver

__version__ = "1.0.0"

__all__ = ["EventEnvelope", "RemoteSignal", "__version__", "receiver"]
