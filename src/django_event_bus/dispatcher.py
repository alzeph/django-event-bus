from __future__ import annotations

import logging

from .brokers.base import BaseBroker
from .envelope import EventEnvelope
from .registry import get_receivers

logger = logging.getLogger("django_event_bus.dispatcher")


def dispatch(broker: BaseBroker, envelope: EventEnvelope) -> bool:
    """Exécute les receivers enregistrés pour `envelope`, puis ack/fail
    auprès du broker selon le résultat. Retourne True si le traitement a
    réussi (utilisé par le worker et testable indépendamment de lui).
    """
    succeeded = True
    for handler in get_receivers(envelope.event_type):
        try:
            handler(payload=envelope.payload, envelope=envelope)
        except Exception:
            logger.exception(
                "Échec du receiver %s pour l'événement %s (%s)",
                getattr(handler, "__name__", handler),
                envelope.event_type,
                envelope.event_id,
            )
            succeeded = False

    if succeeded:
        broker.ack(envelope)
    else:
        broker.fail(envelope)
    return succeeded
