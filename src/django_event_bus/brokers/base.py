"""Interface commune des backends de transport du bus d'événements.

Common interface for event bus transport backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..envelope import EventEnvelope


class BaseBroker(ABC):
    """Interface que tout backend de transport (Redis, Kafka, ...) doit implémenter.

    C'est cette interface, chargée dynamiquement depuis
    `EVENT_BUS["BACKEND"]`, qui permet de changer de broker sans toucher
    au reste de la librairie ni au code applicatif.

    Interface that every transport backend (Redis, Kafka, ...) must implement.

    This interface, loaded dynamically from `EVENT_BUS["BACKEND"]`, is
    what allows swapping the broker without touching the rest of the
    library or the application code.
    """

    def __init__(self, *, service_name: str, options: dict) -> None:
        """Reçoit le nom du service courant et les options de configuration du broker.

        Receives the current service's name and the broker's configuration options.
        """
        self.service_name = service_name
        self.options = options

    @abstractmethod
    def publish(self, envelope: EventEnvelope) -> None:
        """Publie un événement sur le bus.

        Publishes an event on the bus.
        """

    @abstractmethod
    def listen(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        """Boucle bloquante: yield chaque événement reçu pour `event_types`.

        Chaque `EventEnvelope` produit doit ensuite être confirmé via
        `ack()` (succès) ou `fail()` (échec) par l'appelant.

        Blocking loop: yields each event received for `event_types`.

        Each produced `EventEnvelope` must then be confirmed by the
        caller via `ack()` (success) or `fail()` (failure).
        """

    @abstractmethod
    def ack(self, envelope: EventEnvelope) -> None:
        """Confirme le traitement réussi d'un événement.

        Confirms the successful processing of an event.
        """

    @abstractmethod
    def fail(self, envelope: EventEnvelope) -> bool:
        """Signale l'échec du traitement d'un événement.

        Retourne True si l'événement a été abandonné (ex: déplacé en
        dead-letter après trop de tentatives), False s'il sera retenté.

        Signals the failed processing of an event.

        Returns True if the event was abandoned (e.g. moved to
        dead-letter after too many attempts), False if it will be
        retried.
        """

    def close(self) -> None:  # noqa: B027 - no-op volontaire, pas de comportement requis par défaut
        """Libère les ressources (connexions, ...). No-op par défaut.

        Releases resources (connections, ...). No-op by default.
        """
