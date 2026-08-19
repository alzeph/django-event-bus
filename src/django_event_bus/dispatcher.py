"""Dispatch d'une enveloppe reçue vers les receivers enregistrés.

Dispatching a received envelope to the registered receivers.
"""

from __future__ import annotations

import logging

from .brokers.base import BaseBroker
from .envelope import EventEnvelope
from .registry import get_receivers

logger = logging.getLogger("django_event_bus.dispatcher")


def dispatch(broker: BaseBroker, envelope: EventEnvelope) -> bool:
    """Exécute les receivers de ``envelope``, puis ``ack``/``fail`` auprès du broker.

    Renvoie ``True`` si le traitement a réussi (utilisé par le worker, et
    testable indépendamment de lui).

    Runs ``envelope``'s receivers, then ``ack``/``fail``s with the broker.

    Returns ``True`` if the processing succeeded (used by the worker, and
    testable independently of it).
    """
    receivers = get_receivers(envelope.event_type)
    failed_count = 0
    for handler in receivers:
        try:
            handler(payload=envelope.payload, envelope=envelope)
        except Exception:
            logger.exception(
                "Échec du receiver %s pour l'événement %s (%s)",
                getattr(handler, "__name__", handler),
                envelope.event_type,
                envelope.event_id,
            )
            failed_count += 1

    succeeded = failed_count == 0
    if succeeded:
        broker.ack(envelope)
    else:
        if failed_count < len(receivers):
            # Le broker ne connaît que l'enveloppe, pas quel receiver a
            # échoué: une ré-émission relance TOUS les receivers, y
            # compris ceux ayant déjà réussi ci-dessus.
            #
            # The broker only knows about the envelope, not which
            # receiver failed: a redelivery re-runs ALL receivers,
            # including the ones that already succeeded above.
            logger.warning(
                "%s/%s receivers ont échoué pour %s (%s): la ré-émission "
                "relancera TOUS les receivers, y compris ceux ayant déjà "
                "réussi — assurez-vous qu'ils sont idempotents / "
                "%s/%s receivers failed for %s (%s): the redelivery will "
                "re-run ALL receivers, including ones that already "
                "succeeded — make sure they are idempotent.",
                failed_count,
                len(receivers),
                envelope.event_type,
                envelope.event_id,
                failed_count,
                len(receivers),
                envelope.event_type,
                envelope.event_id,
            )
        broker.fail(envelope)
    return succeeded
