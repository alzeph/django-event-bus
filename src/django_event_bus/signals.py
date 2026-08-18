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
    """

    def __init__(self, event_type: str):
        self.event_type = event_type

    def send(self, payload: dict[str, Any] | None = None, **extra: Any) -> EventEnvelope:
        from .brokers.utils import get_broker

        envelope = EventEnvelope(
            event_type=self.event_type,
            source_service=app_settings.SERVICE_NAME,
            payload={**(payload or {}), **extra},
        )
        # Publié à la validation de la transaction en cours (immédiatement
        # s'il n'y en a pas): sans ça, un send() fait depuis un post_save
        # publierait pour une ligne qui n'est pas encore (ou jamais)
        # committée si la transaction englobante échoue ensuite — et
        # inversement, une panne du broker ferait échouer une écriture DB
        # qui n'a rien à voir avec l'événement.
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
    """

    def decorator(func: Callable) -> Callable:
        register(event_type, func)
        return func

    return decorator
