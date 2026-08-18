"""``RemoteSignal`` (émission) et ``receiver`` (abonnement).

``RemoteSignal`` (emission) and ``receiver`` (subscription).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db import transaction

from .envelope import EventEnvelope
from .registry import register
from .settings import app_settings


class RemoteSignal:
    """Point d'émission d'un événement inter-services.

    S'utilise comme un `django.dispatch.Signal`: déclaré une fois au
    niveau module, puis on appelle `.send(...)`. Contrairement à un
    signal Django classique, les abonnés ne sont pas des callbacks
    Python enregistrés sur *cette instance* mais n'importe quel service
    ayant un `@receiver(event_type)` sur le même nom d'événement.

    Inter-service event emission point.

    Used like a `django.dispatch.Signal`: declared once at module level,
    then called via `.send(...)`. Unlike a regular Django signal, the
    subscribers are not Python callbacks registered on *this instance*
    but any service with a `@receiver(event_type)` on the same event
    name.
    """

    def __init__(self, event_type: str) -> None:
        """Déclare le nom d'événement émis par cette instance.

        Declares the event name emitted by this instance.
        """
        self.event_type = event_type

    def send(
        self, payload: dict[str, Any] | None = None, **extra: Any
    ) -> EventEnvelope:
        """Construit l'enveloppe, publiée à la validation de la transaction en cours.

        Publié à la validation de la transaction en cours (immédiatement
        s'il n'y en a pas): sans ça, un `send()` fait depuis un
        `post_save` publierait pour une ligne pas encore (ou jamais)
        committée si la transaction englobante échoue ensuite — et
        inversement, une panne du broker ferait échouer une écriture DB
        qui n'a rien à voir avec l'événement.

        Builds the envelope and schedules its publication at transaction commit.

        Published when the current transaction commits (immediately if
        there is none): without this, a `send()` call made from a
        `post_save` would publish for a row that is not yet (or never)
        committed if the enclosing transaction later fails — and
        conversely, a broker outage would fail an unrelated DB write.
        """
        from .brokers.utils import get_broker

        envelope = EventEnvelope(
            event_type=self.event_type,
            source_service=app_settings.SERVICE_NAME,
            payload={**(payload or {}), **extra},
        )
        transaction.on_commit(lambda: get_broker().publish(envelope))
        return envelope


def receiver(event_type: str) -> Callable[[Callable], Callable]:
    """Décorateur d'abonnement à un `event_type`.

    L'abonnement se fait par nom d'événement (string), pas par import de
    l'objet `RemoteSignal` du service émetteur: un service consommateur
    n'a en général pas accès au code du service producteur.

        @receiver("auth.user_created")
        def on_user_created(payload, envelope, **kwargs):
            ...

    Decorator subscribing to an `event_type`.

    The subscription is by event name (string), not by importing the
    emitting service's `RemoteSignal` object: a consuming service
    generally has no access to the producing service's code.

        @receiver("auth.user_created")
        def on_user_created(payload, envelope, **kwargs):
            ...
    """

    def decorator(func: Callable) -> Callable:
        register(event_type, func)
        return func

    return decorator
