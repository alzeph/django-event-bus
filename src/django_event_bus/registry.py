"""Registre des receivers abonnés par type d'événement.

Registry of receivers subscribed per event type.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

Receiver = Callable[..., None]

_registry: dict[str, list[Receiver]] = defaultdict(list)


def register(event_type: str, handler: Receiver) -> None:
    """Abonne ``handler`` à ``event_type`` (idempotent).

    Un double appel (double décoration, module importé deux fois par un
    chemin non standard) ne fait pas tourner le même receiver deux fois
    par événement reçu.

    Subscribes ``handler`` to ``event_type`` (idempotent).

    A duplicate call (double decoration, module imported twice through a
    non-standard path) does not run the same receiver twice per received
    event.
    """
    handlers = _registry[event_type]
    if handler not in handlers:
        handlers.append(handler)


def get_receivers(event_type: str) -> list[Receiver]:
    """Renvoie les receivers abonnés à ``event_type``.

    Returns the receivers subscribed to ``event_type``.
    """
    return list(_registry.get(event_type, []))


def registered_event_types() -> set[str]:
    """Renvoie l'ensemble des types d'événements ayant au moins un receiver.

    Returns the set of event types having at least one receiver.
    """
    return set(_registry.keys())


def clear() -> None:
    """Vide le registre.

    Utile entre deux tests.

    Clears the registry.

    Useful between tests.
    """
    _registry.clear()
