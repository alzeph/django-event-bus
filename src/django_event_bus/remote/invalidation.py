"""Invalidation du cache de données distantes pilotée par le bus d'événements.

Event-bus-driven invalidation of the remote data cache.
"""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Iterable
from typing import Any

from ..registry import register
from .cache import get_cache, remote_cache_key

logger = logging.getLogger("django_event_bus.remote.invalidation")

_wired: set[tuple[str, str, str]] = set()
_wired_lock = threading.Lock()


def register_invalidation(
    service: str, resource: str, event_types: Iterable[str]
) -> None:
    """Invalide le cache de ``(service, resource)`` à réception de ``event_types``.

    Enregistre, une seule fois par triplet ``(service, resource,
    event_type)`` même si plusieurs champs ``RemoteForeignKey`` visent la
    même ressource, un receiver sur le bus d'événements du volet 1
    (``registry.register``, déjà idempotent) qui supprime l'entrée de
    cache correspondante. Le PK à invalider est lu dans
    ``payload["id"]`` — convention déjà respectée par les événements
    métier du bus (ex. ``auth.user_created``).

    Invalidates the ``(service, resource)`` cache upon receiving any of
    ``event_types``.

    Registers, only once per ``(service, resource, event_type)`` triple
    even if several ``RemoteForeignKey`` fields target the same resource,
    a receiver on the volet-1 event bus (``registry.register``, already
    idempotent) that deletes the matching cache entry. The PK to
    invalidate is read from ``payload["id"]`` — a convention already
    followed by the bus's business events (e.g. ``auth.user_created``).
    """
    with _wired_lock:
        for event_type in event_types:
            key = (service, resource, event_type)
            if key in _wired:
                continue
            _wired.add(key)
            register(event_type, functools.partial(_invalidate, service, resource))


def _invalidate(
    service: str, resource: str, *, payload: dict[str, Any], **kwargs: Any
) -> None:
    """Supprime du cache l'entrée désignée par ``payload["id"]``, si présent.

    Deletes the cache entry designated by ``payload["id"]``, if present.
    """
    pk = payload.get("id")
    if pk is None:
        logger.warning(
            "Événement d'invalidation pour %s.%s sans 'id' dans le payload, ignoré / "
            "invalidation event for %s.%s missing 'id' in payload, ignored",
            service,
            resource,
            service,
            resource,
        )
        return
    get_cache().delete(remote_cache_key(service, resource, pk))
