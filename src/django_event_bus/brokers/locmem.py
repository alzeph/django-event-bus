"""Broker en mémoire (backend par défaut, sans infra).

In-memory broker (default backend, no infra required).
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator

from ..envelope import EventEnvelope
from .base import BaseBroker

_lock = threading.Lock()
_subscribers: dict[str, set[str]] = {}
_queues: dict[tuple[str, str], queue.Queue[EventEnvelope]] = {}


class LocMemBroker(BaseBroker):
    """Broker 100% en mémoire, partagé au sein du process Python.

    Utile pour les tests unitaires et le développement local sans
    dépendance externe. Ne fonctionne PAS entre process/services
    distincts: c'est le rôle du backend Redis (ou d'un futur Kafka).
    Backend par défaut de la librairie, pour qu'un `pip install` seul
    suffise à faire tourner les tests sans infra.

    100% in-memory broker, shared within the Python process.

    Useful for unit tests and local development without an external
    dependency. Does NOT work across separate processes/services: that
    is the role of the Redis backend (or a future Kafka one). The
    library's default backend, so a plain `pip install` is enough to run
    the tests without infra.
    """

    def publish(self, envelope: EventEnvelope) -> None:
        """Distribue ``envelope`` dans la file de chaque service abonné à son type.

        Distributes ``envelope`` into each service's queue subscribed to its type.
        """
        with _lock:
            for service_name, event_types in _subscribers.items():
                if envelope.event_type in event_types:
                    _queues[(service_name, envelope.event_type)].put(envelope)

    def listen(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        """Enregistre l'abonnement puis renvoie l'itérateur de consommation.

        L'inscription se fait ici, de façon synchrone à l'appel: une
        fonction génératrice n'exécute rien avant le premier next(), ce
        qui laisserait une fenêtre où un publish() juste après l'appel à
        listen() serait perdu faute d'abonné encore enregistré.

        Registers the subscription then returns the consuming iterator.

        Registration happens here, synchronously on call: a generator
        function runs nothing before the first next(), which would leave
        a window where a publish() right after the listen() call would
        be lost for lack of a registered subscriber yet.
        """
        with _lock:
            _subscribers.setdefault(self.service_name, set()).update(event_types)
            for event_type in event_types:
                _queues.setdefault((self.service_name, event_type), queue.Queue())
        return self._consume(event_types)

    def _consume(self, event_types: set[str]) -> Iterator[EventEnvelope]:
        """Yield le prochain événement disponible pour ``event_types``, en boucle.

        Consuming loop: yields the next available event for ``event_types``.
        """
        while True:
            for event_type in event_types:
                q = _queues[(self.service_name, event_type)]
                try:
                    yield q.get(timeout=0.1)
                except queue.Empty:
                    continue

    def ack(self, envelope: EventEnvelope) -> None:
        """Rien à faire: pas de suivi de livraison en mémoire.

        Nothing to do: no delivery tracking in memory.
        """

    def fail(self, envelope: EventEnvelope) -> bool:
        """Rien à retenter en mémoire: l'événement est considéré terminal.

        Nothing to retry in memory: the event is considered terminal.
        """
        return True

    @classmethod
    def reset(cls) -> None:
        """Vide l'état partagé entre process.

        À appeler entre deux tests.

        Clears the state shared across processes.

        To be called between tests.
        """
        with _lock:
            _subscribers.clear()
            _queues.clear()
