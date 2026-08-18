from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..envelope import EventEnvelope


class BaseBroker(ABC):
    """Interface que tout backend de transport (Redis, Kafka, ...) doit
    implémenter. C'est cette interface, chargée dynamiquement depuis
    `EVENT_BUS["BACKEND"]`, qui permet de changer de broker sans toucher
    au reste de la librairie ni au code applicatif.
    """

    def __init__(self, *, service_name: str, options: dict):
        self.service_name = service_name
        self.options = options

    @abstractmethod
    def publish(self, envelope: EventEnvelope) -> None:
        """Publie un événement sur le bus."""

    @abstractmethod
    def listen(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        """Boucle bloquante: yield chaque événement reçu pour `event_types`.

        Chaque `EventEnvelope` produit doit ensuite être confirmé via
        `ack()` (succès) ou `fail()` (échec) par l'appelant.
        """

    @abstractmethod
    def ack(self, envelope: EventEnvelope) -> None:
        """Confirme le traitement réussi d'un événement."""

    @abstractmethod
    def fail(self, envelope: EventEnvelope) -> bool:
        """Signale l'échec du traitement d'un événement.

        Retourne True si l'événement a été abandonné (ex: déplacé en
        dead-letter après trop de tentatives), False s'il sera retenté.
        """

    def close(self) -> None:
        """Libère les ressources (connexions, ...). No-op par défaut."""
