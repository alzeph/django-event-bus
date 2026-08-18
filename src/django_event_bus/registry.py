from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

Receiver = Callable[..., None]

_registry: dict[str, list[Receiver]] = defaultdict(list)


def register(event_type: str, handler: Receiver) -> None:
    handlers = _registry[event_type]
    if handler not in handlers:
        # Idempotent: un double appel (double décoration, module importé
        # deux fois par un chemin non standard) ne doit pas faire tourner
        # le même receiver deux fois par événement reçu.
        handlers.append(handler)


def get_receivers(event_type: str) -> list[Receiver]:
    return list(_registry.get(event_type, []))


def registered_event_types() -> set[str]:
    return set(_registry.keys())


def clear() -> None:
    """Vide le registre. Utile entre deux tests."""
    _registry.clear()
